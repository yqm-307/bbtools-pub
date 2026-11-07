"""Shared policy and report handling; never mutate baselines or ignores."""
import copy
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import tomllib

VERSION = '0.1.0'
AXES = 'URALG'
METRICS = dict(cognitive_complexity=25, cyclomatic_complexity=15, nloc=100, parameter_count=6)
DEFAULTS = {
    'schema_version': 1, 'quality_policy': 'warn',
    'scope': {'include': ['bbt/**/*.hpp', 'bbt/**/*.cc'], 'exclude': ['**/generated/**', '**/*.pb.cc']},
    'structural': {'backend_version': '1.25.0', 'thresholds': METRICS},
    'semantic': {'rubric_version': 'bbt-semantic-v1', 'confirmations': 2, 'min_delta': 1,
                 'axes': {a: {'enabled': True, 'warn_at': 2} for a in AXES}},
    'limits': {'max_files': 2000, 'max_file_bytes': 1048576, 'max_total_bytes': 33554432},
}


class AnalysisError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AnalysisError(message)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def merge(base, update):
    require(isinstance(update, dict), 'Configuration must be an object')
    result = copy.deepcopy(base)
    for key, value in update.items():
        require(key in base, f'Unsupported configuration key: {key}')
        require(type(value) is type(base[key]), f'Wrong configuration type: {key}')
        result[key] = merge(base[key], value) if isinstance(value, dict) else value
    return result


def config_load(path=None):
    c = merge(DEFAULTS, tomllib.loads(Path(path).read_text()) if path else {})
    require(c['schema_version'] == 1, 'Unsupported schema_version')
    require(c['quality_policy'] in ('warn', 'fail'), 'Invalid quality_policy')
    require(c['scope']['include'], 'Empty scope.include')
    for patterns in c['scope'].values():
        require(all(nonempty(p) and not p.startswith('/') and '..' not in p.split('/') for p in patterns), 'Invalid scope pattern')
    require(all(integer(v, 1, 1024 ** 3) for v in c['limits'].values()), 'Invalid budget')
    require(all(integer(v, 0, 1000000) for v in c['structural']['thresholds'].values()), 'Invalid threshold')
    s = c['semantic']
    require(s['rubric_version'] == 'bbt-semantic-v1', 'Unsupported rubric')
    require(s['confirmations'] in (1, 2) and integer(s['min_delta'], 1, 3), 'Invalid semantic policy')
    require(all(integer(a['warn_at'], 1, 3) for a in s['axes'].values()), 'Invalid semantic threshold')
    return c


def safe_path(root, relative):
    require(isinstance(relative, str), 'Path must be a string')
    p = PurePosixPath(relative)
    require(relative and not p.is_absolute() and '..' not in p.parts and '.git' not in p.parts, 'Unsafe path')
    target = root.joinpath(*p.parts)
    require(target.resolve().is_relative_to(root.resolve()) and not target.is_symlink(), 'Symlink or escaping path')
    return target


def read_text(path, limit=33554432):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, f'File exceeds byte budget: {Path(path).name}')
    return data.decode('utf-8')


def json_load(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, f'Duplicate JSON key: {k}')
            result[k] = v
        return result
    return json.loads(read_text(path), object_pairs_hook=unique)


def baseline_load(path, current):
    if path is None:
        return None
    old = json_load(path)
    require(isinstance(old, dict) and old.get('schema_version') == 1 and old.get('kind') == current['kind'], 'Invalid baseline schema/kind')
    require(old.get('analysis_status') == 'complete' and old.get('coverage', {}).get('skipped') == [], 'Baseline must be a complete report')
    require(isinstance(old.get('observations'), list), 'Missing baseline observations')
    return old


def classify(after, before, threshold, inventory, comparable, minimum=1, inclusive=False):
    exceeds = after >= threshold if inclusive else after > threshold
    if not comparable:
        return 'not_comparable', False
    if inventory:
        return 'inventory', False
    if before is None:
        return 'new', exceeds
    if after - before >= minimum:
        return 'worsened', exceeds
    return ('improved' if after < before else 'unchanged'), False


def apply_ignores(findings, path):
    if path is None:
        return []
    doc = tomllib.loads(read_text(path))
    require(set(doc) <= {'ignore'} and isinstance(doc.get('ignore', []), list), 'Invalid ignore document')
    indexed = {}
    required = {'finding_id', 'rule', 'unit', 'evidence_digest', 'reason'}
    for entry in doc.get('ignore', []):
        require(isinstance(entry, dict) and required <= set(entry) <= required | {'expires_on'}, 'Invalid ignore fields')
        require(all(nonempty(entry[k]) for k in required), 'Ignore fields cannot be empty')
        for key in ('finding_id', 'evidence_digest'):
            require(len(entry[key]) == 64 and all(c in '0123456789abcdef' for c in entry[key]), 'Invalid ignore fingerprint')
        require(entry['finding_id'] not in indexed, 'Duplicate ignore ID')
        if 'expires_on' in entry:
            entry['expires_on'] = date.fromisoformat(str(entry['expires_on']))
        indexed[entry['finding_id']] = entry
    used = set()
    for f in findings:
        entry = indexed.get(f['finding_id'])
        if not entry:
            continue
        used.add(f['finding_id'])
        valid = all(entry[k] == f[k] for k in ('rule', 'unit', 'evidence_digest'))
        valid = valid and entry.get('expires_on', date.max) >= date.today()
        f['ignore_status'] = 'accepted' if valid else 'needs_review'
        f['ignore_reason'] = entry['reason']
        if valid:
            f['warning'] = False
    return sorted(set(indexed) - used)


def finalize(report, findings, config, ignore):
    report['analysis_status'] = 'partial' if report['coverage']['skipped'] else 'complete'
    report['unused_ignores'] = apply_ignores(findings, ignore)
    report['findings'] = findings
    report['effective_config'] = config
    report['config_digest'] = digest(config)
    report['summary'] = {'warnings': sum(f['warning'] for f in findings), 'findings': len(findings)}
    if report['analysis_status'] == 'partial':
        return 2
    return int(config['quality_policy'] == 'fail' and report['summary']['warnings'] > 0)
