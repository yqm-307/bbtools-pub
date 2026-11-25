"""Read-only, immutable Git evidence for design history checks."""
from collections import defaultdict
from fnmatch import fnmatchcase
from functools import cached_property
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from cpp import EXTENSIONS, LEXEMES, blank
from design import Check


class HistoryUnavailable(Exception):
    """A Git input could not be read, not a failure in a rule using it."""


class History:
    def __init__(self, ctx):
        self.ctx = ctx
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(PATH='/usr/bin:/bin', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_LAZY_FETCH='1',
                        GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', GIT_NO_REPLACE_OBJECTS='1',
                        GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='core.fsmonitor', GIT_CONFIG_VALUE_0='false',
                        GIT_CONFIG_KEY_1='core.hooksPath', GIT_CONFIG_VALUE_1=os.devnull)
        if Path(self.git('rev-parse', '--show-toplevel').strip()).resolve() != ctx.root:
            raise HistoryUnavailable('history checks require the Git root as --root')
        self.base = self.git('rev-parse', '--verify', '--end-of-options', ctx.baseline + '^{commit}').strip()
        self.tip = self.git('rev-parse', '--verify', 'HEAD^{commit}').strip()

    def call(self, cmd, **kwargs):
        return subprocess.run(cmd, cwd=self.ctx.root, env=self.env, capture_output=True, text=True,
                              timeout=self.ctx.cfg['timeout_seconds'], **kwargs)

    def git(self, *args):
        try:
            proc = self.call(['/usr/bin/git', *args])
        except (subprocess.TimeoutExpired, UnicodeDecodeError) as error:
            raise HistoryUnavailable(str(error)) from error
        if proc.returncode:
            raise HistoryUnavailable(proc.stderr.strip() or f'git {args[0]}: exit {proc.returncode}')
        return proc.stdout

    def text(self, path):
        return self.git('show', f'{self.tip}:{path}')

    @cached_property
    def changed(self):
        paths = self.git('diff', '--name-only', '-z', '--diff-filter=ACM', '--no-renames', '--no-ext-diff',
                         '--no-textconv', self.base, self.tip, '--').split('\0')
        return [p for p in paths if Path(p).suffix in EXTENSIONS and not any(
            fnmatchcase(p, mask) for mask in self.ctx.cfg['scope']['exclude'])]

    def added(self, path):
        diff = self.git('diff', '-U0', '--inter-hunk-context=0', '--no-ext-diff', '--no-textconv', '--no-color',
                        '--no-renames', self.base, self.tip, '--', ':(literal)' + path)
        return [number for start, size in re.findall(r'^@@ -\S+ \+(\d+)(?:,(\d+))? @@', diff, re.M)
                for number in range(int(start), int(start) + int(size or 1))]

    def has_addition(self, commit, path, text):
        diff = self.git('show', '--format=', '--no-notes', '--no-ext-diff', '--no-textconv',
                        '--no-color', '--no-renames', '--unified=0', commit, '--', ':(literal)' + path)
        return any(normalized(row[1:].strip()) == text for row in diff.splitlines()
                   if row.startswith('+') and not row.startswith('+++ '))

    def log(self, *paths):
        return [dict(commit=oid, subject=subject) for row in self.git(
            'log', '--no-show-signature', '--format=%H%x09%s', f'{self.base}..{self.tip}', '--',
            *(':(literal)' + path for path in paths)).splitlines() if '\t' in row
                for oid, subject in [row.split('\t', 1)]]


def history_check(check):
    def run(ctx, result):
        if not ctx.baseline:
            result.gap('NO_BASELINE', 'select the baseline commit with --baseline')
            return
        try:
            if not hasattr(ctx, 'history'):
                ctx.history = History(ctx)
            check(ctx, result, ctx.history)
        except HistoryUnavailable as error:
            result.gap('NO_HISTORY', str(error), uncovered=result.check.kind != 'manual')
            result.reason = 'NO_HISTORY'
    return run


@history_check
def retired(ctx, result, history):
    declarations = ctx.cfg['retired']
    if not declarations:
        result.gap('NO_RETIRED_DECL', 'declare retired identifiers and path scopes with [[retired]]')
        return
    script = Path(__file__).resolve().parents[1] / 'retired-symbol/main.py'
    data = dict(config=ctx.cfg, base=history.base, tree=history.tip)
    p = history.call([sys.executable, '-I', str(script)], input=json.dumps(data))
    if p.returncode == 0:
        if p.stdout.strip() or p.stderr.strip():
            raise ValueError('retired-symbol produced unexpected output: ' + (p.stderr or p.stdout).strip())
        return
    if p.returncode != 1:
        raise ValueError(f'retired-symbol exit {p.returncode}: {(p.stderr or p.stdout).strip()}')
    report = json.loads(p.stdout)
    if report.get('code') != 'E-RETIRED-SYMBOL' or not report.get('problems'):
        raise ValueError('invalid retired-symbol report')
    for problem in report['problems']:
        match = re.fullmatch(r'(.+):(\d+): 已退役标识符 (\w+)', problem)
        if not match:
            raise ValueError(f'unrecognized retired-symbol finding: {problem}')
        path, line, symbol = match.groups()
        rule_index, item = next((i, d) for i, d in enumerate(declarations)
                                if symbol in d['symbols'] and fnmatchcase(path, d['path']))
        contract = ctx.config_quote('[[retired]]', 'symbols', occurrence=rule_index)
        if not contract:
            result.gap('NO_RETIRED_DECL', 'retired declaration cannot be quoted')
            continue
        result.add(path, int(line), symbol, 'retired spelling on a Git-added source line',
                   dict(retired_symbol=symbol, scope_glob=item['path'], new_lines=[int(line)], matched_spelling=symbol,
                        skipped_contexts=['comment', 'literal', 'include operand'], compat_exception=False),
                   contract=contract, status='violation')


