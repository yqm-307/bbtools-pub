"""Adapt existing lexical candidates without promoting their heuristics to violations."""
import re

from cpp import Source
from design import Check, quote
from design_ast import address, before_comment, body, call_ref, children, direct_calls, functions, line, reference, types, walk
from scanner import scan as comments


def rows(ctx, rule):
    return (row for row in ctx.scan.rows if row['rule'] == rule)


def unwrap(node):
    while (node['kind'] in ('Paren', 'ImplicitCast', 'ExprWithCleanups', 'CXXBindTemporary', 'MaterializeTemporary')
           and len(children(node)) == 1):
        node = children(node)[0]
    return node


def is_self_value(expr):
    value = unwrap(expr)
    if value['kind'] == 'CXXThis':
        return True
    callee = call_ref(value)
    if (value['kind'] != 'CXXMemberCall' or not callee or callee.get('detail') != 'shared_from_this'
            or len(children(callee)) != 1):
        return False
    receiver = children(callee)[0]
    return (unwrap(receiver)['kind'] == 'CXXThis'
            and any(t.startswith(('std::enable_shared_from_this<', 'const std::enable_shared_from_this<'))
                    for t in types(receiver)))


def locks_self(fn, member):
    # A pointer obtained from this->member points to the member's object, not necessarily to this.
    if len(children(member)) != 1:
        return False
    base = unwrap(children(member)[0])
    if base['kind'] == 'CXXOperatorCall' and (call_ref(base) or {}).get('detail') == 'operator->' and len(children(base)) == 2:
        base = unwrap(children(base)[1])
    if is_self_value(base):
        return True
    if base['kind'] != 'DeclRef':
        return False
    key = reference(base)
    var = next((v for v in walk(body(fn)) if v['kind'] == 'Var' and address(v) == key), None)
    exprs = [n for n in children(var) if n.get('role') == 'expression'] if var else []
    if len(exprs) != 1 or not is_self_value(exprs[0]):
        return False
    # Do not infer identity from assignments: a write on one branch need not run on the lock's path.
    for op in walk(body(fn)):
        parts = children(op)
        if op['kind'] == 'BinaryOperator' and op.get('detail') == '=' and parts:
            target = parts[0]
        elif op['kind'] == 'CXXOperatorCall' and (call_ref(op) or {}).get('detail') == 'operator=' and len(parts) >= 2:
            target = parts[1]
        else:
            continue
        if reference(unwrap(target)) == key:
            return False
    return True


def locks(ctx, result):
    candidates = list(rows(ctx, 'T102'))
    if not candidates:
        if ctx.scan.partial:
            result.gap('LOCK_UNRESOLVED', 'lexical lock scan was incomplete')
        return
    trees = dict(ctx.ast(result, 'LOCK_UNRESOLVED'))
    findings = {}
    for row in candidates:
        path, n, name = row['file'], row['line'], row['symbol']
        tree = trees.get(path)
        if not tree:
            continue
        fields = {address(f): f for f in walk(tree) if f['kind'] == 'Field' and f.get('detail') == name}
        fn = next((f for f in functions(tree) if body(f) and line(f) <= n <= f['range']['end']['line'] + 1), None)
        matched = [(nd, fields[reference(nd)]) for nd in walk(body(fn)) if nd['kind'] == 'Member'
                   and 'range' in nd and line(nd) == n and reference(nd) in fields] if fn else []
        if not matched:
            result.gap('LOCK_UNRESOLVED', f'{path}:{n} lock member or receiver not resolved')
            continue
        external = [field for member, field in matched if not locks_self(fn, member)]
        if not external:
            continue
        field = external[0]
        expression = ctx.sources[path].splitlines()[n - 1].strip()
        record = next((x for x in walk(tree) if x['kind'] == 'CXXRecord' and field in children(x)), {})
        protocol = before_comment(ctx.sources[path], line(fn))
        if re.search(r'协议|protocol', protocol, re.I) and name in protocol:
            continue
        key = (path, address(field))
        entry = findings.setdefault(key, dict(
            path=path,
            line=n,
            name=name,
            message=row['message'],
            facts=dict(lock_decl=dict(type=types(field)[0], owner=record.get('detail'), path=path, line=line(field)),
                       external_access=[], protected_data=[], protocol_ref=None, t102_candidate=True)))
        entry['facts']['external_access'].append(
            dict(path=path, line=n, enclosing=fn['detail'], expression=expression))

    for entry in findings.values():
        result.add(entry['path'], entry['line'], entry['name'], entry['message'], entry['facts'])


