"""Evidence from narrow, inspectable control-flow shapes, never runtime claims."""
from collections import defaultdict
import re

from design import Check, quote
from design_ast import (address, body, children, definition_ids, direct_calls, functions, line,
                        location, reference, source_range, split_if, types, walk)


def source(text, node):
    return source_range(text, node['range']) if 'range' in node else ''


def sites(path, nodes):
    return [location(path, n) for n in nodes if 'range' in n]


def references(node, value):
    return any(reference(n) == value for n in walk(node))


def records(tree):
    return [n for n in walk(tree) if n['kind'] == 'CXXRecord' and n.get('detail') and 'range' in n]


def release_paths(ctx, result):
    pairs = {'acquire': 'release', 'fopen': 'fclose', 'malloc': 'free', 'calloc': 'free'}
    for path, tree in ctx.ast(result, 'OWNERSHIP_UNKNOWN'):
        text = ctx.sources[path]
        owners = {rec['detail']: rec for rec in records(tree)}
        for fn in functions(tree):
            if not body(fn) or fn['kind'] == 'CXXDestructor':
                continue
            statements = children(body(fn))
            for start, stmt in enumerate(statements):
                for var in (n for n in children(stmt) if n['kind'] == 'Var'):
                    pair = next(((call, pairs[ref['detail']]) for call, ref in direct_calls(var)
                                 if ref.get('detail') in pairs and 'range' in call), None)
                    if not pair:
                        continue
                    acquisition, release = pair
                    identifier = address(var)
                    owner = next((owners[t] for t in types(var) if t in owners), None)
                    methods = {}
                    if owner:
                        for method in children(owner):
                            data = body(method)
                            if data and any(ref['detail'] == release for _, ref in direct_calls(data)):
                                methods[address(method)] = method
                    if any(m['kind'] == 'CXXDestructor' for m in methods.values()):
                        continue

                    def closes(node):
                        return any((ref.get('detail') == release or reference(ref) in methods) and references(call, identifier)
                                   for call, ref in direct_calls(node))

                    exits, uncovered, releases = [], [], []
                    closed = False
                    for following in statements[start + 1:]:
                        cond, then, other = split_if(following)
                        if cond and not other:
                            sequence = children(then) if then['kind'] == 'Compound' else [then]
                            if all(n['kind'] not in ('If', 'For', 'While', 'CXXTry', 'Switch') for n in sequence):
                                branch_closed = closed
                                for n in sequence:
                                    if closes(n):
                                        releases.append(location(path, n))
                                        branch_closed = True
                                    if n['kind'] == 'Return':
                                        item = dict(**location(path, n), condition=source(text, cond))
                                        exits.append(item)
                                        if not branch_closed:
                                            uncovered.append(item)
                            continue
                        if following['kind'] in ('Call', 'CXXMemberCall', 'ExprWithCleanups') and closes(following):
                            releases.append(location(path, following))
                            closed = True
                        if following['kind'] == 'Return':
                            item = dict(**location(path, following), condition=None)
                            exits.append(item)
                            if not closed:
                                uncovered.append(item)
                    # Require a paired release site before suggesting a resource contract.
                    if uncovered and releases:
                        missing = result.static_only(PATHS_PARTIAL='exception, alias and ownership-transfer paths not modeled')
                        result.add(path, line(acquisition), fn['detail'], 'a return precedes any resolved matching release in a simple path',
                                   dict(acquisitions=sites(path, [acquisition]), owners=[var.get('detail')], exit_paths=exits,
                                        release_sites=releases, raii_wrapper=False, uncovered_paths=uncovered), missing=missing)


def callback_sites(data, field):
    lambdas = {address(n): c for n in walk(data) if n['kind'] == 'Var'
               for c in children(n) if c['kind'] == 'Lambda'}

    def local(node):
        yield node
        for child in children(node):
            if child['kind'] != 'Lambda':
                yield from local(child)

    for node in local(data):
        cs = children(node)
        if node['kind'] != 'CXXOperatorCall' or len(cs) < 2 or "'()'" not in node.get('arcana', ''):
            continue
        if references(cs[1], field):
            yield node
        for key, fn in lambdas.items():
            if references(cs[1], key) and any(
                n['kind'] == 'CXXOperatorCall' and "'()'" in n.get('arcana', '') and len(children(n)) >= 2
                and references(children(n)[1], field) for n in walk(fn)):
                yield node


