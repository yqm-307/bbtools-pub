"""Directory-discovered rules. Metadata, not dispatch tables, defines extensions."""
import importlib.util
from pathlib import Path
import re
import sys
import tomllib

RULES = Path(__file__).resolve().parents[1] / 'rules'
META_KEYS = {'id', 'interface', 'kind', 'title', 'fix', 'docs'}
OPTIONAL_KEYS = {'default_enabled', 'options'}
ID = re.compile(r'[A-Za-z][A-Za-z0-9-]*')


def load_meta(rule):
    if not isinstance(rule, str) or not ID.fullmatch(rule):
        raise ValueError(f'{rule!r}: invalid rule ID')
    path = RULES / rule / 'meta.toml'
    if not path.is_file():
        raise ValueError(f'{rule}: missing meta.toml ({path}); copy rules/_template/ to start a rule')
    meta = tomllib.loads(path.read_text(encoding='utf-8'))
    missing = META_KEYS - set(meta)
    unknown = set(meta) - META_KEYS - OPTIONAL_KEYS
    if missing or unknown:
        raise ValueError(f'{rule}: missing {sorted(missing)}, unknown {sorted(unknown)} meta keys')
    if any(not isinstance(meta[k], str) or not meta[k].strip() for k in META_KEYS):
        raise ValueError(f'{rule}: required meta values must be nonempty strings')
    if (meta['id'] != rule or meta['kind'] not in ('auto', 'attested')
            or meta['interface'] not in ('cpp', 'git-change', 'git-push')):
        raise ValueError(f'{rule}: invalid id/interface/kind')
    if type(meta.get('default_enabled', False)) is not bool:
        raise ValueError(f'{rule}: default_enabled must be boolean')
    options = meta.get('options', {})
    if not isinstance(options, dict) or any(type(v) is not int or v < 1 for v in options.values()):
        raise ValueError(f'{rule}: option defaults must be positive integers')
    return meta


def defaults():
    return [p.name for p in sorted(RULES.iterdir()) if p.is_dir() and not p.name.startswith(('_', '.'))
            and load_meta(p.name).get('default_enabled', False)]


def load_check(rule):
    path = RULES / rule / 'main.py'
    spec = importlib.util.spec_from_file_location('lint_rule_' + rule.replace('-', '_'), path)
    if spec is None or spec.loader is None:
        raise ValueError(f'{rule}: cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, 'check', None)):
        raise ValueError(f'{rule}: main.py must export check(source, options)')
    return module.check
