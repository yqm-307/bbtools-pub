"""Declared boundaries checked against resolved includes or AST declarations."""
from fnmatch import fnmatchcase
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

from configuration import string_list
from design import Check
from design_ast import function, line, walk


def matches(value, patterns):
    return any(fnmatchcase(value, pattern) for pattern in patterns)


def target_map(opts):
    targets = opts.get('targets', {})
    if not isinstance(targets, dict) or any(not isinstance(x, str) or not x.strip() for x in targets.values()):
        raise ValueError('design targets must map path globs to target names')
    return targets


def target(path, targets):
    matched = {name for glob, name in targets.items() if fnmatchcase(path, glob)}
    return next(iter(matched)) if len(matched) == 1 else None


def include_edges(ctx, result):
    # Only clangd-resolved links are evidence of active includes, not regex paths.
    ctx.ast(result, 'INCLUDE_UNRESOLVED')
    for source, links in sorted(ctx.links.items()):
        for item in links or []:
            uri = urlparse(item.get('target', ''))
            if uri.scheme != 'file' or uri.netloc:
                continue
            header = Path(unquote(uri.path))
            if header.is_relative_to(ctx.root):
                n = item['range']['start']['line'] + 1
                yield source, header.relative_to(ctx.root).as_posix(), n, ctx.sources[source].splitlines()[n - 1].strip()


def private_headers(ctx, result):
    opts = ctx.design.get('design.private-header-boundary', {})
    private = string_list(opts.get('private', []), 'design.private-header-boundary.private')
    allowed = string_list(opts.get('allow', []), 'design.private-header-boundary.allow')
    if not private:
        result.gap('NO_BOUNDARY_DECL', 'declare private header paths in [design."design.private-header-boundary"]')
        return
    if not (targets := target_map(opts)):
        result.gap('TARGET_UNKNOWN', 'declare target membership')
        return
    contract = ctx.config_quote('[design."design.private-header-boundary"]', 'private')
    if not contract:
        result.gap('NO_BOUNDARY_DECL', 'private declaration could not be located in configuration')
        return
    for source, header, n, spelling in include_edges(ctx, result):
        if not matches(header, private) or header in allowed:
            continue
        including, owning = target(source, targets), target(header, targets)
        if including is None or owning is None:
            result.gap('TARGET_UNKNOWN', f'{source} -> {header}: unique source/header targets required')
        elif including != owning:
            result.add(source, n, header, 'target includes a private header of another target',
                       dict(include_directive=dict(path=source, line=n, spelling=spelling), resolved_header=header,
                            including_target=including, boundary_decl=dict(owner=owning, private=private, allow=allowed),
                            exception_match=False), contract=contract, status='violation')


def target_edges(ctx, result):
    graph = ctx.design.get('design.forbidden-target-edge', {}).get('graph', {})
    if not isinstance(graph, dict) or graph.keys() - {'targets', 'forbidden', 'assembly'}:
        raise ValueError('design.forbidden-target-edge.graph expects targets, forbidden and assembly')
    targets = target_map(graph)
    if not targets:
        result.gap('NO_TARGET_GRAPH', 'declare target membership in [design."design.forbidden-target-edge".graph]')
        return
    forbidden = graph.get('forbidden', [])
    if not isinstance(forbidden, list) or any(len(string_list(edge, 'forbidden edge')) != 2 for edge in forbidden):
        raise ValueError('design.forbidden-target-edge.graph.forbidden requires [from, to] pairs')
    assembly = string_list(graph.get('assembly', []), 'design.forbidden-target-edge.graph.assembly')
    contract = ctx.config_quote('[design."design.forbidden-target-edge".graph]', 'forbidden')
    if not forbidden or not contract:
        result.gap('NO_CONTRACT', 'declare forbidden target edges')
        return
    edges = {}
    nodes = sorted(set(targets.values()))
    for source, header, n, spelling in include_edges(ctx, result):
        endpoints = target(source, targets), target(header, targets)
        if None in endpoints:
            result.gap('EDGE_PARTIAL', f'{source} -> {header}: no unique target pair', uncovered=False)
        elif endpoints[0] != endpoints[1]:
            edges.setdefault(endpoints, []).append(dict(file=source, line=n, header=header, spelling=spelling))
    result.gap('EDGE_PARTIAL', 'observed include edges only, not link or cross-TU reference edges', uncovered=False)
    for edge, sites in sorted(edges.items()):
        if list(edge) not in forbidden or edge[0] in assembly:
            continue
        site = sites[0]
        result.add(site['file'], site['line'], ' -> '.join(edge), 'resolved include crosses a forbidden target edge',
                   dict(target_nodes=nodes, target_edges=[list(x) for x in sorted(edges)], forbidden_edges=forbidden,
                        violating_edges=[list(edge)], ref_sites=sites, assembly_exception=False),
                   contract=contract, status='violation', missing=['EDGE_PARTIAL'])


