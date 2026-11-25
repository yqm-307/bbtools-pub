"""Intra-TU evidence that external callers maintain a container member."""
from collections import defaultdict
import re

from design import Check, quote
from design_ast import address, body, children, function, line, reference, source_range, types, walk
from scanner import scan as comments

COLLECTION = re.compile(r'\bstd::(?:deque|vector|list|map|set|unordered_map|unordered_set)\s*<')
READ = {'front', 'back', 'find', 'empty', 'size', 'begin', 'end', 'cbegin', 'cend', 'count', 'contains', 'at'}
WRITE = {'erase', 'clear', 'pop_back', 'pop_front', 'push_back', 'push_front', 'insert',
         'emplace', 'emplace_front', 'emplace_back', 'resize', 'assign', 'remove', 'splice', 'swap'}


def member_owner_fields(tree):
    fields = {}

    def visit(node, owner=()):
        kind, name = node['kind'], node.get('detail')
        if kind == 'CXXRecord' and name and ' definition ' in node['arcana']:
            owner += (name,)
            access = 'private' if f' class {name} definition ' in node['arcana'] else 'public'
            for child in children(node):
                if child['kind'] == 'AccessSpec':
                    access = child['arcana'].rsplit(' ', 1)[-1]
                elif child['kind'] == 'Field' and 'range' in child:
                    fields[address(child)] = (node, owner, child, access)
                visit(child, owner)
        else:
            for child in children(node):
                visit(child, owner)

    visit(tree)
    return fields


def find_contract(path, text, field, record):
    # A nearby comment is quoted, not interpreted as proof of the invariant.
    for before in (line(field), line(record)):
        nearby = [c for c in comments(text)[0] if c.end == before - 1]
        for cm in nearby:
            if cm.kind == 'line' and re.search(r'契约|序号升序|invariant|contract', cm.text, re.I):
                return quote(path, cm.start, cm.text.strip())
            if cm.kind == 'block':
                content = [re.sub(r'^\s*\*\s?', '', row).strip() for row in cm.text[2:-2].split('\n')]
                for i, row in enumerate(content):
                    if re.search(r'契约|序号升序|invariant|contract', row, re.I):
                        return quote(path, cm.start + i, ''.join(content[i:]))
    return None


def scope_nodes(node):
    yield node
    for child in children(node):
        if not function(child) and child['kind'] != 'Lambda':
            yield from scope_nodes(child)