def once_field(cond):
    for call, method in direct_calls(cond):
        if method.get('detail') == 'exchange' and any(
                n['kind'] == 'CXXBoolLiteral' and n.get('detail') == 'true' for n in children(call)[1:]):
            field = next((n for n in children(method) if n['kind'] == 'Member' and any(
                         'std::atomic<bool>' in t for t in types(n))), None)
            if field:
                return reference(field)
    return None


def guard(method, callbacks, helpers):
    statements = children(body(method))
    for i, stmt in enumerate(statements):
        cond, then, other = split_if(stmt)
        if not cond or other:
            continue
        ret = children(then)[0] if then['kind'] == 'Compound' and len(children(then)) == 1 else then
        field = once_field(cond) if cond['kind'] == 'CXXMemberCall' else None
        rest = {address(n) for following in statements[i+1:] for n in walk(following)}
        if field and ret['kind'] == 'Return' and all(address(n) in rest for n in callbacks):
            return field
        calls = list(direct_calls(cond))
        inside = {address(n) for n in walk(then)}
        if (cond['kind'] == 'CXXMemberCall' and len(calls) == 1 and reference(calls[0][1]) in helpers
                and all(address(n) in inside for n in callbacks)):
            return helpers[reference(calls[0][1])]
    return None


def callbacks(ctx, result):
    for path, tree in ctx.ast(result, 'RACE_UNREPRODUCIBLE'):
        detached = any(ref.get('detail') == 'detach' and any('std::thread' in t for c in children(ref) for t in types(c))
                       for _, ref in direct_calls(tree))
        for owner in records(tree):
            methods = {m['detail']: m for m in children(owner) if m['kind'] == 'CXXMethod' and body(m) and m.get('detail')}
            helpers = {}
            for m in methods.values():
                statements = children(body(m))
                if len(statements) == 1 and statements[0]['kind'] == 'Return' and children(statements[0]):
                    expr = children(statements[0])[0]
                    if expr['kind'] == 'UnaryOperator' and expr.get('detail') == '!' and (key := once_field(expr)):
                        helpers[address(m)] = key
            for field in children(owner):
                if field['kind'] != 'Field' or not any('std::function<' in t for t in types(field)):
                    continue
                cancel, complete = methods.get('cancel'), methods.get('complete')
                if not cancel or not complete:
                    if detached:
                        result.gap('RACE_UNREPRODUCIBLE', f'{path}: detached thread without controllable order')
                    continue
                a, b = list(callback_sites(body(cancel), address(field))), list(callback_sites(body(complete), address(field)))
                if not a or not b:
                    continue
                ga, gb = guard(cancel, a, helpers), guard(complete, b, helpers)
                if ga and ga == gb:
                    continue
                missing = result.static_only(NO_CONTRACT='no terminal cardinality contract')
                result.add(path, line(field), field['detail'], 'cancel and complete contain calls to the same callback member',
                           dict(terminal_callback_decl=dict(name=field['detail'], **location(path, field)),
                                cancel_sites=sites(path, a), complete_sites=sites(path, b), once_guard=False,
                                replay_order=[], notifications_observed=None, contract_max=None), missing=missing)


def failure_result(ctx, result):
    for path, tree in ctx.ast(result, 'ERROR_ERASED'):
        text = ctx.sources[path]
        fns = functions(tree)
        opaque = {address(fn) for fn in fns if not body(fn) and types(fn) and types(fn)[0].startswith('bool (')}
        for fn in fns:
            if not body(fn):
                continue
            statements = children(body(fn))
            if len(statements) == 1 and statements[0]['kind'] == 'Return' and any(
                    reference(ref) in opaque for _, ref in direct_calls(statements[0])):
                result.gap('ERROR_ERASED', f'{path}:{line(fn)}: forwards opaque bool, richer error outcome not inspectable')
            nullable = {address(var): call for stmt in statements for var in children(stmt) if var['kind'] == 'Var'
                        for call, ref in direct_calls(var) if ref.get('detail') == 'fopen' and 'range' in call}
            for stmt in statements:
                cond, branch, other = split_if(stmt)
                if not cond or other or cond['kind'] != 'UnaryOperator' or cond.get('detail') != '!':
                    continue
                origin = next((call for key, call in nullable.items() if references(cond, key)), None)
                if not origin:
                    continue
                calls = {ref.get('detail') for _, ref in direct_calls(branch)}
                if calls - {'log', 'fprintf', 'perror'}:
                    continue
                empty = [n for n in walk(branch) if n['kind'] == 'Return' and
                         re.fullmatch(r'return\s*(?:std::vector<[^;{}]+>\s*)?\{\s*\}\s*;?', source(text, n))]
                if not empty:
                    continue
                missing = result.static_only(NO_CONTRACT='no contract for empty result on file-open failure')
                result.add(path, line(empty[0]), fn['detail'], 'file-open failure branch returns an empty value',
                           dict(failure_sites=sites(path, [origin, cond]), error_type=None,
                                return_values=[source(text, n) for n in empty], contract_empty_semantics=None,
                                caller_checks=[], distinguishability_test=None, log_only=bool(calls)), missing=missing)