OWNERSHIP_SPELLINGS = ('unique_ptr', 'shared_ptr', 'weak_ptr', 'make_unique', 'make_shared')
SYNC_SPELLINGS = ('mutex', 'lock_guard', 'unique_lock', 'scoped_lock', 'shared_lock',
                  'condition_variable', 'atomic', 'semaphore', 'latch', 'barrier')


def walk_with_parents(node, parents=()):
    yield node, parents
    for child in children(node):
        yield from walk_with_parents(child, parents + (node,))


def qualified_scope(parents):
    """Accumulated namespace/record spelling of a node's enclosing scopes, in order."""
    parts = []
    for node in parents:
        if node['kind'] == 'Namespace':
            spelling = node.get('detail', '').strip(':')
            if spelling:
                parts.extend(spelling.split('::'))
        elif node['kind'] in ('CXXRecord', 'ClassTemplate') and node.get('detail'):
            parts.append(node['detail'])
    return parts


def signature(node):
    return types(node)[0] if types(node) else ''


def return_type(node):
    value = signature(node)
    return value.rsplit(' -> ', 1)[-1].strip() if ' -> ' in value else value.split(' (', 1)[0].strip()


def spellings(node):
    found = set()
    for child in walk(node):
        found.update(types(child))
    return found


def single_transfer(fn_node):
    """The delegate call when the body is exactly one statement that is or returns one call."""
    stmts = children(body(fn_node) or {})
    if len(stmts) != 1:
        return None
    stmt = stmts[0]
    while stmt['kind'] == 'ExprWithCleanups' and len(children(stmt)) == 1:
        stmt = children(stmt)[0]
    if stmt['kind'] == 'Return':
        if len(children(stmt)) != 1:
            return None
        stmt = children(stmt)[0]
        while stmt['kind'] in ('ExprWithCleanups', 'ImplicitCast', 'Paren', 'CXXConstruct') \
                and len(children(stmt)) == 1:
            stmt = children(stmt)[0]
    if stmt['kind'] not in ('Call', 'CXXMemberCall', 'CXXOperatorCall'):
        return None
    calls = list(direct_calls(stmt))
    return calls[0] if len(calls) == 1 else None


def expression(node):
    """Strip implicit sugar: casts, parens, construction and copy-init wrappers."""
    seen = 0
    while (node['kind'] in ('ImplicitCast', 'Paren', 'CXXConstruct', 'CXXBindTemporary',
                            'MaterializeTemporary', 'ExprWithCleanups')
           and children(node) and children(node)[0]['kind'] != 'Type' and seen < 8):
        node = children(node)[0]
        seen += 1
    return node


def argument_passthrough(fn_node, call, target_node=None):
    """Every parameter forwarded exactly once, in order, directly into the delegate call.

    Parameters the wrapper does not have cannot be adapted, so a parameterless wrapper
    passes this check trivially; adaptation of real arguments is what disqualifies.
    """
    params = [address(p) for p in children(fn_node) if p['kind'] == 'ParmVar']
    callee = call_ref(call)
    args = []
    for child in children(call):
        target = expression(child)
        if target is callee:
            continue  # the callee reference itself, never an argument
        if target['kind'] in ('Type', 'Record', 'Builtin', 'Member') or target.get('kind') is None:
            continue
        if target['kind'] == 'CXXThis':
            continue  # the receiver object of a member delegate, not a forwarded argument
        args.append(reference(target) if target['kind'] == 'DeclRef' else None)
    if not args and target_node is not None:
        if any(child['kind'] == 'ParmVar' and ' cinit' in child.get('arcana', '')
               for child in children(target_node)):
            return False
    return len(args) == len(params) and args == params


def callee_target(callee):
    ref_types = types(callee)
    return ref_types[3] if len(ref_types) >= 4 else None


def delegate_evidence(callee):
    """Return only a target recorded by Clang's resolved reference arcana.

    The spelling of an unresolved function is not enough to prove a delegation
    target. Function pointers, dependent calls and parser recovery therefore
    fail closed instead of becoming forwarding-layer findings.
    """
    target_ref = reference(callee)
    if not target_ref or not re.search(rf'\b(?:Function|CXXMethod)\s+{re.escape(target_ref)}\b',
                                       callee.get('arcana', '')):
        return None
    return callee_target(callee)


def member_keys(callee, scope=()):
    ref_types = types(callee)
    if len(ref_types) < 4 or not ref_types[1]:
        return ()
    record = ref_types[3]
    names = {record}
    names.update('::'.join((*scope[:index], record)) for index in range(1, len(scope) + 1))
    return tuple((name, ref_types[1], ref_types[0]) for name in names)


