"""Opt-in, report-only dispatch for design checks."""
from collections import Counter
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cached_property
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tomllib

from configuration import string_list, validate
from cpp import EXTENSIONS
from design_ast import analyze
import design_zh
from scan import Scan


COMMON_MISSING_CODES = frozenset({
    'NO_AST', 'NO_INDEX', 'NO_BUILD_DB', 'NO_TARGET_GRAPH', 'NO_BOUNDARY_DECL',
    'NO_CONTRACT', 'NO_BASELINE', 'NO_HISTORY', 'NO_BEHAVIOR_HARNESS',
})


@dataclass(frozen=True)
class Check:
    source_ref: str
    slug: str
    kind: str
    run: object
    options: tuple = ()
    lexical: str = ''
    missing_codes: tuple = ()

    @property
    def key(self):
        return f'design.{self.slug}'

    @property
    def aliases(self):
        return (self.source_ref, self.slug)


def registry():
    checks = {}
    for path in sorted(Path(__file__).resolve().parent.parent.glob('rules/_design/*.py')):
        spec = importlib.util.spec_from_file_location('design_' + path.stem, path)
        if spec is None or spec.loader is None:
            raise ValueError(f'cannot load design rule {path}')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for check in module.CHECKS:
            if check.key in checks:
                raise ValueError(f'duplicate design check: {check.key}')
            checks[check.key] = check
    return checks


def aliases(checks):
    result = {}
    for check in checks.values():
        for alias in check.aliases:
            if alias in checks or alias in result:
                raise ValueError(f'duplicate design check alias: {alias}')
            result[alias] = check.key
    return result


def canonical_key(value, checks, legacy):
    if value in checks:
        return value
    if value in legacy:
        return legacy[value]
    raise ValueError(f'unknown design check: {value}')


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def quote(path, line, text):
    return dict(path=path, line=line, quote=text, sha256=sha(text))


def relationship(value):
    if isinstance(value, dict):
        return {k: relationship(v) for k, v in value.items()
                if k not in ('line', 'column', 'end_line', 'start_line', 'invariant_ref')}
    if isinstance(value, list):
        return [relationship(v) for v in value]
    return value


class Result:
    def __init__(self, check):
        self.check = check
        self.rows = []
        self.missing = {}
        self.status = 'manual_pending' if check.kind == 'manual' else 'not_reported'
        self.reason = None

    def validate_missing_code(self, code):
        if not isinstance(code, str) or (code not in COMMON_MISSING_CODES and code not in self.check.missing_codes):
            raise ValueError(f'design check {self.check.key}: unregistered missing-input code {code!r}')

    def gap(self, code, detail, *, uncovered=True):
        self.validate_missing_code(code)
        self.missing.setdefault(code, set()).add(detail)
        if uncovered:
            self.status = 'uncovered'
        if uncovered and self.reason is None:
            self.reason = code

    def static_only(self, **gaps):
        missing = {'NO_BEHAVIOR_HARNESS': 'no behavior replay; static facts only', **gaps}
        for code, detail in missing.items():
            self.gap(code, detail, uncovered=False)
        return list(missing)

    def add(self, file, line, symbol, message, facts, *, contract=None, status='candidate', missing=()):
        missing = list(missing)
        for code in missing:
            self.validate_missing_code(code)
        if self.check.kind == 'manual':
            status = 'manual_pending'
        if self.status == 'not_reported' or (self.status == 'candidate' and status == 'violation'):
            self.status = status
        fingerprint = 'sha256:' + sha(json.dumps(
            [self.check.key, file, symbol, relationship(facts)], sort_keys=True, ensure_ascii=False))
        self.rows.append(dict(key=self.check.key, status=status, severity='warn', file=file,
                              line=line, symbol=symbol or '-', message=message, facts=facts,
                              missing=missing, contract_ref=contract, fingerprint=fingerprint))


class Context:
    def __init__(self, root, path, cfg, design, design_sections, baseline, lexical):
        self.root, self.path, self.cfg, self.design = root, path, cfg, design
        self.design_sections = design_sections
        self.baseline = baseline
        self.scan = Scan(root, cfg, sorted(lexical))
        self.sources = {}
        self.tus = set()
        self.links = {}
        self.partial = set()
        for file in sorted(root.rglob('*')):
            if file.suffix not in EXTENSIONS or not (file.is_file() or file.is_symlink()):
                continue
            rel = file.relative_to(root).as_posix()
            if not self.scan.included(rel):
                continue
            if file.is_symlink():
                self.scan.emit(rel, 1, 'T000', 'symlink skipped')
                self.partial.add(rel)
                continue
            try:
                text = file.read_text(encoding='utf-8')
            except (OSError, UnicodeError) as error:
                self.scan.emit(rel, 1, 'T000', str(error))
                self.partial.add(rel)
                continue
            self.sources[rel] = text
            if lexical:
                self.scan.text(rel, text, lambda p: (root / p).is_file())
        self.partial.update(self.scan.partial)

    @cached_property
    def cdb(self):
        path = self.root / self.design.get('cdb', 'build-vscode/compile_commands.json')
        return path if path.is_file() else None

    @cached_property
    def asts(self):
        if 'cdb' in self.design and self.cdb is None:
            return [], {'.': 'explicit design.cdb path does not exist or is not a file'}
        trees, errors = [], {}
        try:
            for path, tree, diagnostics, links in analyze(self.root, self.cdb, self.sources, self.cfg['timeout_seconds']):
                self.links[path] = links
                if diagnostics:
                    errors[path] = '; '.join(diagnostics)
                    self.partial.add(path)
                else:
                    self.tus.add(path)
                    trees.append((path, tree))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            errors['.'] = str(error)
        if self.cdb:
            self.partial.update(set(self.sources) - self.tus)
        return trees, errors

    def ast(self, result, code='AST_UNAVAILABLE'):
        trees, errors = self.asts
        if errors:
            result.gap(code, '; '.join(f'{path}: {detail}' for path, detail in errors.items()))
        return trees

    def config_quote(self, section, prefix, *, occurrence=0):
        if self.path is None:
            return None
        section = self.design_sections.get(section, section)
        index = -1
        active = False
        for n, line in enumerate(self.path.read_text(encoding='utf-8').splitlines(), 1):
            line = line.strip()
            if line.startswith('['):
                if line == section:
                    index += 1
                active = line == section and index == occurrence
            if active and line.partition('=')[0].strip() == prefix:
                path = self.path.resolve()
                rel = path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else path.name
                return quote(rel, n, line)
        return None