def test_seams(ctx, result):
    opts = ctx.design.get('design.test-seam-in-production', {})
    targets = target_map(opts)
    forbidden = string_list(opts.get('forbidden', []), 'design.test-seam-in-production.forbidden')
    test_targets = string_list(opts.get('test_targets', []), 'design.test-seam-in-production.test_targets')
    lexical = {(f['file'], f['symbol']) for f in ctx.scan.rows if f['rule'] == 'T601'}
    if not targets:
        result.gap('TARGET_UNKNOWN', 'declare target membership in [design."design.test-seam-in-production".targets]')
        return
    if not forbidden:
        for row in ctx.scan.rows:
            if row['rule'] != 'T601':
                continue
            path = row['file']
            owner = target(path, targets)
            if owner and not matches(path, test_targets) and owner not in test_targets:
                result.gap('NO_CONTRACT', 'T601 spelling only; no forbidden declaration patterns', uncovered=False)
                result.add(path, row['line'], row['symbol'], row['message'],
                           dict(symbol=row['symbol'], decl_scope=None, target=owner, production_refs=[],
                                forbidden_contract=None, t601_candidate=True, test_target_match=False),
                           missing=['NO_CONTRACT'])
        if not result.rows:
            result.gap('NO_CONTRACT', 'no forbidden declaration patterns')
        return
    contract = ctx.config_quote('[design."design.test-seam-in-production"]', 'forbidden')
    if not contract:
        result.gap('NO_CONTRACT', 'forbidden declaration could not be located')
        return
    for path, tree in ctx.ast(result, 'VISIBILITY_PARTIAL'):
        owner = target(path, targets)
        if owner in test_targets or matches(path, test_targets):
            continue
        for node in walk(tree):
            name = node.get('detail', '')
            if not function(node) or 'range' not in node or not matches(name, forbidden):
                continue
            if not owner:
                result.gap('TARGET_UNKNOWN', f'{path}: unique target required')
                continue
            # The configured contract defines forbidden spellings in production targets.
            # Do not infer public C++ visibility or outside references from the spelling.
            result.add(path, line(node), name, 'forbidden function declaration in configured production target',
                       dict(symbol=dict(name=name, decl_path=path, line=line(node)), decl_scope='production target',
                            target=owner, production_refs=[], forbidden_contract=contract,
                            t601_candidate=(path, name) in lexical, test_target_match=False),
                       contract=contract, status='violation')


CHECKS = [Check('2.1', 'private-header-boundary', 'contract', private_headers, ('private', 'allow', 'targets'),
                missing_codes=('INCLUDE_UNRESOLVED', 'TARGET_UNKNOWN')),
          Check('2.2', 'forbidden-target-edge', 'contract', target_edges, ('graph',),
                missing_codes=('INCLUDE_UNRESOLVED', 'EDGE_PARTIAL')),
          Check('3.4', 'test-seam-in-production', 'contract', test_seams,
                ('forbidden', 'targets', 'test_targets'), 'T601', missing_codes=('TARGET_UNKNOWN', 'VISIBILITY_PARTIAL'))]