def access_level(record, method):
    """Resolve access from direct AccessSpec AST children, ignoring comments."""
    arcana = record.get('arcana', '')
    default = 'public' if re.search(r'\bstruct\b', arcana) else 'private'
    current = default
    for child in children(record):
        if child.get('kind') != 'AccessSpec' or 'range' not in child:
            continue
        if line(child) > line(method):
            break
        label = re.search(r'\b(public|protected|private)\b', child.get('arcana', ''))
        if not label:
            return None
        current = label.group(1)
    return current


def semantic_exclusions(record, methods, trees, qrecord):
    """Type-marker, public-interface, ownership, synchronization or error-conversion
    semantics each mean the class is not a profitless layer even when its shape matches."""
    reasons = set()
    if any(access_level(record, method) in ('public', 'protected')
           or ' virtual ' in method.get('arcana', '') or 'Overrides:' in method.get('arcana', '')
           for method, _t in methods):
        reasons.add('public_interface')
    joined = ' '.join(s for fn_node, _t in methods for s in spellings(body(fn_node))) \
        + ' ' + record.get('arcana', '')
    if any(word in joined for word in OWNERSHIP_SPELLINGS):
        reasons.add('ownership')
    if any(word in joined for word in SYNC_SPELLINGS):
        reasons.add('synchronization')
    short = qrecord.split('::')[-1]
    for path, tree in trees.items():
        record_nodes = []
        for node in walk(tree):
            arcana = node.get('arcana', '')
            if short and short in arcana:
                record_nodes.append(node)
            if node['kind'] in ('CXXBaseSpecifier', 'BaseSpecifiers') and short in arcana:
                reasons.add('public_interface')
        # A record spelling inside a template argument or specialization carries type
        # selection semantics even when the project uses its own trait vocabulary.
        positions = [n for n in record_nodes if n['kind'] in ('TemplateArgument', 'Type', 'TemplateSpecialization')]
        if positions:
            reasons.add('type_marker')
    return sorted(reasons)


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

    # Index call sites by (qualified record, method name, signature). Header-defined
    # classes are re-declared per TU, so AST addresses only dedupe within one TU.
    call_sites = {}
    for tpath, tree in trees.items():
        for node, parents in walk_with_parents(tree):
            if node['kind'] not in ('Call', 'CXXMemberCall', 'CXXOperatorCall'):
                continue
            callee = call_ref(node)
            if callee is None:
                continue
            keys = member_keys(callee, qualified_scope(parents))
            if not keys or 'range' not in node:
                continue
            caller_fn = next((p for p in reversed(parents)
                              if p['kind'] in ('CXXMethod', 'Function', 'CXXConstructor', 'CXXDestructor')
                              and body(p)), None)
            site = dict(path=tpath, line=line(node),
                        caller=(caller_fn.get('detail') or '<unnamed>') if caller_fn else '<file-scope>',
                        caller_node=caller_fn)
            for key in keys:
                call_sites.setdefault(key, []).append(site)

    for row in candidates:
        path, n, name = row['file'], row['line'], row['symbol']
        found, found_parents = None, ()
        for node, parents in walk_with_parents(trees.get(path, {})):
            if (node.get('kind') in ('CXXRecord', 'ClassTemplate') and node.get('detail') == name
                    and 'range' in node and line(node) == n):
                found, found_parents = node, parents
                break
        if found is None:
            detail = (errors.get(path) or errors.get('.') or 'no AST covers this T401 candidate') \
                if path not in trees else 'T401 candidate class could not be resolved'
            result.gap(code, f'{path}:{n}: {detail}', uncovered=False)
            result.reason = code
            continue

        qrecord = '::'.join([*qualified_scope(found_parents), name])
        methods, chain = [], []
        resolved = True
        receivers = set()
        for fn_node in children(found):
            if not body(fn_node) or fn_node['kind'] not in ('CXXMethod', 'CXXConversion'):
                continue
            if ' static ' not in fn_node.get('arcana', ''):
                resolved = False
                continue
            transfer = single_transfer(fn_node)
            if transfer is None:
                resolved = False
                continue
            call, callee = transfer
            target = delegate_evidence(callee)
            if target is None:
                resolved = False
                continue
            target_ref = reference(callee)
            target_node = next((node for node in walk(trees[path])
                                if address(node) == target_ref and node['kind'] in
                                ('Function', 'CXXMethod', 'CXXConstructor', 'CXXDestructor', 'CXXConversion')),
                               None)
            if target_node is None:
                resolved = False
                continue
            fn_types = types(fn_node)
            callee_types = types(callee)
            if not fn_types or not callee_types:
                resolved = False
                continue
            fn_return = return_type(fn_node)
            callee_return = return_type(callee)
            if fn_return != callee_return:
                # A differing return type means the wrapper adapts the result,
                # including implicit error conversion. That is layer value, not
                # profitless forwarding.
                resolved = False
                continue
            receivers.add(target)
            passthrough = argument_passthrough(fn_node, call, target_node)
            methods.append((fn_node, transfer))
            chain.append(dict(decl=fn_node['detail'], impl=callee.get('detail'), line=line(call),
                              delegate_target=target,
                              delegate_location=dict(path=path, line=line(target_node)),
                              params_changed=not passthrough, return_changed=None,
                              ownership_changed=None, permission_changed=None))
        if not chain or not resolved:
            result.gap(code, f'{path}:{n}: T401 candidate forwarding calls not fully resolved',
                       uncovered=False)
            result.reason = code
            continue
        if len(receivers) > 1:
            # Several receiver types: the class mixes facades, it is not one forwarding layer.
            result.gap(code, f'{path}:{n}: forwarding methods delegate to different receiver types',
                       uncovered=False)
            result.reason = code
            continue
        if any(entry['params_changed'] for entry in chain):
            # Parameter adaptation is exactly the value a layer can carry; not pure forwarding.
            result.gap(code, f'{path}:{n}: forwarding methods adapt arguments instead of passing them through',
                       uncovered=False)
            result.reason = code
            continue

        exclusions = semantic_exclusions(found, methods, trees, qrecord)
        wrapper_keys = {(qrecord, fn_node.get('detail') or '', signature(fn_node)) for fn_node, _t in methods}
        callers = []
        for key in wrapper_keys:
            for site in call_sites.get(key, []):
                if site['caller_node'] is not None and any(site['caller_node'] is fn_node for fn_node, _t in methods):
                    continue  # the wrappers' own delegate calls are not users of the layer
                internal = 'internal-linkage' in (methods[0][0].get('arcana', ''))
                if internal and site['path'] != path:
                    continue  # internal linkage: callers can only live in the same TU
                callers.append(dict(path=site['path'], line=site['line'], caller=site['caller']))
        callers = dedupe_sites(sorted(callers, key=lambda c: (c['path'], c['line'], c['caller'])))
        if callers and not exclusions:
            result.add(path, n, name, row['message'],
                       dict(chain=chain, contract_ref=None, callers=callers,
                            delegate_target=chain[0].get('delegate_target'),
                            exclusions_checked=['type_marker', 'public_interface', 'ownership', 'synchronization'],
                            t401_candidate=True))


