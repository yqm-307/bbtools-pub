"""Evidence packs for judgments that still require an independent reader."""
from collections import defaultdict
import re

from design import Check, quote
from design_ast import (address, before_comment, body, call_ref, children, definition_ids, direct_calls,
                        functions, line, location, reference, source_range, split_if, types, walk)


def span(text, node):
    return source_range(text, node['range']) if 'range' in node else ''


def dual_writes(ctx, result):
    if not ctx.cdb:
        result.gap('NO_INDEX', 'a compile database is required for field write sites')
        return
    result.gap('WRITES_PARTIAL', 'only plain field assignments within analyzed TUs', uncovered=False)
    result.gap('NO_BEHAVIOR_HARNESS', 'no replay of state transitions', uncovered=False)
    for path, tree in ctx.ast(result, 'NO_INDEX'):
        text = ctx.sources[path]
        for record in walk(tree):
            if record['kind'] != 'CXXRecord' or 'range' not in record or not record.get('detail'):
                continue
            fields = {address(n): n for n in children(record) if n['kind'] == 'Field' and 'range' in n}
            writes, reads, paired = defaultdict(list), defaultdict(list), defaultdict(set)
            for fn in functions(tree):
                if not body(fn):
                    continue
                for node in walk(body(fn)):
                    if node['kind'] != 'Member' or reference(node) not in fields or 'range' not in node:
                        continue
                    reads[reference(node)].append(dict(**location(path, node), enclosing=fn['detail'], operation='reference'))
                for n in walk(body(fn)):
                    lhs = children(n)[0] if children(n) else {}
                    key = reference(lhs)
                    if n['kind'] != 'BinaryOperator' or n.get('detail') != '=' or lhs.get('kind') != 'Member' or key not in fields:
                        continue
                    receiver = next((reference(x) for x in walk(lhs) if x['kind'] == 'DeclRef'), None)
                    if not receiver and not any(x['kind'] == 'CXXThis' for x in walk(lhs)):
                        continue
                    writes[key].append(dict(**location(path, lhs), enclosing=fn['detail'], operation='assignment'))
                    paired[(address(fn), receiver or 'this')].add(key)
            pairs = {tuple(sorted(fields[k]['detail'] for k in group)) for group in paired.values() if len(group) >= 2}
            if not pairs:
                continue
            keys = {k for g in paired.values() if len(g) >= 2 for k in g}
            sorted_keys = sorted(keys, key=lambda k: fields[k]['detail'])
            sites = [site for k in sorted_keys for site in writes[k]]
            fields_info = [dict(member=fields[k]['detail'], type=types(fields[k])[0]) for k in sorted_keys]
            contract = next((quote(path, line(fields[k])-1, doc) for k in sorted_keys
                             if re.search(r'唯一写|single writer|unique writer', (doc := before_comment(text, line(fields[k]))), re.I)), None)
            if not contract:
                result.gap('NO_CONTRACT', 'equal or conflicting meaning of fields is not determined', uncovered=False)
            result.add(path, min(s['line'] for s in sites), record['detail'], 'the same receiver has multiple fields written by the same function',
                       dict(state_subject=dict(owner=record['detail'], fields=fields_info), writers=sites,
                            readers=[site for k in sorted_keys for site in reads[k] if not any(
                                (site['line'], site['enclosing']) == (w['line'], w['enclosing']) for w in writes[k])],
                            dual_write_pairs=[list(pair) for pair in sorted(pairs)], unique_writer_contract=contract,
                            cache_protocol=None), contract=contract)


def simple_transfer(fn):
    statements = children(body(fn))
    if not statements:
        return None
    last = statements[-1]
    if last['kind'] == 'Return' and children(last):
        last = children(last)[0]
    if last['kind'] not in ('Call', 'CXXMemberCall'):
        return None
    calls = list(direct_calls(last))
    return calls[0] if len(calls) == 1 else None


def graph(tree):
    fns = [fn for fn in functions(tree) if body(fn)]
    definitions = {key: fn for fn in fns for key in definition_ids(fn)}
    edges = {}
    for fn in fns:
        if (call := simple_transfer(fn)) and reference(call[1]) in definitions:
            edges[address(fn)] = definitions[reference(call[1])]
    incoming = {address(fn) for fn in edges.values()}
    for start in fns:
        if address(start) in incoming or address(start) not in edges:
            continue
        members = [start]
        seen = {address(start)}
        while (next_fn := edges.get(address(members[-1]))) is not None and address(next_fn) not in seen:
            members.append(next_fn)
            seen.add(address(next_fn))
        yield members


