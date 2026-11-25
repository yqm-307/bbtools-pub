"""Local AST clues; these checks neither simulate execution nor edit source."""
import re

from cpp import LEXEMES
from design import Check
from design_ast import (address, before_comment, body, children, definition_ids, direct_calls,
                        functions, line, location, reference, source_range, split_if, types, walk)


PRIMITIVE = re.compile(r'(?:bool|char|short|int|long(?: long)?|float|double|unsigned(?: int| long(?: long)?| short| char)?|(?:std::)?u?int\d+_t)')


def snippet(text, node):
    return source_range(text, node['range']) if 'range' in node else ''


def params(fn):
    proto = next((n for n in children(fn) if n['kind'] == 'FunctionProto'), {})
    return [p for p in children(proto) if p['kind'] == 'ParmVar']


def canonical(node):
    values = types(node)
    return values[-1].removeprefix('const ') if values else ''


def by_ref(nodes, identifier):
    return [n for n in nodes if reference(n) == identifier]


def behavior_gap(result, *other):
    codes = ('NO_BEHAVIOR_HARNESS', *other)
    for code in codes:
        result.gap(code, {'NO_BEHAVIOR_HARNESS': 'no behavior replay; static facts only',
                          'NO_CONTRACT': 'no applicable machine-readable contract',
                          'PATHS_PARTIAL': 'only simple direct and conditional returns; no exception paths',
                          'IDEMPOTENCY_UNKNOWN': 'idempotency and duplicate effects not observed',
                          'RETRY_HIDDEN': 'transport retry is a source declaration, not observed implementation'}[code],
                   uncovered=False)
    return codes


def units(ctx, result):
    for path, tree in ctx.ast(result, 'TYPE_UNRESOLVED'):
        text = ctx.sources[path]
        seen = set()
        fns = functions(tree)
        eligible = [fn for fn in fns if any(canonical(a) == canonical(b) and PRIMITIVE.fullmatch(canonical(a))
                                           for a, b in zip(params(fn), params(fn)[1:]))]
        eligible_ids = set().union(*(definition_ids(fn) for fn in eligible))
        for fn in eligible:
            ps = params(fn)
            data = body(fn)
            if data and len(children(data)) == 1:
                calls = list(direct_calls(data))
                if len(calls) == 1 and reference(calls[0][1]) in eligible_ids - definition_ids(fn):
                    call = calls[0][0]
                    actual = [reference(n) for arg in children(call)[1:] for n in walk(arg) if n['kind'] == 'DeclRef']
                    if sorted(a for a in actual if a) == sorted(address(p) for p in ps):
                        # The forwarded signature is checked at the receiving declaration.
                        continue
            pairs = [[i, i + 1] for i in range(len(ps) - 1)
                     if canonical(ps[i]) == canonical(ps[i + 1]) and PRIMITIVE.fullmatch(canonical(ps[i]))]
            if not pairs:
                continue
            signature = fn['detail'], tuple(canonical(p) for p in ps)
            if signature in seen:
                continue
            seen.add(signature)
            doc = before_comment(text, line(fn))
            facts = [dict(name=p.get('detail'), type=canonical(p), position=i,
                          unit_ref=doc if p.get('detail') and p['detail'] in doc else None) for i, p in enumerate(ps)]
            missing = behavior_gap(result, *(() if any(p['unit_ref'] for p in facts) else ('NO_CONTRACT',)))
            result.add(path, line(fn), fn['detail'], 'adjacent parameters have the same primitive type',
                       dict(params=facts, same_type_adjacent_pairs=pairs, strong_type=False, swap_compiles=None),
                       missing=missing)