def collect(path, text, tree, result):
    fields = {k: value for k, value in member_owner_fields(tree).items()
              if any(COLLECTION.search(t) for t in types(value[2]))}
    if not fields:
        return
    methods = {key: {address(n) for n in children(value[0]) if function(n)}
               for key, value in fields.items()}
    accessors = {}
    functions = [n for n in walk(tree) if function(n) and body(n) and 'range' in n and n.get('detail')]
    for fn in functions:
        returns = [n for n in scope_nodes(body(fn)) if n['kind'] == 'Return']
        signature = types(fn)
        if len(returns) != 1 or not signature or not re.search(r'(?<!&)\&\s*\(', signature[0]):
            continue
        if signature[0].lstrip().startswith('const '):
            continue
        value = children(returns[0])
        if len(value) == 1 and value[0]['kind'] == 'Member':
            field = reference(value[0])
            if field in fields and address(fn) in methods[field]:
                accessors[address(fn)] = field

    uses = defaultdict(list)
    read_writes = defaultdict(set)
    owner_ops = defaultdict(set)
    mediated = set()
    for fn in functions:
        aliases = {}

        def root_receiver(node):
            roots = {reference(n) for n in walk(node) if n['kind'] == 'DeclRef'
                     and re.search(r'\b(?:Var|ParmVar) 0x', n.get('arcana', '')) and reference(n)}
            if len(roots) == 1 or (not roots and any(n['kind'] == 'CXXThis' for n in walk(node))):
                members = tuple(reference(n) for n in walk(node) if n['kind'] == 'Member')
                return next(iter(roots), 'this'), members
            return None

        def receiver(node):
            k = node['kind']
            if k == 'Member':
                field = reference(node)
                if field in fields and children(node):
                    return field, root_receiver(children(node)[0]), False
            if k == 'CXXMemberCall' and children(node):
                callee = children(node)[0]
                field = accessors.get(reference(callee))
                if field and children(callee):
                    return field, root_receiver(children(callee)[0]), True
            if k == 'DeclRef' and reference(node) in aliases:
                return aliases[reference(node)]
            if k in ('ImplicitCast', 'Paren', 'ExprWithCleanups') and len(children(node)) == 1:
                return receiver(children(node)[0])
            return None, None, False

        for node in scope_nodes(body(fn)):
            k, cs = node['kind'], children(node)
            if k == 'Var' and cs and types(node) and types(node)[0].endswith(' &'):
                field, root, getter = receiver(cs[-1])
                if field and root and not types(node)[0].startswith('const '):
                    aliases[address(node)] = field, root, getter
            if not cs or 'range' not in node:
                continue
            callee = cs[0]
            op = callee.get('detail')
            refs = []
            if k == 'CXXMemberCall' and op in READ | WRITE and children(callee):
                refs = [receiver(children(callee)[0])]
            if k == 'Call':
                ref = next((n for n in walk(callee) if n['kind'] == 'DeclRef'), {})
                if (ref.get('detail') == 'find' and reference(ref) and 'range' in callee
                        and re.fullmatch(r'std\s*::\s*find', source_range(text, callee['range']))):
                    op = 'find'
                    refs = [receiver(children(children(n)[0])[0]) for arg in cs[1:] for n in walk(arg)
                            if n['kind'] == 'CXXMemberCall' and children(n)
                            and children(n)[0].get('detail') in ('begin', 'end') and children(children(n)[0])]
            for field, root, getter in dict.fromkeys(refs):
                if not field:
                    continue
                record, _, _, _ = fields[field]
                if address(fn) in methods[field] or f' parent {address(record)} ' in fn['arcana']:
                    if address(fn) not in accessors:
                        owner_ops[field].add(fn['detail'])
                    continue
                if getter:
                    mediated.add(field)
                kind = 'write' if op in WRITE else 'read'
                event = dict(function=fn['detail'], line=line(node), op=op, kind=kind)
                uses[field].append((address(fn), event))
                if root:
                    read_writes[(field, address(fn), root)].add(kind)

    for field, occurrences in uses.items():
        responsible = {fn for (key, fn, _), kinds in read_writes.items() if key == field and kinds == {'read', 'write'}}
        if not responsible:
            continue
        events = sorted((event for _, event in occurrences), key=lambda e: e['line'])
        primary = [event for fn, event in occurrences if fn in responsible]
        site = next((event for event in primary if event['op'] in ('front', 'back', 'find', 'at')), primary[0])
        record, owner, declaration, access = fields[field]
        owner_name = '::'.join(owner)
        name = declaration['detail']
        contract = find_contract(path, text, declaration, record)
        missing = {'NO_BEHAVIOR_HARNESS': 'static evidence only; no behavior replay',
                   'CALLERS_PARTIAL': 'only intra-TU, direct container calls and local reference aliases'}
        if not contract:
            missing['NO_CONTRACT'] = 'no adjacent invariant comment found'
        for code, detail in missing.items():
            result.gap(code, detail, uncovered=False)
        result.add(path, site['line'], f'{owner_name}::{name}',
                   'caller queries and mutates a container via the same receiver declaration',
                   dict(owner_type=owner_name, field=dict(name=name, type=types(declaration)[0], access=access),
                        caller_functions=sorted({e['function'] for e in events}), access_sequence=events,
                        owner_operations=sorted(owner_ops[field]),
                        invariant_ref=f"{path}:{contract['line']}" if contract else None,
                        getter_mediated=field in mediated, read_only_use=False),
                   contract=contract, missing=missing)


def check(ctx, result):
    if not ctx.cdb:
        result.gap('NO_INDEX', 'a compile database for the selected snapshot is required')
        return
    for path, tree in ctx.ast(result, 'OWNER_UNRESOLVED'):
        collect(path, ctx.sources[path], tree, result)


CHECKS = [Check('3.3', 'caller-maintains-owner-state', 'behavior', check,
                missing_codes=('OWNER_UNRESOLVED', 'CALLERS_PARTIAL'))]
