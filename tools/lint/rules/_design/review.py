"""Review-only checks that reuse the pinned lizard measurement: cross-file similar
function bodies and complexity deltas against a Git baseline. Both are clues with
explicit coverage, never violations."""
from collections import Counter
from difflib import SequenceMatcher

from design import Check
from design_measure import (BACKEND_VERSION, BackendMissing, backend_context,
                            load_complexity, measure_file)

# Raw-token count below which a body is plumbing boilerplate (getters, one-line
# forwarders, trivial constructors, small test fixtures): excluded from both exact and
# near matching. Calibrated on the bbtools-coroutine corpus: accepted long copies sit at
# 99-122 tokens, while operator/getter/fixture boilerplate stays below 60.
MIN_BODY_TOKENS = 16
MIN_EXACT_TOKENS = 80
MIN_NEAR_TOKENS = 80
# Near-copies must also carry enough substance per line count, not just long signatures.
MIN_NEAR_NLOC = 8
# A long near-copy shares most of its token multiset and most of its ordered tokens.
# Below these bars the pair is a different function, not a near-copy.
NEAR_JACCARD = 0.75
NEAR_RATIO = 0.85
# At most this many differing raw tokens (both sides combined) still count as a
# near-copy; beyond it the pair is independent implementation, not a copied body.
MAX_DIFFERENT_TOKENS = 12
# One function may be part of several genuinely different copied families, but a dense
# boilerplate cluster is noise. Cap pair emission per function instead of flooding.
MAX_PAIRS_PER_FUNCTION = 4


def measure_all(ctx, result, lizard_path=None):
    """Measure every scanned source once; return {path: functions} or report the gap."""
    if lizard_path is None:
        lizard_path = ctx.design.get('design.similar-functions', {}).get('lizard_path') or \
            ctx.design.get('design.complexity-delta', {}).get('lizard_path')
    try:
        with backend_context(lizard_path) as lizard:
            measured, partial = {}, []
            for path in sorted(ctx.sources):
                functions, error = measure_file(lizard, path, ctx.sources[path])
                if error:
                    partial.append(f'{path}: {error}')
                elif functions:
                    measured[path] = functions
    except BackendMissing as error:
        result.gap('NO_MEASUREMENT_BACKEND', str(error))
        return None
    if partial:
        result.gap('MEASURE_PARTIAL', '; '.join(sorted(partial)), uncovered=False)
    return measured


def ranges_overlap(a, b):
    return a['start_line'] <= b['end_line'] and b['start_line'] <= a['end_line']


def diff_tokens(left, right):
    """Differing raw tokens in order, left side against right side; operators,
    constants and call names survive. left_only means present only in the left body."""
    matcher = SequenceMatcher(None, left, right, autojunk=False)
    removed, added = [], []
    for tag, a1, a2, b1, b2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        removed.extend(left[a1:a2])
        added.extend(right[b1:b2])
    return removed, added


def jaccard(left, right):
    intersection = sum((Counter(left) & Counter(right)).values())
    union = len(left) + len(right) - intersection
    return intersection / union if union else 0.0