def flag_switch(ctx, result):
    for path, tree in ctx.ast(result, 'BODY_UNKNOWN'):
        text = ctx.sources[path]
        fns = functions(tree)
        defined = set().union(*(definition_ids(n) for n in fns if body(n)))
        calls = list(direct_calls(tree))
        for fn in fns:
            ps = [(i, p) for i, p in enumerate(params(fn)) if canonical(p) == 'bool']
            attribute = bool(re.fullmatch(r'(?:set|enable|disable)_?\w+', fn['detail']))
            if not ps or attribute:
                continue
            data = body(fn)
            if not data:
                if not definition_ids(fn) & defined:
                    result.gap('BODY_UNKNOWN', f'{path}:{line(fn)}: boolean parameter, body unavailable')
                continue
            branches = []
            effects = []
            for stmt in walk(data):
                cond, then, other = split_if(stmt)
                if not cond or not any(by_ref(walk(cond), address(p)) for _, p in ps):
                    continue
                actions = [n for n in walk(then) if n['kind'] in ('Return', 'BinaryOperator', 'CXXOperatorCall',
                                                                 'Call', 'CXXMemberCall')]
                if not actions:
                    continue
                branches.append(dict(line=line(stmt), condition=snippet(text, cond)))
                effects.append(dict(then=snippet(text, then), otherwise=snippet(text, other) if other else None))
            if branches:
                sites = [location(path, call) for call, ref in calls if reference(ref) in definition_ids(fn) and 'range' in call]
                missing = [] if sites else ['CALLERS_PARTIAL']
                if missing:
                    result.gap('CALLERS_PARTIAL', 'no resolved callers in the analyzed TU', uncovered=False)
                result.add(path, line(fn), fn['detail'], 'boolean parameter selects a branch with observable operations',
                           dict(bool_params=[dict(name=p.get('detail'), position=i, doc=None) for i, p in ps],
                                controlled_branches=branches, branch_effects=effects, call_sites=sites,
                                attribute_like_name=False), missing=missing)


def call_order(ctx, result):
    for path, tree in ctx.ast(result, 'INIT_HIDDEN'):
        text = ctx.sources[path]
        records = [n for n in walk(tree) if n['kind'] == 'CXXRecord']
        for fn in functions(tree):
            if fn['kind'] != 'CXXMethod' or not body(fn):
                continue
            owner = next((record for record in records if any(address(f) in definition_ids(fn)
                          for f in children(record) if f['kind'] == 'CXXMethod')), None)
            if not owner or any(f['kind'] == 'CXXConstructor' and 'implicit ' not in f.get('arcana', '') for f in children(owner)):
                continue
            state_ids = {address(n) for n in children(owner) if n['kind'] in ('Var', 'Field') and canonical(n) == 'bool'}
            phases = [dict(name=n['detail'], line=line(n), body_visible=bool(body(n))) for n in children(owner)
                      if n['kind'] == 'CXXMethod' and 'range' in n and 'implicit ' not in n.get('arcana', '')
                      and types(n) and types(n)[0].startswith('void (')]
            if not phases:
                continue
            statements = children(body(fn))
            for i, stmt in enumerate(statements):
                cond, then, other = split_if(stmt)
                if not cond or other or not any(reference(n) in state_ids for n in walk(cond)):
                    continue
                returns = [n for n in walk(then) if n['kind'] == 'Return']
                calls = [(call, ref) for following in statements[i+1:] for call, ref in direct_calls(following)]
                if not calls or not returns or not any(re.fullmatch(r'return\s+(?:0|false|\{\})\s*;?', snippet(text, n)) for n in returns):
                    continue
                missing = behavior_gap(result, 'NO_CONTRACT')
                result.add(path, line(stmt), fn['detail'], 'state guard returns a normal-shaped value before the operation',
                           dict(phases=phases, preconditions=[dict(line=line(stmt), expression=snippet(text, cond))],
                                normal_ops=[dict(line=line(call), name=ref['detail']) for call, ref in calls if 'range' in call],
                                failure_mode='silent', type_constraint=None, docs_ref=None, call_order_observed=[]), missing=missing)
                break


TOKEN = re.compile(LEXEMES.pattern + r'|[A-Za-z_]\w*|::|->\*?|\.\*|[!<>+*/%&|^=\-]=|&&|\|\||\+\+|--|<<=?|>>=?|\S')


def tokenized(text):
    return tuple(m[0] for m in TOKEN.finditer(text) if not m[0].startswith(('//', '/*')))


def macros_in(text):
    return set(re.findall(r'^\s*#\s*define\s+([A-Za-z_]\w*)', text, re.M))