def guard_sites(path, text, fn):
    return [dict(**location(path, n), function=fn['detail'], condition=span(text, cond))
            for n in children(body(fn)) if (cond := split_if(n)[0]) and not split_if(n)[2]
            and any(x['kind'] == 'Return' for x in walk(split_if(n)[1]))]


def unresolved_chain(tree, path, result, *, validation=False):
    nodes = list(walk(tree))
    if not validation and any(n['kind'] == 'FunctionTemplate' and any(
            x['kind'] in ('Call', 'CXXDependentScopeMember', 'UnresolvedLookup') for x in walk(n)) for n in nodes):
        result.gap('DISPATCH_UNRESOLVED', f'{path}: dependent call in a template')
    partial = any(n['kind'] == 'CXXMethod' and ' virtual pure ' in n.get('arcana', '') for n in nodes)
    partial |= any(ref['kind'] == 'Member' and '(*' in ref.get('arcana', '') for _, ref in direct_calls(tree))
    if partial:
        result.gap('FLOW_PARTIAL' if validation else 'CHAIN_PARTIAL',
                   f'{path}: abstract declaration or indirect call not followed', uncovered=False)


def explain_empty_pack(ctx, result, code, shape):
    if result.rows or result.status != 'manual_pending':
        return
    detail = f'no {shape} found in analyzed TUs'
    if ctx.partial:
        result.gap(code, f'{detail}; source coverage is partial (see coverage.partial)', uncovered=False)
    result.reason = code if code in result.missing else detail


def layers(ctx, result):
    check_validation = result.check.key == 'design.repeated-validation'
    code = 'FLOW_PARTIAL' if check_validation else 'CHAIN_PARTIAL'
    for path, tree in ctx.ast(result, code):
        unresolved_chain(tree, path, result, validation=check_validation)
        text = ctx.sources[path]
        for chain in graph(tree):
            if len(chain) < 3:
                continue
            groups = [guard_sites(path, text, fn) for fn in chain]
            common = set.intersection(*(set(site['condition'] for site in group) for group in groups))
            if not common:
                continue
            validations = [site for group in groups for site in group if site['condition'] in common]
            # Only list chains that pass one identical parameter type directly at each hop.
            declarations = []
            for fn in chain:
                proto = next((n for n in children(fn) if n['kind'] == 'FunctionProto'), {})
                ps = [p for p in children(proto) if p['kind'] == 'ParmVar']
                if len(ps) != 1 or not types(ps[0]):
                    break
                declarations.append(ps[0])
            if len(declarations) != len(chain) or len({types(p)[-1] for p in declarations}) != 1:
                continue
            if any(not any(reference(n) == address(p) for n in walk(simple_transfer(fn)[0]))
                   for fn, p in zip(chain[:-1], declarations)):
                continue
            head = chain[0]
            if check_validation:
                result.gap('BOUNDARY_UNKNOWN', 'equal guard spelling does not prove a shared trust boundary', uncovered=False)
                facts = dict(validation_sites=validations, data_source=types(declarations[0])[-1], trust_boundary=None,
                             immutable_guarantee=None, external_input=None, duplicate_pairs=[sorted(common)], removal_risk=None)
            else:
                result.gap('NO_CONTRACT', 'group invariant not established by forwarding and repeated guards', uncovered=False)
                t = types(declarations[0])[-1]
                record = next((n for n in walk(tree) if n['kind'] == 'CXXRecord' and n.get('detail') == t), {})
                facts = dict(group_fields=[n['detail'] for n in children(record) if n['kind'] == 'Field'],
                             layers=[dict(signature=types(fn)[0], function=fn['detail'],
                                          forwarded_fields=[p.get('detail')], revalidations=sites)
                                     for fn, p, sites in zip(chain, declarations, groups)],
                             shared_invariant_contract=None, independent_use_sites=[])
            result.add(path, line(head), head['detail'], 'direct call chain forwards the parameter type past matching guards', facts)
    shape = 'matching validation flow' if check_validation else 'matching parameter-forwarding chain'
    explain_empty_pack(ctx, result, code, shape)


def split_chain(ctx, result):
    for path, tree in ctx.ast(result, 'CHAIN_PARTIAL'):
        unresolved_chain(tree, path, result)
        for chain in graph(tree):
            if len(chain) < 4 or any(len(children(body(fn))) != 1 for fn in chain[:-1]):
                continue
            items = [dict(**location(path, fn), name=fn['detail']) for fn in chain]
            result.gap('NO_BEHAVIOR_HARNESS', 'no real invocation replay through this chain', uncovered=False)
            result.add(path, items[0]['line'], items[0]['name'], 'direct in-TU chain contains consecutive single-call bodies',
                       dict(chain=items, forward_only=items[:-1], contract_per_layer=[None for _ in items],
                            entry=items[0], effect=items[-1], hop_count=len(items)-1, real_call_example=None))
    explain_empty_pack(ctx, result, 'CHAIN_PARTIAL', 'matching consecutive single-call chain')


