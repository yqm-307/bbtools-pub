"""Adapt existing lexical candidates without promoting their heuristics to violations."""
import re

from cpp import Source
from design import Check, quote
from design_ast import address, before_comment, body, children, direct_calls, functions, line, reference, types, walk
from scanner import scan as comments


def rows(ctx, rule):
    return (row for row in ctx.scan.rows if row['rule'] == rule)


def locks(ctx, result):
    candidates = list(rows(ctx, 'T102'))
    if not candidates:
        if ctx.scan.partial:
            result.gap('LOCK_UNRESOLVED', 'lexical lock scan was incomplete')
        return
    trees = dict(ctx.ast(result, 'LOCK_UNRESOLVED'))
    for row in candidates:
        path, n, name = row['file'], row['line'], row['symbol']
        tree = trees.get(path)
        if not tree:
            continue
        fields = {address(f): f for f in walk(tree) if f['kind'] == 'Field' and f.get('detail') == name}
        fn = next((f for f in functions(tree) if body(f) and line(f) <= n <= f['range']['end']['line'] + 1), None)
        matched = [(nd, fields[reference(nd)]) for nd in walk(body(fn)) if nd['kind'] == 'Member'
                   and 'range' in nd and line(nd) == n and reference(nd) in fields] if fn else []
        matched = [(nd, f) for nd, f in matched if 'CXXThis' not in {x['kind'] for x in walk(nd)}]
        if not matched:
            result.gap('LOCK_UNRESOLVED', f'{path}:{n} lock member or receiver not resolved')
            continue
        _, field = matched[0]
        record = next((x for x in walk(tree) if x['kind'] == 'CXXRecord' and field in children(x)), {})
        protocol = before_comment(ctx.sources[path], line(fn))
        if re.search(r'协议|protocol', protocol, re.I) and name in protocol:
            continue
        result.add(path, n, name, row['message'],
                   dict(lock_decl=dict(type=types(field)[0], owner=record.get('detail'), path=path, line=line(field)),
                        external_access=[dict(path=path, line=n, enclosing=fn['detail'],
                                              expression=ctx.sources[path].splitlines()[n - 1].strip())],
                        protected_data=[], protocol_ref=None, t102_candidate=True))


def forwarders(ctx, result):
    candidates = list(rows(ctx, 'T401'))
    code = 'CHAIN_UNRESOLVED'
    if ctx.scan.partial:
        result.gap(code, 'lexical forwarder candidate scope contains unsupported source', uncovered=False)
        result.reason = code
    if not candidates:
        if ctx.scan.partial:
            # Macro-hidden scope is degraded, but it provides no T401 finding.
            result.status = 'candidate'
        return
    asts, errors = ctx.asts
    trees = dict(asts)
    for row in candidates:
        path, n, name = row['file'], row['line'], row['symbol']
        found = next((node for node in walk(trees.get(path, {})) if node.get('kind') == 'CXXRecord'
                      and node.get('detail') == name and 'range' in node and line(node) == n), {})
        chain = []
        unresolved = False
        for fn in children(found):
            if not body(fn):
                continue
            calls = list(direct_calls(body(fn)))
            if len(calls) != 1:
                unresolved = True
                continue
            call, callee = calls[0]
            params = [address(p) for p in children(fn) if p['kind'] == 'ParmVar']
            args = [reference(arg) for arg in walk(call) if arg['kind'] == 'DeclRef' and reference(arg) in params]
            chain.append(dict(decl=fn['detail'], impl=callee['detail'], line=line(call),
                              params_changed=params != args, return_changed=None,
                              ownership_changed=None, permission_changed=None))
        missing = ()
        if not chain or unresolved:
            if path not in trees:
                detail = errors.get(path) or errors.get('.') or 'no AST covers this T401 candidate'
            elif not found:
                detail = 'T401 candidate class could not be resolved'
            else:
                detail = 'T401 candidate forwarding calls not fully resolved'
            result.gap(code, f'{path}:{n}: {detail}', uncovered=False)
            result.reason = code
            missing = (code,)
        result.add(path, n, name, row['message'],
                   dict(chain=chain, contract_ref=None, callers=[], t401_candidate=True), missing=missing)