def catches(ctx, result):
    for path, tree in ctx.ast(result, 'CATCH_UNRESOLVED'):
        text = ctx.sources[path]
        for fn in functions(tree):
            if not body(fn):
                continue
            statements = children(body(fn))
            if not statements or statements[-1]['kind'] != 'Return' or not re.fullmatch(
                    r'return\s+0\s*;?', source(text, statements[-1])):
                continue
            for attempt in statements[:-1]:
                if attempt['kind'] != 'CXXTry':
                    continue
                for handler in (n for n in children(attempt) if n['kind'] == 'CXXCatch'):
                    handler_body = body(handler)
                    if not handler_body:
                        continue
                    actions = children(handler_body)
                    action_calls = [next(iter(direct_calls(n)), (None, {}))[1].get('detail') for n in actions]
                    if not actions or any(c not in ('log', 'fprintf', 'perror') for c in action_calls):
                        continue
                    caught = next((types(n)[0] for n in children(handler) if n['kind'] == 'Var' and types(n)), '...')
                    result.add(path, line(handler), fn['detail'], 'logging-only catch falls through toward the same literal return',
                               dict(catch_sites=sites(path, [handler]), caught_type=caught, actions=action_calls,
                                    error_propagation=False, outer_exit=source(text, statements[-1]),
                                    contract_ref=None, caller_observes=False))


def retries(ctx, result):
    for path, tree in ctx.ast(result, 'RETRY_HIDDEN'):
        text = ctx.sources[path]
        lines = text.splitlines()
        fns = functions(tree)
        declarations = {key: fn for fn in fns for key in definition_ids(fn)}
        for fn in fns:
            if not body(fn):
                continue
            for loop in (n for n in children(body(fn)) if n['kind'] in ('For', 'While', 'Do')):
                for call, callee in direct_calls(loop):
                    decl = declarations.get(reference(callee))
                    if not decl or 'range' not in call:
                        continue
                    notes = lines[line(decl)-1].partition('//')[2].strip()
                    if not re.search(r'重试|\bretr(?:y|ies)\b', notes, re.I):
                        continue
                    ref = quote(path, line(decl), notes)
                    missing = result.static_only(IDEMPOTENCY_UNKNOWN='idempotency and duplicate effects not observed',
                                                 RETRY_HIDDEN='inner retry is only declared by a source comment')
                    result.add(path, line(loop), fn['detail'], 'loop calls a function documented as retrying internally',
                               dict(retry_layers=[dict(kind='loop', **location(path, loop)),
                                                  dict(kind='declared', declaration=ref, callee=callee['detail'])],
                                    operation_side_effect=None, idempotency_key=None, budget_owner=None,
                                    timeout_path=None, duplicate_write_test=None), contract=ref, missing=missing)
                    break


CHECKS = [Check('1.4', 'resource-release-paths', 'behavior', release_paths,
                missing_codes=('OWNERSHIP_UNKNOWN', 'PATHS_PARTIAL')),
          Check('1.6', 'callback-multiple-paths', 'behavior', callbacks, missing_codes=('RACE_UNREPRODUCIBLE',)),
          Check('4.1', 'empty-value-on-failure', 'behavior', failure_result, missing_codes=('ERROR_ERASED',)),
          Check('4.2', 'logging-only-catch', 'clue', catches, missing_codes=('CATCH_UNRESOLVED',)),
          Check('4.4', 'nested-retry-clue', 'behavior', retries, missing_codes=('IDEMPOTENCY_UNKNOWN', 'RETRY_HIDDEN'))]