def run(root, path, args):
    checks = registry()
    legacy = aliases(checks)
    raw = tomllib.loads(path.read_text(encoding='utf-8')) if path else {}
    raw_design = raw.pop('design', {})
    cfg = validate(raw)
    if not isinstance(raw_design, dict):
        raise ValueError('unknown [design] key or invalid table')
    design = {}
    design_sections = {}
    for name, value in raw_design.items():
        if name in ('rules', 'manual', 'cdb'):
            design[name] = value
            continue
        key = canonical_key(name, checks, legacy)
        if key in design:
            raise ValueError(f'duplicate design check configuration: {name}')
        design[key] = value
        for alias in (key, checks[key].source_ref, checks[key].slug, name):
            design_sections[f'[design."{alias}"]'] = f'[design."{name}"]'
            design_sections[f'[design."{alias}".graph]'] = f'[design."{name}".graph]'
    active = []
    for name in ('rules', 'manual'):
        values = [canonical_key(value, checks, legacy)
                  for value in string_list(design.get(name, []), f'design.{name}')]
        design[name] = values
        active.extend(values)
    selected = [canonical_key(value, checks, legacy) for value in args.check]
    if len(set(active)) != len(active) or len(set(selected)) != len(selected):
        raise ValueError('duplicate or unknown design check')
    if 'cdb' in design and (not isinstance(design['cdb'], str) or not design['cdb'].strip()):
        raise ValueError('design.cdb requires a path')
    for key in checks.keys() & design.keys():
        opts = design[key]
        if not isinstance(opts, dict) or opts.keys() - set(checks[key].options):
            raise ValueError(f'design.{key}: unknown options or invalid table')
    if any(checks[k].kind != 'manual' for k in design.get('manual', [])):
        raise ValueError('design.manual requires manual check keys')
    keys = sorted(set(selected or checks))
    ctx = Context(root, path, cfg, design, design_sections, args.baseline,
                  {checks[k].lexical for k in keys if k in active and checks[k].lexical})
    summaries, findings, missing = [], [], []
    for key in keys:
        check = checks[key]
        enabled = key in active
        result = Result(check)
        if enabled:
            check.run(ctx, result)
        else:
            result.status = 'disabled'
        summaries.append(dict(key=key, source_ref=check.source_ref, slug=check.slug,
                              **{'class': check.kind}, enabled=enabled,
                              status=result.status, reason=result.reason))
        findings.extend(dict(source_ref=check.source_ref, **row) for row in result.rows)
        missing.extend(dict(key=key, source_ref=check.source_ref, code=code,
                            detail='; '.join(sorted(details)))
                       for code, details in sorted(result.missing.items()))
    findings.sort(key=lambda f: (f['file'], f['line'], f['key'], f['symbol'], f['fingerprint']))
    statuses = Counter(row['status'] for row in summaries)
    manual = [row['key'] for row in summaries if row['status'] == 'manual_pending']
    disabled = [row['key'] for row in summaries if row['status'] == 'disabled']
    hits = Counter(row['key'] for row in findings)
    report = dict(schema_version=2, tool=dict(name='bbtools-lint', version='2'),
                  invocation=dict(root=str(root), config=str(path) if path else None,
                                  baseline=args.baseline, checks=keys, format=args.format),
                  checks=summaries, findings=findings,
                  coverage=dict(mode='design', complete=not (ctx.partial or missing or manual or disabled),
                                files_scanned=len(ctx.sources), tus=sorted(ctx.tus), index='none',
                                partial=sorted(ctx.partial), missing_inputs=missing,
                                manual_pending=manual, disabled=disabled),
                  counts=dict(by_key={row['key']: hits[row['key']] for row in summaries if row['enabled']},
                              by_status=dict(sorted(statuses.items()))))
    chinese = args.lang == 'zh'
    if chinese:
        for f in findings:
            f['message'] = design_zh.finding_message(f)
    if args.format == 'json':
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.format == 'diagnostic':
        from design_diagnostic import print_diagnostics
        print_diagnostics(report, ctx)
    else:
        for f in findings:
            print(f"{f['file']}:{f['line']} {f['key']} {f['status'].upper()} {f['symbol']} {f['message']}")
        for row in summaries:
            print(f".:1 {row['key']} {row['status'].upper()} {row['slug']} findings={hits[row['key']]}")
        for gap in missing:
            print(f".:1 {gap['key']} MISSING {gap['code']} {gap['detail']}", file=sys.stderr)
    return 2 if statuses['uncovered'] else 0