def versions(ctx, result):
    candidates = list(rows(ctx, 'T501'))
    path = ctx.design.get('design.versioned-entry', {}).get('contract_file')
    if path is not None and (not isinstance(path, str) or not path.strip()):
        raise ValueError('design.versioned-entry.contract_file requires a path')
    if not path or not (doc := (ctx.root / path).resolve()).is_relative_to(ctx.root) or not doc.is_file():
        result.gap('NO_MIGRATION_CONTRACT', 'configure an existing in-root migration contract')
        return
    doc_lines = doc.read_text(encoding='utf-8').splitlines()
    for row in candidates:
        file, n, symbol = row['file'], row['line'], row['symbol']
        base = re.sub(r'V\d+', '', symbol, count=1)
        text = ctx.sources[file]
        source = Source(file, text, lambda _: False)
        old = re.search(r'\b' + re.escape(base) + r'\b', source.code)
        if not old:
            continue
        notes = [(i, value.strip()) for i, value in enumerate(doc_lines, 1)
                 if re.search(r'\b' + re.escape(symbol) + r'\b', value) and re.search(r'\b' + re.escape(base) + r'\b', value)]
        if not notes:
            result.gap('NO_MIGRATION_CONTRACT', f'{symbol}: no contract mentions the pair')
            continue
        i, value = notes[0]
        ref = quote(doc.relative_to(ctx.root).as_posix(), i, value)
        result.gap('SPELLING_ONLY', 'T501 and contract text do not establish caller identity or migration behavior', uncovered=False)
        result.add(file, n, symbol, 'versioned spelling and prior spelling both occur; review migration',
                   dict(versioned_symbols=[symbol], entry_pairs=[[base, symbol]], callers=[], migration_contract=ref,
                        exit_condition=value if re.search(r'退出条件|exit condition', value, re.I) else None,
                        public_protocol_parallel=None, t501_candidate=True), contract=ref, missing=['SPELLING_ONLY'])


def comment_candidates(ctx, result):
    for path, text in ctx.sources.items():
        if path in ctx.scan.partial:
            result.gap('COMMENT_UNRESOLVED', f'{path}: lexical comment attachment not fully resolved')
            continue
        source = Source(path, text, lambda _: False)
        attached = {c.start: (c, before or after) for c, before, after in source.variable_comments()}
        for cm in comments(text)[0]:
            if cm.start in attached or cm.start == 1 and cm.text.startswith(('/* Copyright', '// SPDX')):
                continue
            if cm.end < len(text.splitlines()) and not text.splitlines()[cm.end].strip() and cm.kind == 'block':
                result.gap('COMMENT_UNRESOLVED', f'{path}:{cm.start}: detached block has no adjacent declaration')
        for row in rows(ctx, 'T202'):
            if row['file'] != path or row['line'] not in attached:
                continue
            cm, inline = attached[row['line']]
            declaration = source.code.splitlines()[cm.start - 1 if inline else cm.end]
            head = re.split(r'[={;\[]', declaration, maxsplit=1)[0]
            name = re.search(r'(\w+)\s*$', head)
            extra = re.findall(r'单位|生命周期|哨兵|顺序|lifetime|sentinel|units?', cm.text, re.I)
            if extra:
                continue
            symbol = name[1] if name else '-'
            # 'restates_name' is intentionally unknown unless the comment repeats
            # the identifier verbatim. T202 is a short-comment heuristic, not translation.
            repeated = bool(name and re.search(r'\b' + re.escape(symbol) + r'\b', cm.text))
            result.add(path, row['line'], symbol, row['message'],
                       dict(comment=dict(path=path, line=cm.start, text=cm.text), target_symbol=symbol,
                            restates_name=True if repeated else None, extra_info=extra, t202_candidate=True))


CHECKS = [Check('1.5', 'cross-object-lock', 'clue', locks, lexical='T102', missing_codes=('LOCK_UNRESOLVED',)),
          Check('2.3', 'forwarding-layer', 'clue', forwarders, lexical='T401', missing_codes=('CHAIN_UNRESOLVED',)),
          Check('5.4', 'versioned-entry', 'clue', versions, ('contract_file',), 'T501',
                missing_codes=('NO_MIGRATION_CONTRACT', 'SPELLING_ONLY')),
          Check('6.4', 'comment-restates-code', 'clue', comment_candidates, lexical='T202',
                missing_codes=('COMMENT_UNRESOLVED',))]
