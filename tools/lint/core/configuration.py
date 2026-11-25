"""Shared schema for scanning and hooks; repository names belong in adapters/configs."""
import copy
import re
from pathlib import Path
import tomllib
from registry import ID, defaults, load_meta

CONFIG = '.config/lint.toml'
# 阻断级别：fatal 首错即停、error 记为未通过继续执行其余规则；warn/notice 只报告不放行失败。
LEVELS = ('fatal', 'error', 'warn', 'notice')
BLOCKING = ('fatal', 'error')


def string_list(value, name):
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f'{name}: expected nonempty strings')
    return value


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('config must be a table')
    cfg = {'schema_version': 2, 'timeout_seconds': 60, 'scan': {'rules': defaults()},
           'commit': {'rules': []}, 'push': {'rules': []}, 'scope': {'exclude': []},
           'format': {'binary': 'clang-format'}, 'rules': {}, 'exclude': [],
           'retired': [], 'enforce_blocks': False,
           'layout': {'allowed_roots': [], 'allowed_gitlinks': []}}
    if set(data) - set(cfg):
        raise ValueError(f'unknown config keys: {sorted(set(data) - set(cfg))}')
    cfg.update(copy.deepcopy(data))
    if type(cfg['enforce_blocks']) is not bool:
        raise ValueError('enforce_blocks must be boolean')
    if not isinstance(cfg['retired'], list):
        raise ValueError('retired must be an array of tables')
    for item in cfg['retired']:
        if (not isinstance(item, dict) or set(item) != {'path', 'symbols'}
                or not isinstance(item['path'], str) or not item['path'].strip()):
            raise ValueError('retired requires a path glob and symbols')
        names = string_list(item['symbols'], 'retired.symbols')
        if not names or any(not re.fullmatch(r'[A-Za-z_]\w*', n, re.ASCII) for n in names):
            raise ValueError('retired.symbols requires exact C++ identifiers')
    layout = cfg['layout']
    if not isinstance(layout, dict) or set(layout) - {'allowed_roots', 'allowed_gitlinks'}:
        raise ValueError('layout: expected allowed_roots/allowed_gitlinks arrays only')
    cfg['layout'] = {'allowed_roots': string_list(layout.get('allowed_roots', []), 'layout.allowed_roots'),
                     'allowed_gitlinks': string_list(layout.get('allowed_gitlinks', []), 'layout.allowed_gitlinks')}
    if any('/' in root or root in ('.', '..') for root in cfg['layout']['allowed_roots']):
        raise ValueError('layout.allowed_roots must be exact top-level directory names')
    for path in cfg['layout']['allowed_gitlinks']:
        parts = path.split('/')
        if any(not part or part in ('.', '..') for part in parts):
            raise ValueError('layout.allowed_gitlinks must be exact repo-relative paths')
        if parts[0] != 'third-party':
            raise ValueError('layout.allowed_gitlinks must name third-party or a path inside it')
    if type(cfg['schema_version']) is not int or cfg['schema_version'] != 2:
        raise ValueError('schema_version must be 2')
    if type(cfg['timeout_seconds']) is not int or cfg['timeout_seconds'] <= 0:
        raise ValueError('timeout_seconds must be a positive integer')
    for mode in ('scan', 'commit', 'push'):
        section = cfg[mode]
        if not isinstance(section, dict) or set(section) != {'rules'}:
            raise ValueError(f'{mode}: expected rules array only')
        names = string_list(section['rules'], mode + '.rules')
        if len(set(names)) != len(names) or any(not ID.fullmatch(n) for n in names):
            raise ValueError(f'{mode}: duplicate or invalid rule ID')
        if 'retired-symbol' in names and not cfg['retired']:
            raise ValueError('retired-symbol requires at least one [[retired]] entry')
        if 'new-root' in names and not cfg['layout']['allowed_roots']:
            raise ValueError('new-root requires a nonempty layout.allowed_roots list')
        if 'third-party-layout' in names and not cfg['layout']['allowed_gitlinks']:
            raise ValueError('third-party-layout requires a nonempty layout.allowed_gitlinks list')
    if not isinstance(cfg['scope'], dict) or set(cfg['scope']) != {'exclude'}:
        raise ValueError('scope: expected exclude array only')
    string_list(cfg['scope']['exclude'], 'scope.exclude')
    if (not isinstance(cfg['format'], dict) or set(cfg['format']) != {'binary'}
            or not isinstance(cfg['format']['binary'], str) or not cfg['format']['binary'].strip()):
        raise ValueError('format: expected nonempty binary')
    if not isinstance(cfg['rules'], dict):
        raise ValueError('rules must be a table')
    if any('header-implementation' in cfg[stage]['rules'] for stage in ('commit', 'push')):
        settings = cfg['rules'].setdefault('header-implementation', {})
        if not isinstance(settings, dict) or settings.setdefault('level', 'warn') not in ('warn', 'notice'):
            raise ValueError('header-implementation is warning-only (warn or notice)')
    for rule, settings in cfg['rules'].items():
        meta = load_meta(rule)
        if not isinstance(settings, dict) or set(settings) - {'level', 'options'}:
            raise ValueError(f'{rule}: unknown settings; expected level/options')
        if settings.get('level', 'fatal') not in LEVELS:
            raise ValueError(f'{rule}: level must be one of {"/".join(LEVELS)}')
        options = settings.get('options', {})
        if not isinstance(options, dict) or set(options) - set(meta.get('options', {})):
            raise ValueError(f'{rule}: unknown options')
        if any(type(v) is not int or v < 1 for v in options.values()):
            raise ValueError(f'{rule}: thresholds must be positive integers')
    if not isinstance(cfg['exclude'], list):
        raise ValueError('exclude must be an array of tables')
    for item in cfg['exclude']:
        if (not isinstance(item, dict) or set(item) != {'rule', 'path', 'symbol', 'reason'}
                or any(not isinstance(v, str) or not v.strip() for v in item.values())):
            raise ValueError('exclusion requires rule/path/symbol/reason')
        meta = load_meta(item['rule'])
        if item['rule'] == 'T000' or meta['interface'] != 'cpp':
            raise ValueError('symbol exclusions require a C++ candidate rule; T000 cannot be suppressed')
    return cfg


def load_config(path=None):
    return validate(tomllib.loads(Path(path).read_text(encoding='utf-8')) if path else {})


def rule_options(cfg, rule, meta):
    return dict(meta.get('options', {}), **cfg['rules'].get(rule, {}).get('options', {}))