def similar_functions(ctx, result):
    lizard_path = ctx.design.get('design.similar-functions', {}).get('lizard_path')
    measured = measure_all(ctx, result, lizard_path)
    if measured is None:
        return
    units = []
    for path, functions in measured.items():
        for fn in functions:
            if not fn['window_ambiguous'] and len(fn['tokens']) >= MIN_BODY_TOKENS:
                units.append(dict(path=path, **fn))
    units.sort(key=lambda u: (u['path'], u['start_line'], u['end_line'], u['long_name']))

    pairs = []
    exact_keys = set()
    by_digest = {}
    for unit in units:
        if len(unit['tokens']) >= MIN_EXACT_TOKENS and unit['metrics']['nloc'] >= MIN_NEAR_NLOC:
            by_digest.setdefault(tuple(unit['tokens']), []).append(unit)
    for group in sorted(by_digest.values(), key=lambda g: (g[0]['path'], g[0]['start_line'])):
        if len(group) < 2:
            continue
        first, *rest = group
        for other in rest:
            if first['path'] == other['path'] and ranges_overlap(first, other):
                continue  # a nested lambda is a window of its enclosing body, not a copy
            exact_keys.add((id(first), id(other)))
            pairs.append((first, other, [], []))

    # Prescreen by token multiset before paying for the ordered comparison.
    for index, left in enumerate(units):
        if len(left['tokens']) < MIN_NEAR_TOKENS or left['metrics']['nloc'] < MIN_NEAR_NLOC:
            continue
        for right in units[index + 1:]:
            if len(right['tokens']) < MIN_NEAR_TOKENS or right['metrics']['nloc'] < MIN_NEAR_NLOC:
                continue
            if (id(left), id(right)) in exact_keys:
                continue
            if left['path'] == right['path'] and ranges_overlap(left, right):
                continue
            shortest, longest = sorted((len(left['tokens']), len(right['tokens'])))
            if shortest / longest < NEAR_JACCARD:
                continue
            if jaccard(left['tokens'], right['tokens']) < NEAR_JACCARD:
                continue
            shorter, longer = (left, right) if len(left['tokens']) <= len(right['tokens']) else (right, left)
            ratio = SequenceMatcher(None, shorter['tokens'], longer['tokens'], autojunk=False).ratio()
            if ratio < NEAR_RATIO:
                continue
            # Difference labels belong to the pair sides, not to whichever side is
            # shorter: left_only is what only the left body carries.
            removed, added = diff_tokens(left['tokens'], right['tokens'])
            if len(removed) + len(added) > MAX_DIFFERENT_TOKENS:
                continue
            pairs.append((left, right, removed, added))

    # A function involved in too many pairs belongs to a boilerplate family, not a copy
    # worth review; emit at most the first pairs per function, deterministically.
    ordered = sorted(pairs, key=lambda p: (p[0]['path'], p[0]['start_line'],
                                           p[1]['path'], p[1]['start_line']))
    fan = Counter()
    capped = []
    for pair in ordered:
        left, right = pair[0], pair[1]
        if fan[(left['path'], left['start_line'])] >= MAX_PAIRS_PER_FUNCTION \
                or fan[(right['path'], right['start_line'])] >= MAX_PAIRS_PER_FUNCTION:
            continue
        fan[(left['path'], left['start_line'])] += 1
        fan[(right['path'], right['start_line'])] += 1
        capped.append(pair)

    for left, right, removed, added in capped:
        identical = not removed and not added
        result.add(
            left['path'], left['start_line'], left['long_name'],
            'identical function body occurs in another location' if identical
            else 'long function body differs from another location only in a few tokens',
            dict(match='identical' if identical else 'near',
                 left=dict(path=left['path'], line=left['start_line'], end_line=left['end_line'],
                           function=left['long_name']),
                 right=dict(path=right['path'], line=right['start_line'], end_line=right['end_line'],
                            function=right['long_name']),
                 token_counts=[len(left['tokens']), len(right['tokens'])],
                 differences=dict(left_only=removed, right_only=added),
                 difference_count=len(removed) + len(added),
                 shared_evidence='raw lizard tokens; operators, constants and call names kept verbatim'))


def complexity_findings(ctx, result):
    try:
        with load_complexity(ctx.design.get('design.complexity-delta', {}).get('lizard_path') or
                             ctx.design.get('design.similar-functions', {}).get('lizard_path')) as loaded:
            return _complexity_findings(ctx, result, *loaded)
    except BackendMissing as error:
        result.gap('NO_MEASUREMENT_BACKEND', str(error))
        return