def dedupe_sites(sites):
    seen, out = set(), []
    for site in sites:
        key = (site['path'], site['line'], site['caller'])
        if key not in seen:
            seen.add(key)
            out.append(site)
    return out


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


def comment_label(text):
    """Remove comment markup, not words or operators from the explanation."""
    text = re.sub(r'^(?://[/!]?<?|/\*[*!]?<?)', '', text).removesuffix('*/')
    text = re.sub(r'(?m)^\s*\* ', '', text)
    return re.sub(r'^(?:@brief|\\brief)\s+', '', text.strip()).rstrip('.。').strip()


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
            if not name:
                continue
            symbol = name[1]
            label = comment_label(cm.text)
            repeated = label in (symbol, f'`{symbol}`')
            if not repeated:
                # A short local note often labels a step, not the variable underneath it.
                offset = (source.newlines[cm.start - 2] + 1 if cm.start > 1 else 0) + cm.start_col
                if source.in_body(offset) or not re.fullmatch(r'[\u3400-\u9fff]{1,8}|[A-Za-z]+(?: [A-Za-z]+){0,2}', label):
                    continue
                if re.search(r'单位|生命周期|哨兵|顺序|锁内|锁外|析构|不得|必须|仅在|\b(?:lifetime|sentinel|units?|only|before|after)\b', label, re.I):
                    continue
            result.add(path, row['line'], symbol, row['message'],
                       dict(comment=dict(path=path, line=cm.start, text=cm.text), target_symbol=symbol,
                            restates_name=True if repeated else None, extra_info=[], t202_candidate=True))


CHECKS = [Check('1.5', 'cross-object-lock', 'clue', locks, lexical='T102', missing_codes=('LOCK_UNRESOLVED',)),
          Check('2.3', 'forwarding-layer', 'clue', forwarders, lexical='T401', missing_codes=('CHAIN_UNRESOLVED',)),
          Check('5.4', 'versioned-entry', 'clue', versions, ('contract_file',), 'T501',
                missing_codes=('NO_MIGRATION_CONTRACT', 'SPELLING_ONLY')),
          Check('6.4', 'comment-restates-code', 'clue', comment_candidates, lexical='T202',
                missing_codes=('COMMENT_UNRESOLVED',))]