def normalized(raw):
    return LEXEMES.sub(lambda m: '' if m[0].startswith(('//', '/*')) else m[0], raw).strip()


def duplicates(history, selector):
    locations = defaultdict(list)
    for path in history.changed:
        lines = history.text(path).splitlines()
        for n in history.added(path):
            raw = lines[n - 1].strip()
            if selector.match(raw):
                locations[normalized(raw)].append(dict(path=path, line=n))
    return [(text, sites) for text, sites in sorted(locations.items()) if len({s['path'] for s in sites}) > 1]


@history_check
def cochange(ctx, result, history):
    result.gap('EXTERNAL_UNKNOWN', 'Git history does not show independent downstream consumers', uncovered=False)
    for text, sites in duplicates(history, re.compile(r'case\s+[^:]+:\s*(?:return|\w+\s*=)')):
        files = [s['path'] for s in sites]
        changes = {}
        for path in files:
            for change in history.log(path):
                if history.has_addition(change['commit'], path, text):
                    changes.setdefault(change['commit'], set()).add(path)
        shared = [dict(commit=oid, files=sorted(paths)) for oid, paths in changes.items() if len(paths) > 1]
        if not shared:
            continue
        result.add(files[0], sites[0]['line'], text, 'same mapping text added to more than one file in the same change',
                   dict(change_set=shared, modules=[], mapping_duplicates=sites, independent_tests=[], knowledge_kind=None))


@history_check
def repeated(ctx, result, history):
    for text, sites in duplicates(history, re.compile(r'(?:static\s+)?constexpr\s.+[=\{]')):
        result.gap('TEXT_ONLY', 'identical changed declarations do not prove shared knowledge', uncovered=False)
        result.add(sites[0]['path'], sites[0]['line'], text, 'matching declaration text added in separate files',
                   dict(duplicate_pairs=sites, knowledge_kind=None, contract_refs=[],
                        change_history=history.log(*(s['path'] for s in sites))), missing=['TEXT_ONLY'])


@history_check
def old_implementation(ctx, result, history):
    result.gap('EXTERNAL_UNKNOWN', 'external consumers and ABI use are not established by source text', uncovered=False)
    if any(re.search(r'\b(?:dlsym|GetProcAddress|register_via_loader)\s*\(', s) for s in ctx.sources.values()):
        result.gap('DYNAMIC_UNKNOWN', 'observed loader spelling; registration targets require inspection', uncovered=False)
    tracked = history.git('ls-tree', '-r', '--name-only', '-z', history.tip).split('\0')
    texts = {p: history.text(p) for p in tracked if Path(p).suffix in EXTENSIONS}
    tokens = {p: LEXEMES.sub(lambda m: blank(m[0]), text) for p, text in texts.items()}
    for path in history.changed:
        candidates = []
        for n, raw in enumerate(tokens[path].splitlines(), 1):
            match = re.match(r'(?:[\w:*&<>]+\s+)+(\b(?:old_|legacy_)\w*)\s*\([^;{}]*\)\s*\{', raw.strip())
            if not match:
                continue
            name = match[1]
            refs = [dict(path=p, line=i) for p, text in tokens.items() for i, value in enumerate(text.splitlines(), 1)
                    if re.search(r'\b' + re.escape(name) + r'\b', value)
                    and ((p, i) != (path, n) or len(re.findall(r'\b' + re.escape(name) + r'\b', value)) > 1)]
            if not refs:
                candidates.append(dict(name=name, line=n))
        if candidates:
            result.add(path, candidates[0]['line'], candidates[0]['name'], 'legacy spellings with no other tracked C++ text matches',
                       dict(old_impl=candidates, refs=[], abi_export=None, dynamic_registration=None,
                            template_instantiation=None, external_consumers=None, replacement=None, deletion_risk=None),
                       missing=['EXTERNAL_UNKNOWN'])


CHECKS = [Check('2.4', 'cochanged-mapping', 'manual', cochange, missing_codes=('EXTERNAL_UNKNOWN',)),
          Check('5.1', 'retired-symbol', 'contract', retired, missing_codes=('NO_RETIRED_DECL',)),
          Check('5.2', 'repeated-declaration', 'clue', repeated, missing_codes=('EXTERNAL_UNKNOWN', 'TEXT_ONLY')),
          Check('5.3', 'legacy-implementation', 'manual', old_implementation,
                missing_codes=('EXTERNAL_UNKNOWN', 'DYNAMIC_UNKNOWN'))]