def _complexity_findings(ctx, result, common, structural, backend):
    """Reuse tools/complexity: same measurement, same baseline comparison, same CCN policy."""
    lizard_path = ctx.design.get('design.complexity-delta', {}).get('lizard_path') or \
        ctx.design.get('design.similar-functions', {}).get('lizard_path')
    options = ctx.design.get('design.complexity-delta', {})
    config_file = options.get('config_file')
    path = None
    if config_file is not None:
        if not isinstance(config_file, str) or not config_file.strip():
            raise ValueError('design.complexity-delta.config_file requires a path')
        candidate = (ctx.root / config_file).resolve()
        if not candidate.is_file() or not candidate.is_relative_to(ctx.root):
            result.gap('NO_CONTRACT', 'design.complexity-delta.config_file must exist inside --root')
            return
        path = str(candidate)
    try:
        config = common.config_load(path)
    except (ValueError, OSError) as error:
        raise ValueError(f'design.complexity-delta config: {error}') from error

    measured = measure_all(ctx, result, lizard_path)
    if measured is None:
        return
    observations = []
    for path, functions in measured.items():
        if not structural.selected(path, config['scope']):
            continue  # the reused measurement policy decides which sources carry metrics
        counts = Counter(fn['long_name'] for fn in functions)
        for fn in functions:
            ambiguous = counts[fn['long_name']] > 1
            digest = common.digest(fn['tokens'])
            # Mirror structural.scan: same-named functions are keyed by body digest,
            # and identical ambiguous bodies cannot be paired safely at all.
            if ambiguous and sum(other['long_name'] == fn['long_name']
                                 and common.digest(other['tokens']) == digest for other in functions) > 1:
                result.gap('MEASURE_PARTIAL', f'{path}: identical ambiguous functions cannot be paired safely',
                           uncovered=False)
                continue
            unit = fn['long_name'] + (' [body:' + digest[:16] + ']' if ambiguous else '')
            observations.append(dict(path=path, unit=unit, line=fn['start_line'],
                                     identity='content_disambiguated' if ambiguous else 'symbol',
                                     end_line=fn['end_line'],
                                     metrics=fn['metrics'], code_digest=digest))
    # The report mirrors structural.scan's shape so the tools/complexity diff logic is
    # reused verbatim; the scope here is the lint scan universe, not complexity globs.
    report = {'schema_version': 1, 'kind': 'structural', 'revision': 'working-tree',
              'evaluator': {'backend': 'lizard', 'version': '1.25.0',
                            'metrics': list(common.METRICS), 'policy_version': '0.1.0'},
              'scope': {'include': ['**'], 'exclude': []}, 'observations': observations,
              'coverage': {'files_total': len(ctx.sources), 'files_scanned': len(measured), 'skipped': []}}

    old = None
    if ctx.baseline:
        try:
            commit = structural.resolve_base(ctx.root, ctx.baseline, 'merge-base')
        except (ValueError, OSError) as error:
            result.gap('NO_BASELINE', str(error))
            return
        try:
            scanned = structural.scan(ctx.root, config, commit,
                                      backend=backend, backend_version=BACKEND_VERSION)
        except (ValueError, OSError) as error:
            result.gap('NO_BASELINE', f'baseline scan failed: {error}')
            return
        if scanned['coverage']['skipped']:
            detail = '; '.join(f"{row['path']}: {row['reason']}" for row in scanned['coverage']['skipped'][:5])
            result.gap('NO_BASELINE', f'baseline scan incomplete: {detail}')
            return
        # Compare on the same universe and evaluator: keep only baseline rows whose path
        # the lint scan actually covers, then align evaluator/scope so compare() treats
        # the two measurements as the same instrument.
        old = dict(scanned,
                   observations=list(scanned['observations']),
                   evaluator=dict(report['evaluator']), scope=dict(report['scope']))

    findings = structural.compare(report, old, config)
    rows = [f for f in findings if f['status'] in ('new', 'worsened', 'inventory')]
    for finding in sorted(rows, key=lambda f: (f['path'], f['line'], f['unit'])):
        metric = finding['rule'].removeprefix('structural.')
        state = 'inventory' if finding['status'] == 'inventory' else finding['status']
        result.add(
            finding['path'], finding['line'], finding['unit'],
            f"{metric} {finding['after']} exceeds threshold {finding['threshold']} ({state})",
            dict(metric=metric, unit=finding['unit'],
                 before=finding['before'], after=finding['after'], threshold=finding['threshold'],
                 comparison=finding['status'], baseline=ctx.baseline,
                 measurement=dict(backend='lizard', version='1.25.0')))
    if not rows and old is None:
        result.reason = 'no function exceeds its complexity threshold in measured files'


CHECKS = [
    Check('R1', 'similar-functions', 'clue', similar_functions, ('lizard_path',),
          missing_codes=('NO_MEASUREMENT_BACKEND', 'MEASURE_PARTIAL')),
    Check('R2', 'complexity-delta', 'clue', complexity_findings, ('lizard_path', 'config_file'),
          missing_codes=('NO_MEASUREMENT_BACKEND', 'MEASURE_PARTIAL')),
]
