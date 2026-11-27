"""Human-readable design findings. Locations and evidence come from the check, not a second parse."""
from collections import Counter
from functools import lru_cache


LABELS = {'candidate': '候选', 'manual_pending': '人工复核', 'violation': '违反契约'}
HISTORY_CHECKS = {'2.4', '5.1', '5.2', '5.3'}


def one_line(value):
    # A source line, symbol or path cannot inject terminal controls or another header.
    return ''.join(c if c.isprintable() else ascii(c)[1:-1] for c in str(value))


def explain(row):
    """Return the observed reason and related lines in the same source file."""
    facts, ref, line = row['facts'], row['source_ref'], row['line']
    if ref == '1.2':
        params = facts['params']
        pairs = [f"{params[a]['name'] or '#' + str(a + 1)} / {params[b]['name'] or '#' + str(b + 1)}（{params[a]['type']}）"
                 for a, b in facts['same_type_adjacent_pairs']]
        return '相邻参数类型相同：' + '；'.join(pairs) + '。核对调用处能否传反；不表示已经传错。', []
    if ref == '6.4':
        reason = ('注释正文只重复符号名。' if facts['restates_name'] else
                  '注释是简短标签。工具不能判断它是否只是名称的翻译；请对照声明。')
        return reason, []
    if ref == '3.1':
        branches = facts['controlled_branches']
        return '布尔参数参与分支判断：' + branches[0]['condition'] + '。核对它是否切换了两种行为。', [b['line'] for b in branches]
    if ref == '6.2':
        calls = {}
        for site in facts['responsibility_candidates']:
            calls.setdefault(site['callee'], site['line'])
        return '该函数分别调用 ' + '、'.join(calls) + '。核对是否为不同职责，还是同一件事的步骤。', list(calls.values())
    if ref == '1.5':
        access = facts['external_access'][0]
        lock = facts['lock_decl']
        return f"{access['enclosing']} 直接使用 {lock['owner']} 的锁 {row['symbol']}。核对这是否是约定的加锁协议。", [lock['line']]
    if ref == '3.3':
        seq = facts['access_sequence']
        fn = next(s['function'] for s in seq if s['line'] == line)
        ops = [s for s in seq if s['function'] == fn]
        return f"{fn} 对 {row['symbol']} 执行 " + ' → '.join(s['op'] for s in ops) + '。核对读写责任是否应在调用方。', [s['line'] for s in ops]
    if ref == '1.1':
        writers = facts['writers']
        fn = next(s['enclosing'] for s in writers if s['line'] == line)
        return f"同一函数写入同一对象的多个字段，命中行位于 {fn}。核对是否在维护同一份状态。", [s['line'] for s in writers if s['enclosing'] == fn]
    if ref == '2.3':
        delegates = [f"{s['delegate_location']['path']}:{s['delegate_location']['line']}"
                     for s in facts['chain'] if s.get('delegate_location')]
        callers = [f"{s['path']}:{s['line']} ({s['caller']})" for s in facts.get('callers', [])]
        detail = '委托目标：' + '、'.join(delegates or ['未定位'])
        if callers:
            detail += '；实际调用方：' + '、'.join(callers)
        return '多个静态方法只转发一次调用。' + detail + '。核对该层是否承载调用契约。', [s['line'] for s in facts['chain']]
    if ref == 'R1':
        left, right = facts['left'], facts['right']
        differences = facts['differences']
        return (f"{left['path']}:{left['line']} {left['function']} ↔ "
                f"{right['path']}:{right['line']} {right['function']}；"
                f"差异 left_only={differences['left_only']}，right_only={differences['right_only']}。"), \
            [left['line']]
    if ref == 'R2':
        return (f"{facts['metric']}：before={facts['before']}，after={facts['after']}，"
                f"threshold={facts['threshold']}，比较={facts['comparison']}。"), []
    return row['message'], []


def print_frame(lines, primary, related):
    if not 1 <= primary <= len(lines):
        print('    源码片段不可用；请核对报告对应的快照。')
        return
    marks = list(dict.fromkeys(n for n in [primary, *related] if 1 <= n <= len(lines)))
    # Show two additional evidence sites at most; keep repeated calls from flooding the listing.
    shown = marks[:3]
    visible = sorted({i for n in shown for i in range(max(1, n - 1), min(len(lines), n + (3 if n == primary else 1)) + 1)})
    width = len(str(visible[-1]))
    previous = None
    for i in visible:
        if previous is not None and i != previous + 1:
            print('  …')
        marker = '>' if i == primary else '+' if i in shown else ' '
        print(f'{marker} {i:{width}} | {one_line(lines[i - 1].expandtabs(4))}')
        previous = i
    if len(marks) > len(shown):
        print('    其他证据行：' + ', '.join(map(str, marks[len(shown):])))


def print_diagnostics(report, ctx):
    @lru_cache(maxsize=8)
    def lines_for(path, history):
        text = ctx.history.text(path) if history else ctx.sources.get(path, '')
        return text.split('\n') if text else []

    rows, coverage = report['findings'], report['coverage']
    counts = Counter(r['status'] for r in rows)
    print(f"设计检查：{coverage['files_scanned']} 个源码文件，{len(coverage['tus'])} 个已解析编译单元；{len(rows)} 条诊断"
          f"（候选 {counts['candidate']}，人工复核 {counts['manual_pending']}，违反契约 {counts['violation']}）。")
    print('> 命中行；+ 关联证据行。标记不表示要删除或修改该行。')
    for row in rows:
        reason, related = explain(row)
        print(f"\n{one_line(row['file'])}:{row['line']}: {LABELS.get(row['status'], row['status'])} [{one_line(row['key'])}] {one_line(row['symbol'])}")
        print('  ' + one_line(reason))
        print_frame(lines_for(row['file'], row['source_ref'] in HISTORY_CHECKS), row['line'], related)
        if row['missing']:
            print('  证据限制：' + ', '.join(map(one_line, row['missing'])))

    print('\n覆盖：' + ('完整' if coverage['complete'] else '不完整（零命中不代表没有问题）'))
    for check in report['checks']:
        if check['status'] == 'uncovered':
            print(f"  未覆盖完整 [{one_line(check['key'])}] {one_line(check['reason'] or '')}")
    if coverage['disabled']:
        print('  未启用：' + ', '.join(map(one_line, coverage['disabled'])))
    if not coverage['complete']:
        print('  逐项缺口与原始证据：用 --format json 查看 coverage 和 findings[].facts。')
