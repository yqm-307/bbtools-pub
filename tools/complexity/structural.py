"""Pinned lizard measurements over a working tree or an immutable git tree."""
from collections import Counter
from contextlib import redirect_stderr
from fnmatch import fnmatchcase
import importlib.metadata
import io
import os
from pathlib import Path
import subprocess

from common import VERSION, METRICS, AnalysisError, require, digest, safe_path, read_text, classify


def glob_match(path, pattern):
    def match(parts, masks):
        if not masks:
            return not parts
        if masks[0] == '**':
            return match(parts, masks[1:]) or bool(parts and match(parts[1:], masks))
        return bool(parts and fnmatchcase(parts[0], masks[0]) and match(parts[1:], masks[1:]))
    return match(path.split('/'), pattern.split('/'))


def selected(path, scope):
    return any(glob_match(path, p) for p in scope['include']) and not any(glob_match(path, p) for p in scope['exclude'])


def git(root, *args):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=30)
    require(p.returncode == 0, 'Git operation failed: ' + args[0])
    return p.stdout


def resolve_base(root, ref, mode):
    commit = git(root, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    if mode == 'merge-base':
        commit = git(root, 'merge-base', 'HEAD', commit).decode().strip()
    return commit


def sources(root, config, commit=None):
    scope = config['scope']
    if commit:
        entries = git(root, 'ls-tree', '-rz', '--full-tree', commit).decode().split(chr(0))
        files = {}
        for entry in filter(None, entries):
            metadata, path = entry.split(chr(9), 1)
            mode, kind, oid = metadata.split()
            if selected(path, scope):
                require(mode in ('100644', '100755') and kind == 'blob', 'Unsupported git source: ' + path)
                files[path] = oid
        return files
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != '.git' and not Path(directory, d).is_symlink()
                         and not any(glob_match((Path(directory, d).relative_to(root) / '_').as_posix(), p) for p in scope['exclude']))
        for name in sorted(names):
            path = (Path(directory) / name).relative_to(root).as_posix()
            if selected(path, scope):
                files[path] = None
    return files


def scan(root, config, commit=None):
    try:
        import lizard
        from lizard_languages import get_reader_for
        version = importlib.metadata.version('lizard')
    except (ImportError, importlib.metadata.PackageNotFoundError) as e:
        raise AnalysisError('lizard is missing; use the documented environment') from e
    require(version == config['structural']['backend_version'], 'lizard version does not match configuration')
    analyzer = lizard.FileAnalyzer(lizard.get_extensions(['cognitive']))
    limits = config['limits']
    files = sources(root, config, commit)
    report = {'schema_version': 1, 'tool_version': VERSION, 'kind': 'structural',
              'evaluator': {'backend': 'lizard', 'version': version, 'metrics': list(METRICS), 'policy_version': VERSION},
              'scope': config['scope'], 'revision': commit or 'working-tree',
              'observations': [], 'semantic_status': 'not_evaluated',
              'coverage': {'files_total': len(files), 'files_scanned': 0, 'skipped': []}}
    total = 0
    for index, (path, oid) in enumerate(sorted(files.items())):
        try:
            require(index < limits['max_files'], 'File-count budget exceeded')
            require(Path(path).suffix in ('.cc', '.cpp', '.cxx', '.hpp', '.h', '.hh', '.hxx', '.c'), 'Unsupported source extension')
            if oid:
                size = int(git(root, 'cat-file', '-s', oid))
                require(size <= limits['max_file_bytes'], 'File byte budget exceeded')
                text = git(root, 'cat-file', 'blob', oid).decode('utf-8')
            else:
                text = read_text(safe_path(root, path), limits['max_file_bytes'])
            total += len(text.encode())
            require(total <= limits['max_total_bytes'], 'Total byte budget exceeded')
            diagnostics = io.StringIO()
            with redirect_stderr(diagnostics):
                parsed = analyzer.analyze_source_code(path, text)
            require(not diagnostics.getvalue(), 'lizard emitted a diagnostic')
            counts = Counter(f.long_name for f in parsed.function_list)
            rows = []
            for f in parsed.function_list:
                snippet = chr(10).join(text.splitlines()[f.start_line - 1:f.end_line])
                tokens = [t for t in get_reader_for(path).generate_tokens(snippet)
                          if t.strip() and not t.startswith(('//', '/*'))]
                metrics = {name: getattr(f, name) for name in METRICS}
                code_digest = digest(tokens)
                ambiguous = counts[f.long_name] > 1
                unit = f.long_name + (' [body:' + code_digest[:16] + ']' if ambiguous else '')
                rows.append({'path': path, 'unit': unit, 'line': f.start_line,
                             'identity': 'content_disambiguated' if ambiguous else 'symbol',
                             'end_line': f.end_line, 'metrics': metrics, 'code_digest': code_digest})
            require(len({r['unit'] for r in rows}) == len(rows), 'Identical ambiguous functions cannot be paired safely')
            report['observations'].extend(rows)
            report['coverage']['files_scanned'] += 1
        except (OSError, UnicodeError, ValueError, IndexError, RecursionError) as e:
            report['coverage']['skipped'].append({'path': path, 'reason': str(e)})
    if not files:
        report['coverage']['skipped'].append({'path': '', 'reason': 'No matching sources; check scope'})
    return report


def compare(report, old, config):
    comparable = old is None or (old.get('evaluator') == report['evaluator'] and old.get('scope') == report['scope'])
    previous = {}
    for row in old['observations'] if old else []:
        require(isinstance(row, dict) and all(k in row for k in ('path', 'unit', 'metrics', 'code_digest')), 'Malformed baseline observation')
        key = row['path'], row['unit']
        require(key not in previous, 'Duplicate baseline function')
        require(set(row['metrics']) == set(METRICS) and all(type(n) is int and n >= 0 for n in row['metrics'].values()), 'Malformed baseline metrics')
        previous[key] = row
    findings = []
    matched = set()
    for row in report['observations']:
        key = row['path'], row['unit']
        before = previous.get(key)
        if before:
            matched.add(key)
        # ponytail: ambiguous moves remain unmatched; AST identity can refine this later.
        if before is None and old:
            candidates = [(k, v) for k, v in previous.items() if k not in matched and v['unit'] == row['unit'] and v['code_digest'] == row['code_digest']]
            current_count = sum(v['unit'] == row['unit'] and v['code_digest'] == row['code_digest'] for v in report['observations'])
            if len(candidates) == 1 and current_count == 1:
                before = candidates[0][1]
                matched.add(candidates[0][0])
        for metric, after in row['metrics'].items():
            threshold = config['structural']['thresholds'][metric]
            if after <= threshold:
                continue
            prior = before['metrics'][metric] if before else None
            matched_identity = not (old and before is None and row.get('identity') == 'content_disambiguated')
            status, warning = classify(after, prior, threshold, old is None, comparable and matched_identity)
            rule = 'structural.' + metric
            findings.append({'finding_id': digest([rule, row['path'], row['unit']]), 'rule': rule,
                             'unit': row['unit'], 'path': row['path'], 'line': row['line'],
                             'before': prior, 'after': after, 'threshold': threshold,
                             'status': status, 'warning': warning,
                             'evidence_digest': digest([report['evaluator'], row['code_digest']])})
    report['baseline_revision'] = old.get('revision') if old else None
    report['unmatched_baseline'] = [{'path': p, 'unit': u, 'status': 'not_observed'} for p, u in sorted(set(previous) - matched)]
    report['comparison_status'] = 'comparable' if comparable else 'not_comparable'
    return findings
