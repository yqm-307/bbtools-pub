"""What a push publishes and which review ticket covers it.

A ticket records the reviewed code commit X and lives in a later, ticket-only commit (a commit
cannot contain its own hash), so the ticket for the newest code commit is looked up in the pushed tip.
"""
import datetime
import json
import re
import sys
from runner import HookError, RuleFail, git

TICKETS = '.config/review-tickets/'
OID = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


def is_null(oid):
    return set(oid) == {'0'}


def empty_tree():
    return git('hash-object', '-t', 'tree', '/dev/null').stdout.strip()


def resolve(rev):
    return git('rev-parse', '--verify', '--end-of-options', f'{rev}^{{commit}}').stdout.strip()


def ancestor(base, tip):
    p = git('merge-base', '--is-ancestor', base, tip, check=False)
    if p.returncode not in (0, 1):
        raise HookError(p.stderr.strip() or 'cannot determine ancestry')
    return p.returncode == 0


def changed_paths(commit):
    p = git('rev-parse', '--verify', '--quiet', f'{commit}^1', check=False)
    parent = p.stdout.strip() if p.returncode == 0 else empty_tree()
    out = git('diff', '--name-only', '-z', '--no-renames', parent, commit, '--').stdout
    return [n for n in out.split('\0') if n]


def plan(ctx, update):
    """tip, base and the newest commit that changed code (None when only tickets are pushed)."""
    tip = resolve(update['oid'])
    if not is_null(update['old']):
        old = resolve(update['old'])
        commits = git('rev-list', f'{old}..{tip}').stdout.split()
        mb = git('merge-base', old, tip, check=False)
        base = mb.stdout.strip() if mb.returncode == 0 else empty_tree()
    else:
        args = ['rev-list', '--boundary', tip]
        if ctx.get('remote'):
            args += ['--not', f'--remotes={ctx["remote"]}']
        lines = git(*args).stdout.split()
        commits = [x for x in lines if not x.startswith('-')]
        bounds = [x[1:] for x in lines if x.startswith('-')]
        base = bounds[0] if bounds else empty_tree()
    code = next((c for c in commits
                 if any(not n.startswith(TICKETS) for n in changed_paths(c))), None)
    return {'tip': tip, 'base': base, 'code': code, 'ref': update['remote_ref']}


def candidates(ctx):
    for update in ctx['updates']:
        if is_null(update['oid']):
            print(f'SKIP {update["remote_ref"]}: deletion has no candidate code', file=sys.stderr)
            continue
        yield plan(ctx, update)


def ticket_path(tip, code):
    names = git('ls-tree', '-r', '--name-only', '-z', tip, '--', TICKETS.rstrip('/')).stdout.split('\0')
    return [n for n in names if re.fullmatch(re.escape(TICKETS) + r'\d{4}-\d{2}-\d{2}/' + code + r'\.json', n)]


def load_ticket(info):
    """Read the ticket for info['code']; a ticket whose result is not pass is not validated further."""
    code, tip = info['code'], info['tip']
    paths = ticket_path(tip, code)
    if not paths:
        raise RuleFail('E-TICKET-MISSING', [
            f'{info["ref"]}: 代码 commit {code} 没有 ticket（应在 {TICKETS}<YYYY-MM-DD>/{code}.json）'])
    if len(paths) > 1:
        raise RuleFail('E-TICKET-INVALID', [f'{code} 有多份 ticket：{", ".join(paths)}'])
    path = paths[0]
    try:
        ticket = json.loads(git('show', f'{tip}:{path}').stdout)
    except ValueError:
        raise RuleFail('E-TICKET-INVALID', [f'{path}: 不是合法 JSON']) from None
    if not isinstance(ticket, dict):
        raise RuleFail('E-TICKET-INVALID', [f'{path}: 顶层必须是 JSON 对象'])
    result = ticket.get('result')
    if result == 'pending':
        raise RuleFail('E-TICKET-PENDING', [f'{path}: result 仍是 pending，ticket 还是未填写的骨架'],
                       '完成审查后填写 result（pass/fail）、reviewer、summary 与各 check，再提交 ticket')
    if result == 'fail':
        raise RuleFail('E-TICKET-REVIEW-FAILED', [f'{path}: result 为 fail，审查未通过，不能 push'],
                       '先修复审查发现的问题，对新的代码 commit 重新审查并生成新的 ticket')
    if result != 'pass':
        raise RuleFail('E-TICKET-INVALID', [f'{path}: result 必须是 pass、fail 或 pending，实际为 {result!r}'])
    return path, ticket


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate(path, ticket, info):
    problems = []
    if ticket.get('schema_version') != 1:
        problems.append('schema_version 必须是 1')
    if ticket.get('commit') != info['code']:
        problems.append(f'commit 是 {ticket.get("commit")!r}，应为被审查的代码 commit {info["code"]}（amend/rebase 后需重新审查并生成）')
    date = ticket.get('date')
    try:
        datetime.date.fromisoformat(date)
        if date != path.split('/')[-2]:
            problems.append(f'date {date} 与所在目录 {path.split("/")[-2]} 不一致')
    except (TypeError, ValueError):
        problems.append('date 必须是 YYYY-MM-DD')
    for field in ('reviewer', 'summary'):
        if not nonempty(ticket.get(field)):
            problems.append(f'{field} 必须是非空字符串')
    checks = ticket.get('checks')
    if not isinstance(checks, list):
        problems.append('checks 必须是数组')
        checks = []
    for i, check in enumerate(checks):
        name = check.get('id') if isinstance(check, dict) else None
        if not nonempty(name) or check.get('kind') not in ('auto', 'attested'):
            problems.append(f'checks[{i}] 需要 id 与 kind（auto 或 attested）')
        elif check.get('status') != 'pass':
            problems.append(f'检查项 {name} 未通过：status={check.get("status")!r}')
    if problems:
        raise RuleFail('E-TICKET-INVALID', [f'{path}: {x}' for x in problems])
    base = ticket.get('base')
    if not (isinstance(base, str) and OID.fullmatch(base)):
        raise RuleFail('E-TICKET-BASE', [f'{path}: base 必须是完整提交哈希'])
    base = resolve(base)
    if base == info['code'] or not ancestor(base, info['code']):
        raise RuleFail('E-TICKET-BASE', [f'{path}: base 必须是被审查 commit 的严格祖先，审查范围为 base..commit'])
