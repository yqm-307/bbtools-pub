"""Simplified Chinese presentation for design reports; evidence and machine IDs stay verbatim."""

# Index by rule, not English prose: two checks can observe the same facts but ask different questions.
MESSAGES = {
    'co-written-fields': '同一个函数会修改 {symbol} 上的多个字段。核对这些字段是否分别记录了同一个状态。',
    'primitive-parameter-pair': '{symbol} 有相邻参数使用同一种基本类型。核对调用时是否容易把顺序或单位弄反。',
    'group-forwarding': '从 {symbol} 开始，多个函数逐层传递同一类型的参数，并做相同检查。核对这些层各自承担什么职责。',
    'resource-release-paths': '{symbol} 有一条返回路径，在返回前没找到配套的释放操作。核对资源是否已移交，或会在离开作用域时释放。',
    'cross-object-lock': '有代码直接获取 {facts[lock_decl][owner]} 的成员锁 {symbol}。核对这些调用方是否应该持有这把锁。',
    'callback-multiple-paths': '取消和正常完成两条路径都会调用回调 {symbol}。核对两条路径交错时是否只通知一次。',
    'private-header-boundary': '目标 {facts[including_target]} 引用了 {facts[boundary_decl][owner]} 的私有头文件 {symbol}，不在允许例外内。',
    'forbidden-target-edge': '头文件引用产生了配置禁止的依赖方向：{symbol}。',
    'forwarding-layer': '{symbol} 的多个静态方法都只转调一次。核对这一层是否提供了调用方需要的约定。',
    'cochanged-mapping': '同一次变更在多个文件里新增了相同的映射：{symbol}。核对以后改这条映射是否必须同步改多处。',
    'interface-consumers': '找到了抽象接口 {symbol} 的实现。请核对哪些调用方需要这个接口；仅有实现不能说明接口多余。',
    'boolean-branch-switch': '{symbol} 用布尔参数选择执行分支。核对调用方能否看懂传入真或假分别会做什么。',
    'state-gated-operation': '{symbol} 在状态不满足时跳过操作，却返回了普通结果值。核对调用方能否分辨操作没有执行。',
    'caller-maintains-owner-state': '调用方既查询又修改容器 {symbol}。核对该由谁负责元素的顺序或移除时机。涉及：{callers}。',
    'test-seam-in-production': '生产目标 {facts[target]} 中出现了疑似测试专用的名字 {symbol}。未配置禁用规则，请人工核对。',
    'empty-value-on-failure': '{symbol} 在打开文件失败时返回空值。核对调用方能否区分“打开失败”和“内容为空”。',
    'logging-only-catch': '{symbol} 捕获异常后只记日志，随后走向与正常路径相同的返回值。核对调用方如何得知失败。',
    'repeated-validation': '从 {symbol} 开始，多层函数对传入的数据做相同检查。核对中间是否跨越信任边界，再判断校验是否重复。',
    'nested-retry-clue': '{symbol} 在循环中调用了一个注明会自行重试的函数。核对内外两层重试叠加后最多会执行多少次。',
    'retired-symbol': '本次新增的源码行使用了已登记退役的标识符 {symbol}。',
    'repeated-declaration': '不同文件新增了相同的声明：{symbol}。核对它们是否代表同一条约定。',
    'legacy-implementation': '在 Git 跟踪的其他 C++ 代码位置没找到对 {symbol} 的引用。删除前还需核对仓外调用和动态加载。',
    'versioned-entry': '带版本的入口名 {symbol} 和旧名称同时出现。核对谁仍使用旧入口，以及何时可以移除它。',
    'identical-branch-tokens': '{symbol} 的两个分支包含相同的代码标记。核对条件本身是否有副作用，再判断能否合并。',
    'mixed-operation-body': '{symbol} 声明了局部变量，并调用了不同的函数。这本身不是缺陷；请判断这些操作是否服务于同一个目的。',
    'consecutive-forwarders': '从 {symbol} 开始，本编译单元内有连续几层函数各自只转调一次。核对每层是否有独立职责。',
    'comment-restates-code': '核对 {symbol} 旁的短注释是否只重复了名字。若说明了特殊值、范围、顺序、所有权或寿命，应保留。',
    'query-shaped-consumption': '{symbol} 的名字像是只读查询，但函数体里有移除容器元素的操作。核对调用方是否预期数据会被消耗。',
}

def finding_message(row):
    slug = row['key'].removeprefix('design.')
    if slug == 'caller-maintains-owner-state':
        return MESSAGES[slug].format(**row, callers='、'.join(row['facts']['caller_functions']))
    if slug == 'test-seam-in-production' and row['status'] == 'violation':
        return '生产目标 {facts[target]} 声明了配置明确禁止的函数 {symbol}。'.format_map(row)
    template = MESSAGES.get(slug)
    # Trusted extension rules without a translation retain their own message verbatim.
    return template.format_map(row) if template else row['message']
