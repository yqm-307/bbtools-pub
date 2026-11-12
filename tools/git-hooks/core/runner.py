"""Local Git hook execution: explicit order, isolated rules, fail closed."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tomllib

HOME = Path(__file__).resolve().parent.parent
CONFIG = '.config/bbt-git-hooks.toml'
DEFAULTS = {
    'schema_version': 1,
    'commit': {'rules': ['whitespace', 'format', 'comment-form', 'template-layout']},
    'push': {'rules': ['review-ticket', 'llm-review', 'format', 'secrets']},
    'scope': {'exclude': []},
    'timeout_seconds': 60,
    'format': {'binary': 'clang-format'},
}


FOLDERS = {'commit': 'stages/commit', 'push': 'stages/push'}
META_KEYS = {'id', 'stage', 'kind', 'title', 'fix', 'docs'}
# auto: the hook runs the check itself at this stage; attested: the hook only verifies submitted evidence.
KINDS = ('auto', 'attested')
REPORT_CODE = re.compile(r'E-[A-Z0-9]+(-[A-Z0-9]+)*')


class HookError(Exception):
    pass


class RuleFail(Exception):
    """A rule violation: becomes the standard report (exit 1), unlike HookError (tool error, exit 2)."""

    def __init__(self, code, problems, fix=None):
        super().__init__(code)
        self.code, self.problems, self.fix = code, problems, fix


def git(*args, check=True):
    p = subprocess.run(['git', *args], capture_output=True, text=True, timeout=30)
    if check and p.returncode:
        raise HookError(p.stderr.strip() or f'git {args} failed ({p.returncode})')
    return p


def config():
    root = Path(git('rev-parse', '--show-toplevel').stdout.strip())
    result = copy.deepcopy(DEFAULTS)
    path = root / CONFIG
    if path.exists():
        def merge(dst, src):
            for key, value in src.items():
                if key not in dst or type(value) is not type(dst[key]):
                    raise HookError(f'{CONFIG}: unknown key or invalid type: {key}')
                if isinstance(value, dict):
                    merge(dst[key], value)
                else:
                    dst[key] = value
        merge(result, tomllib.loads(path.read_text()))
    if result['schema_version'] != 1 or result['timeout_seconds'] <= 0:
        raise HookError('invalid schema_version or timeout_seconds')
    for stage in ('commit', 'push'):
        rules = result[stage]['rules']
        if any(not isinstance(r, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', r) for r in rules):
            raise HookError(f'{stage}: invalid rule ID')
        if len(set(rules)) != len(rules):
            raise HookError(f'{stage}: duplicate rule ID')
    if any(not isinstance(p, str) for p in result['scope']['exclude']):
        raise HookError('scope.exclude must contain strings')
    os.chdir(root)
    return result


def load_meta(stage, rule):
    path = HOME / FOLDERS[stage] / 'rules' / rule / 'meta.toml'
    if not path.is_file():
        raise HookError(f'{rule}: missing meta.toml ({path}); copy stages/_template/ to start a rule')
    meta = tomllib.loads(path.read_text())
    if set(meta) != META_KEYS:
        raise HookError(f'{rule}: meta.toml keys must be exactly {sorted(META_KEYS)}, '
                        f'missing {sorted(META_KEYS - set(meta))}, unknown {sorted(set(meta) - META_KEYS)}')
    if any(not isinstance(v, str) or not v.strip() for v in meta.values()):
        raise HookError(f'{rule}: every meta.toml value must be a nonempty string')
    if meta['id'] != rule or meta['stage'] != stage or meta['kind'] not in KINDS:
        raise HookError(f'{rule}: meta.toml id/stage/kind must be {rule}/{stage}/one of {KINDS}')
    return meta


def parse_report(rule, text):
    try:
        rep = json.loads(text)
    except ValueError:
        rep = None
    ok = (isinstance(rep, dict) and {'code', 'problems'} <= set(rep) <= {'code', 'problems', 'fix'}
          and isinstance(rep['code'], str) and REPORT_CODE.fullmatch(rep['code'])
          and isinstance(rep['problems'], list) and rep['problems']
          and all(isinstance(x, str) and x for x in rep['problems'])
          and isinstance(rep.get('fix', ''), str))
    if not ok:
        raise HookError(f'{rule}: exited 1 without a valid report on stdout '
                        '(one JSON object: code "E-...", problems[], optional fix)')
    return rep


def render(rule, meta, rep, passed, skipped, pending):
    lines = [f'FAIL {rule}  [{rep["code"]}]  {meta["title"]} ({meta["kind"]})']
    lines += [f'  问题：{x}' for x in rep['problems']]
    lines.append(f'  怎么办：{rep.get("fix") or meta["fix"]}')
    lines.append(f'  规范（pub 仓库）：{meta["docs"]}')
    summary = f'  已通过：{", ".join(passed) or "无"}    未通过：{rule} ({meta["kind"]})    未运行：{", ".join(pending) or "无"}'
    if skipped:
        summary += f'    已跳过：{", ".join(skipped)}'
    lines.append(summary)
    return '\n'.join(lines)


def skip_rules(values, known):
    tokens = {t for value in values for t in re.split(r'[,\s]+', value) if t}
    unknown = tokens - set(known) - {'all'}
    if unknown:
        raise HookError(f'unknown skip rules: {sorted(unknown)}')
    return set(known) if 'all' in tokens else tokens


def message_skips(path):
    values = []
    for line in Path(path).read_text().splitlines():
        if line.startswith('#') and '>8' in line:
            break
        if line.startswith('--skip-rules'):
            match = re.fullmatch(r'--skip-rules\s+(.+)', line)
            if not match:
                raise HookError('expected --skip-rules rule-name[,rule-name]')
            values.append(match[1])
    return values


def execute(stage, cfg, skipped, context):
    folder = HOME / FOLDERS[stage]
    rules = cfg[stage]['rules']
    passed, skip_list = [], []
    for i, rule in enumerate(rules):
        if rule in skipped:
            print(f'SKIP {rule}', file=sys.stderr)
            skip_list.append(rule)
            continue
        script = folder / 'rules' / rule / 'main.py'
        if not script.is_file():
            raise HookError(f'{rule}: missing script {script}')
        meta = load_meta(stage, rule)
        # Kill the rule process group on timeout, including formatter children.
        with subprocess.Popen([sys.executable, '-I', str(script)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True, start_new_session=True) as p:
            try:
                out, _ = p.communicate(json.dumps(context), timeout=cfg['timeout_seconds'])
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.communicate()
                raise HookError(f'{rule}: timeout; remaining rules not run') from None
            if p.returncode == 1:
                rep = parse_report(rule, out)
                pending = [r for r in rules[i + 1:] if r not in skipped]
                print(render(rule, meta, rep, passed, skip_list, pending), file=sys.stderr)
                return 1
            if p.returncode:
                print(f'ERROR {rule}: remaining rules not run', file=sys.stderr)
                return 2
        print(f'PASS {rule}', file=sys.stderr)
        passed.append(rule)
    return 0


def snapshot(cfg):
    """Freeze the actual index, including the temporary index used by commit --only."""
    tree = git('write-tree').stdout.strip()
    head = git('rev-parse', '--verify', 'HEAD', check=False)
    base = head.stdout.strip() if head.returncode == 0 else git('hash-object', '-t', 'tree', '/dev/null').stdout.strip()
    # Compare against HEAD, not intersected merge parents: incoming changes are checked too.
    return {'config': cfg, 'tree': tree, 'base': base}


def push_updates(text):
    updates = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise HookError('malformed pre-push input')
        local_ref, oid, remote_ref, old = fields
        if not all(re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', x) for x in (oid, old)):
            raise HookError('invalid push object ID')
        updates.append({'ref': local_ref, 'oid': oid, 'remote_ref': remote_ref, 'old': old})
    return updates


def entry(stage):
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-rules', action='append', default=[], metavar='RULE[,RULE]')
    if stage == 'commit':
        parser.add_argument('message_file', nargs='?')
    else:
        parser.add_argument('remote', nargs='?')
        parser.add_argument('url', nargs='?')
    args = parser.parse_args()
    cfg = config()
    values = args.skip_rules
    if stage == 'commit' and args.message_file:
        values += message_skips(args.message_file)
    skipped = skip_rules(values, cfg[stage]['rules'])
    context = snapshot(cfg) if stage == 'commit' else {
        'config': cfg, 'updates': push_updates(sys.stdin.read()), 'remote': args.remote}
    return execute(stage, cfg, skipped, context)


def guarded(call):
    try:
        return call()
    except RuleFail as exc:
        return report(exc.code, exc.problems, exc.fix)
    except (HookError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


def rule_input():
    return json.load(sys.stdin)


def report(code, problems, fix=None):
    """Emit the standard failure report on stdout; the runner renders it. Returns the rule exit code."""
    if not problems:
        return 0
    body = {'code': code, 'problems': problems}
    if fix:
        body['fix'] = fix
    print(json.dumps(body, ensure_ascii=False))
    return 1