def branches(ctx, result):
    for path, tree in ctx.ast(result, 'BRANCH_UNRESOLVED'):
        text = ctx.sources[path]
        macros = macros_in(text)
        for fn in functions(tree):
            if not body(fn):
                continue
            for stmt in walk(body(fn)):
                cond, then, other = split_if(stmt)
                if not other or any('range' not in n for n in (stmt, cond, then, other)):
                    continue
                lhs, rhs = snippet(text, then), snippet(text, other)
                if macros.intersection(tokenized(snippet(text, cond)) + tokenized(lhs) + tokenized(rhs)):
                    result.gap('BRANCH_UNRESOLVED', f'{path}:{line(stmt)}: condition or branch contains a local macro')
                    continue
                if tokenized(lhs) != tokenized(rhs):
                    continue
                effect = any(n['kind'] in ('Call', 'CXXMemberCall', 'CXXOperatorCall', 'CompoundAssignOperator',
                                            'CXXConstruct', 'CXXNew', 'CXXDelete')
                             or n['kind'] == 'UnaryOperator' and n.get('detail') in ('++', '--')
                             or n['kind'] == 'BinaryOperator' and n.get('detail') == '=' for n in walk(cond))
                result.gap('TEXT_ONLY', 'equal source tokens are not proof of semantic equivalence', uncovered=False)
                result.add(path, line(stmt), fn['detail'], 'two AST branches have identical source tokens',
                           dict(condition_site=location(path, cond), branch_statements=[lhs, rhs], normalized_equal=True,
                                condition_side_effect=True if effect else (False if all(n['kind'] in
                                    ('IntegerLiteral', 'DeclRef', 'ImplicitCast', 'BinaryOperator', 'Paren')
                                    for n in walk(cond)) and 'volatile' not in snippet(text, fn) else None),
                                empty_branch=tokenized(lhs) == ('{', '}')), missing=['TEXT_ONLY'])


def effect_name(ctx, result):
    for path, tree in ctx.ast(result, 'BODY_UNKNOWN'):
        def query_name(name):
            return bool(re.fullmatch(r'(?:peek|front|head|top|size|empty|view)(?:_\w+)?', name))

        text = ctx.sources[path]
        fns = functions(tree)
        defined = set().union(*(definition_ids(n) for n in fns if body(n)))
        fields = {address(n): n for n in walk(tree) if n['kind'] == 'Field' and any(
                  re.search(r'\bstd::(?:deque|vector|list|queue|stack)\s*<', t) for t in types(n))}
        calls = list(direct_calls(tree))
        for fn in fns:
            if fn['kind'] != 'CXXMethod' or not query_name(fn['detail']):
                continue
            if not body(fn):
                if not definition_ids(fn) & defined:
                    result.gap('BODY_UNKNOWN', f'{path}:{line(fn)}: query-shaped method body unavailable')
                continue
            effects = []
            for call, ref in direct_calls(body(fn)):
                if ref.get('detail') not in ('pop', 'pop_back', 'pop_front', 'erase', 'clear') or 'range' not in call:
                    continue
                for node in children(ref):
                    if node['kind'] == 'Member' and reference(node) in fields:
                        effects.append(dict(operation=ref['detail'], field=node['detail'], line=line(call), kind='consume'))
            if effects:
                doc = before_comment(text, line(fn))
                missing = behavior_gap(result, 'NO_CONTRACT')
                result.add(path, line(fn), fn['detail'], 'query-shaped name contains a resolved container removal call',
                           dict(operation=dict(name=fn['detail'], **location(path, fn)), side_effects=effects,
                                contract_ref=None, before_after_assertions=None,
                                call_sites=[location(path, call) for call, ref in calls if reference(ref) in definition_ids(fn)
                                            and 'range' in call]), missing=missing)


CHECKS = [Check('1.2', 'primitive-parameter-pair', 'behavior', units, missing_codes=('TYPE_UNRESOLVED',)),
          Check('3.1', 'boolean-branch-switch', 'clue', flag_switch, missing_codes=('BODY_UNKNOWN', 'CALLERS_PARTIAL')),
          Check('3.2', 'state-gated-operation', 'behavior', call_order, missing_codes=('INIT_HIDDEN',)),
          Check('6.1', 'identical-branch-tokens', 'clue', branches, missing_codes=('BRANCH_UNRESOLVED', 'TEXT_ONLY')),
          Check('6.5', 'query-shaped-consumption', 'behavior', effect_name, missing_codes=('BODY_UNKNOWN',))]