def extension_points(ctx, result):
    result.gap('EXTERNAL_UNKNOWN', 'repository AST cannot enumerate external consumers', uncovered=False)
    trees, errors = ctx.asts
    if errors:
        result.gap('REGISTRY_PARTIAL', '; '.join(f'{p}: {e}' for p, e in errors.items()), uncovered=False)
    for path, tree in trees:
        text = ctx.sources[path]
        records = [n for n in walk(tree) if n['kind'] == 'CXXRecord' and 'range' in n and n.get('detail')]
        for api in records:
            ids = {address(n) for n in children(api) if n['kind'] == 'CXXMethod' and ' virtual pure ' in n.get('arcana', '')}
            if not ids:
                continue
            doc = before_comment(text, line(api))
            if re.search(r'插件契约|plugin contract', doc, re.I):
                continue
            impls = [dict(name=record['detail'], **location(path, record)) for record in records if any(
                set(re.findall(r'0x[0-9a-f]+', n.get('arcana', '').partition('Overrides:')[2].split('\n')[0])) & ids
                for n in children(record) if n['kind'] == 'CXXMethod')]
            if not impls:
                continue
            sites = [location(path, call) for call, ref in direct_calls(tree) if reference(ref) in ids and 'range' in call]
            result.gap('NO_CONTRACT', 'no adjacent plugin contract; future need is not established', uncovered=False)
            result.add(path, line(api), api['detail'], 'abstract interface has resolved overrides; review its consumers',
                       dict(extension_point=dict(name=api['detail'], **location(path, api)), implementations=impls,
                            consumers=sites, promise_ref=None, variation_demand_ref=None, assembly_cost=None))


def mixed_responsibilities(ctx, result):
    result.gap('INTENT_UNKNOWN', 'separate operations do not prove separate reasons to change', uncovered=False)
    for path, tree in ctx.ast(result, 'INTENT_UNKNOWN'):
        for fn in functions(tree):
            data = body(fn)
            if not data:
                continue
            # A call inside an initializer, a condition or a callback is not a separate
            # top-level operation. Require two distinct standalone void commands as evidence.
            sites = []
            for stmt in children(data):
                while stmt['kind'] == 'ExprWithCleanups' and len(children(stmt)) == 1:
                    stmt = children(stmt)[0]
                ref = call_ref(stmt)
                if (stmt['kind'] == 'Call' and ref and ref['kind'] == 'DeclRef' and 'range' in stmt
                        and ' Function ' in ref.get('arcana', '') and types(stmt)[:1] == ['void']
                        and not ref['detail'].startswith('__builtin_')):
                    sites.append(dict(**location(path, stmt), callee=ref['detail']))
            if len({s['callee'] for s in sites}) < 2 or not any(s['kind'] == 'Decl' for s in children(data)):
                continue
            reasons = []
            if ctx.baseline:
                # Import the trusted sibling adapter locally; the registry owns module loading.
                from design_history import History
                try:
                    reasons = History(ctx).log(path)
                except (OSError, ValueError) as error:
                    result.gap('NO_HISTORY', str(error), uncovered=False)
            n = line(fn)
            result.add(path, n, fn['detail'], 'function body contains distinct resolved calls and local declarations',
                       dict(function=dict(path=path, line=n, metrics=dict(lines=fn['range']['end']['line'] + 2 - n)),
                            responsibility_candidates=sites, data_flow=None, change_reasons=reasons, split_cost=None))


CHECKS = [Check('1.1', 'co-written-fields', 'manual', dual_writes, missing_codes=('WRITES_PARTIAL',)),
          Check('1.3', 'group-forwarding', 'manual', layers, missing_codes=('CHAIN_PARTIAL', 'DISPATCH_UNRESOLVED')),
          Check('2.5', 'interface-consumers', 'manual', extension_points,
                missing_codes=('EXTERNAL_UNKNOWN', 'REGISTRY_PARTIAL')),
          Check('4.3', 'repeated-validation', 'manual', layers, missing_codes=('FLOW_PARTIAL', 'BOUNDARY_UNKNOWN')),
          Check('6.2', 'mixed-operation-body', 'manual', mixed_responsibilities, missing_codes=('INTENT_UNKNOWN',)),
          Check('6.3', 'consecutive-forwarders', 'manual', split_chain,
                missing_codes=('CHAIN_PARTIAL', 'DISPATCH_UNRESOLVED'))]
