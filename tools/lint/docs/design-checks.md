# 设计检查使用说明

这份文档说明 `tools/lint/lint.py --design` 的使用契约。设计检查用于把可观察的代码事实整理成可复核的评审线索。它只生成报告，不修改源码，不默认阻断提交，也不接入 hook 或 CI。

## 适用范围

设计检查适合以下评审输入

- 固定提交或干净快照
- 与快照对应的配置文件
- 需要语义检查时，与快照对应的 `compile_commands.json`
- 历史类检查需要的 Git 基准提交
- 项目自己声明的头文件边界、目标关系和迁移契约

工具不会从目录名推断目标边界，也不会把编译数据库当成目标依赖声明。缺少必要输入时，报告会保留未覆盖状态。未覆盖不能解释为没有问题。

当前实现支持 28 个设计检查键。测试样例已经覆盖这些键的正例、反例、合法例外和缺输入路径。真实消费仓的覆盖范围仍取决于实际编译数据库、契约声明和行为证据。

## 快速开始

在工具仓根目录执行普通扫描

```sh
python3 tools/lint/lint.py \
  --root /path/to/source \
  --config /path/to/lint.toml \
  --format json
```

执行设计检查需要显式加入 `--design`

```sh
python3 tools/lint/lint.py \
  --root /path/to/fixed-snapshot \
  --config /path/to/design.toml \
  --design \
  --format json
```

只运行一个检查键

```sh
python3 tools/lint/lint.py \
  --root /path/to/fixed-snapshot \
  --config /path/to/design.toml \
  --design \
  --check design.caller-maintains-owner-state \
  --format json
```

历史检查增加 Git 基准

```sh
python3 tools/lint/lint.py \
  --root /path/to/git-root \
  --config /path/to/design-history.toml \
  --design \
  --baseline HEAD~1 \
  --format json
```

`--check` 可以重复传入。它只缩小报告范围，不会强制启用配置中没有启用的检查。没有传 `--check` 时，报告会列出全部 28 个内置键，未启用的键显示为 `disabled`。

## 配置

完整配置样例在 [config.example.toml](../config.example.toml)。建议复制一份独立审查配置，不要把设计段直接加入旧 hook 使用的自动发现配置。

最小配置可以只启用一个检查

```toml
schema_version = 2

[design]
rules = ["design.caller-maintains-owner-state"]
manual = []
cdb = "build-vscode/compile_commands.json"
```

设计检查的配置结构如下

| 配置 | 用途 |
|---|---|
| `[design].rules` | 自动检查键。结果可以是 `violation`、`candidate`、`not_reported` 或 `uncovered` |
| `[design].manual` | 需要人工判断的检查键。结果使用 `manual_pending` |
| `[design].cdb` | 相对于 `--root` 的编译数据库路径。缺少时，依赖它的检查会报告未覆盖 |
| `[design."design.private-header-boundary"]` | 私有头文件、允许例外和目标归属 |
| `[design."design.forbidden-target-edge".graph]` | 目标归属、禁止边和装配目标 |
| `[design."design.test-seam-in-production"]` | 生产代码中的测试接缝命名契约和目标归属 |
| `[design."design.versioned-entry"]` | 迁移契约文件路径 |

`rules` 和 `manual` 不能重复。`manual` 中只能放人工检查键。未知键、未知配置字段和未登记的缺输入码都会返回工具错误。

### 输入边界

- `--root` 应指向固定的 Git 快照或干净工作树。
- `cdb` 应由同一个快照生成。工具只接受受控的语言版本、宏定义、包含目录和语法选项。
- 工具不会执行编译数据库中的命令，也不会加载项目脚本、编译器插件或驱动查询。
- 历史检查要求 `--root` 是 Git 仓根，并从 Git 对象读取 `baseline..HEAD` 的变化。
- 目标边界和禁止依赖必须写进 `[design]` 配置，不能从路径名称猜测。
- 行为检查可以记录静态事实，但静态事实不能代替取消竞争、重试副作用等运行时回放。

## 28 个检查键

下表中的判定类来自检查契约。`contract` 表示可以根据显式声明判定，`clue` 表示输出可复核线索，`behavior` 表示需要行为证据才能形成更强结论，`manual` 表示工具只整理人工复核材料。

| key | source_ref | 主题 | 判定类 | 主要输入 |
|---|---|---|---|---|
| `design.co-written-fields` | 1.1 | 双写来源 | manual | 构建数据库、写入事实、契约和行为证据 |
| `design.primitive-parameter-pair` | 1.2 | 基础类型携带单位 | behavior | AST 类型事实和行为或契约证据 |
| `design.group-forwarding` | 1.3 | 分层传递相同对象 | manual | 调用链和分层契约 |
| `design.resource-release-paths` | 1.4 | 分散的资源释放出口 | behavior | AST 控制流和所有权事实 |
| `design.cross-object-lock` | 1.5 | 跨对象加锁 | clue | 锁对象和调用位置 |
| `design.callback-multiple-paths` | 1.6 | 取消与完成回调多次触发 | behavior | 回调路径和竞争行为回放 |
| `design.private-header-boundary` | 2.1 | 私有头文件边界 | contract | clangd include 关系和私有头文件声明 |
| `design.forbidden-target-edge` | 2.2 | 下层依赖上层 | contract | include 关系、目标图和禁止边声明 |
| `design.forwarding-layer` | 2.3 | 无收益的转发层 | clue | T401 线索和调用链 |
| `design.cochanged-mapping` | 2.4 | 多模块共同变更 | manual | Git 基准和变更集合 |
| `design.interface-consumers` | 2.5 | 预留扩展点 | manual | 实现关系和扩展契约 |
| `design.boolean-branch-switch` | 3.1 | 用布尔值切换多种行为 | clue | AST 分支事实 |
| `design.state-gated-operation` | 3.2 | 隐藏调用顺序 | clue | AST 阶段和契约 |
| `design.caller-maintains-owner-state` | 3.3 | 调用方维护拥有者状态 | clue | AST 访问序列、调用方和拥有者事实 |
| `design.test-seam-in-production` | 3.4 | 生产代码泄漏测试接缝 | contract | 函数声明、目标归属和命名契约 |
| `design.empty-value-on-failure` | 4.1 | 失败伪装为空结果 | behavior | 失败路径、返回值和契约 |
| `design.logging-only-catch` | 4.2 | 捕获异常后只记录日志 | clue | catch 路径和返回事实 |
| `design.repeated-validation` | 4.3 | 无界重复校验 | manual | 校验路径和信任边界 |
| `design.nested-retry-clue` | 4.4 | 分层重试放大 | behavior | 重试层级、幂等性和行为证据 |
| `design.retired-symbol` | 5.1 | 退役标识符 | contract | Git 基准和 `[[retired]]` 声明 |
| `design.repeated-declaration` | 5.2 | 重复声明相同知识 | clue | Git 变化和重复声明事实 |
| `design.legacy-implementation` | 5.3 | 旧实现仍然存在 | manual | Git 基准、旧实现和 ABI 或动态使用证据 |
| `design.versioned-entry` | 5.4 | 用版本号代替契约 | clue | 标识符事实和迁移契约 |
| `design.identical-branch-tokens` | 6.1 | 两个分支内容相同 | clue | AST 归一化分支 |
| `design.mixed-operation-body` | 6.2 | 长函数承担多种原因 | manual | 函数结构和意图证据 |
| `design.consecutive-forwarders` | 6.3 | 读取路径过度碎片化 | manual | 调用链和跳转事实 |
| `design.comment-restates-code` | 6.4 | 注释复述代码 | clue | 注释和声明文本。当前只判逐字重复 |
| `design.query-shaped-consumption` | 6.5 | 名称隐藏副作用 | behavior | 函数体、调用关系和行为证据 |

`T101`、`T401`、`T501`、`T601` 和 `T202` 的既有词法候选可以被设计检查复用。候选线索不会自动升级为设计缺陷。

### 检查键命名

当前工具有两套并行的键命名约定

- 普通 lint 规则使用规则目录名作为 ID，例如 `T101`、`retired-symbol` 和 `header-implementation`。普通规则的 ID 必须匹配 `[A-Za-z][A-Za-z0-9-]*`，具体协议由 [core/registry.py](../core/registry.py) 校验。
- 设计检查使用 `1.1` 到 `6.5` 的章节项号。数字部分对应设计检查表的类别和条目，作用是稳定引用原始前置表单。它是设计检查的局部键格式，不代表整个 lint 工具的通用标准。

设计检查的 `slug` 已保存语义名称，例如 `3.3` 对应 `caller-maintains-owner-state`。当前配置和报告使用语义键，`source_ref` 保持前置表单、映射和既有审查记录的对应关系。输入配置和 `--check` 仍兼容数字别名。新增的通用 lint 规则应继续使用语义化短横线 ID，避免把检查顺序或文档位置编码进规则名。

设计检查现在使用带命名空间的稳定语义键，例如 `design.caller-maintains-owner-state`，并把 `3.3` 保留为 `source_ref` 和兼容别名。JSON 的 `checks[]`、`findings[]`、`coverage.missing_inputs[]` 和 `counts.by_key` 使用 canonical key，检查摘要和 finding 同时提供 `source_ref`。

## 报告状态

设计模式的 JSON 报告使用 `schema_version = 2`，包含 `checks`、`findings`、`coverage` 和 `counts`。版本 2 将语义 `key` 与表单 `source_ref` 分开。常用状态如下

| 状态 | 含义 |
|---|---|
| `violation` | 违反了配置中明确声明的机器可判约束 |
| `candidate` | 找到需要人工复核的事实线索 |
| `not_reported` | 在当前可观察范围内没有找到该检查支持的形状 |
| `manual_pending` | 已整理人工复核材料，工具没有替人作结论 |
| `uncovered` | 缺少输入、解析不完整或事实范围不足 |
| `disabled` | 没有在当前运行中启用 |

`not_reported` 只表示当前检查支持的形状没有命中。它不表示全仓没有问题。`uncovered`、`manual_pending` 和 `disabled` 都不能作为干净结论。

### 覆盖字段

`coverage` 中的字段用于判断报告是否可以被复核

- `complete` 表示当前报告没有未覆盖、人工待查、停用键、缺输入或解析不完整。
- `files_scanned` 表示读取到的源码文件数量。
- `tus` 表示实际成功解析的编译单元。
- `index` 当前为 `none` 时，不证明跨编译单元语义。
- `partial` 表示读取或解析不完整的路径。
- `missing_inputs` 记录检查键、缺输入码和原因。
- `manual_pending` 记录仍需人工判断的键。
- `disabled` 记录未启用的键。

`findings` 中的 `file` 路径相对 `--root`，`line` 从 1 开始。`facts` 保留检查所观察到的原始事实。`contract_ref` 在检查依赖显式契约时保存配置或源码引用。`fingerprint` 不包含行号、消息或时间，因此移动代码行不会单独改变同一事实的指纹。

## 退出码

- `0` 表示报告生成成功，且当前运行没有 `uncovered` 检查。
- `2` 表示输入、配置、解析或覆盖错误。设计报告仍可能随标准输出生成。
- 普通全量扫描的既有退出码保持不变。

候选和违规本身不会让设计模式返回 1。设计检查当前只报告，不作为提交阻断门禁。

## 3.3 的五态回放

`3.3` 用于观察调用方是否替拥有者维护内部状态。建议至少保留以下五组输入

1. 坏例。调用方直接索引、推进游标或按底层存储顺序删除。
2. 假修。字段改为私有并增加 getter，调用方仍执行相同的索引和顺序操作。
3. 真修。由拥有者提供 `push`、`pop` 或等价操作，调用方只请求结果。
4. 合法用法。调用方读取普通结果，不负责维护内部状态。
5. 缺输入。没有编译数据库、调用者未解析或拥有者无法解析。

假修仍应保留相同的候选线索。真修和合法只读用法应在确实成功扫描到输入后不报同一个根因。缺少索引时应得到 `uncovered/NO_INDEX`，不能得到零命中。

## 新增设计检查

设计检查代码属于受信任的本地工具代码。消费仓配置不能指定任意 Python 文件路径。

在工具副本的 `tools/lint/rules/_design/` 中新增一个模块，并导出 `CHECKS`

```python
from design import Check


def check(ctx, result):
    for path, text in ctx.sources.items():
        for line_number, line in enumerate(text.splitlines(), 1):
            if line.rstrip().endswith("DESIGN-REVIEW"):
                result.add(
                    path,
                    line_number,
                    "DESIGN-REVIEW",
                    "explicit text marker",
                    {"marker": "DESIGN-REVIEW"},
                )


CHECKS = [Check("example-marker", "explicit-review-marker", "clue", check)]
```

新增检查需要同时完成以下事项

- 在 `CHECKS` 注册唯一键和判定类。
- 在配置示例中说明所需输入。
- 为每个特殊缺输入码登记 `missing_codes`。
- 用正例、反例、合法例外和缺输入样例验证输出。
- 明确哪些事实是自动判定，哪些事实只能交给人工或行为测试。
- 把检查键加入独立配置后再运行，不默认开启旧 hook。

`result.gap()` 或 `result.add(..., missing=...)` 使用未登记的特殊码会返回工具错误。共用的 `NO_AST`、`NO_INDEX`、`NO_BUILD_DB`、`NO_TARGET_GRAPH`、`NO_BOUNDARY_DECL`、`NO_CONTRACT`、`NO_BASELINE`、`NO_HISTORY` 和 `NO_BEHAVIOR_HARNESS` 不需要在每个检查中重复登记。

当前的运行时注册已经按检查模块自动发现。每个模块导出一个 `CHECKS` 列表，列表中的 `Check` 保存稳定键、判定类、处理函数、配置字段和缺输入码。新增检查的运行时接入只需要增加一个设计规则模块并在其中注册 `Check`，不需要修改统一入口或调度器。映射、测试样例和使用说明仍需同步维护，它们分别承担来源契约、独立预期和使用者文档的职责。

这套结构保留了模块边界，也让注册表可以在启动时检查重复键、未知缺输入码和无效配置。后续如果检查数量继续增长，可以把 `Check` 元数据抽成一个稳定目录，生成检查清单和配置提示；这属于收敛重复登记的演进，不改变检查函数只消费输入事实的方向。

## 跨仓与语言适配

`--root`、`--config`、路径排除、目标声明、Git 历史输入和报告格式已经提供仓库适配接缝。当前已验证的是 `bbtools-infra` 的 C++ 单编译单元，不能据此宣称任意仓库或任意语言均已支持。

语言适配应沿事实来源与规则判定分层推进

1. 规则只消费统一的事实对象，例如声明、调用、访问、include 边、控制流、历史变化和覆盖状态。
2. 语言后端负责从本语言的词法工具、AST、语言服务器索引或构建数据库提取这些事实。
3. 历史检查、报告状态、缺输入码、指纹和 CLI 配置保持语言无关。
4. 后端无法提供某项事实时，规则返回明确的 `uncovered` 或 `manual_pending`，并带原因码。

现有 `core/cpp.py` 和 `core/design_ast.py` 属于 C++ 后端。clangd、`compile_commands.json`、C++ include 语义和当前词法模型都应留在后端适配层。Rust、Python 或其他语言接入时，各自提供事实后端，不把语言判断塞进统一调度器。

第一阶段只需要稳定这条内部接缝，不需要先建设通用插件市场或完整跨语言规则平台。等第二种语言有真实检查需求时，再为后端定义接口、能力声明和对应 fixture。没有后端能力的检查应保持可见的未覆盖状态，不能用零命中代替兼容。

## 当前未闭合边界

当前工作树的工具和样例已经可运行，但以下事项仍没有作为整期交付完成

- `5.2` 的事实输出缺少映射要求的 `independent_reason`，对应测试也还没有断言该字段。
- 映射声明的 9 个细粒度降级码尚未全部实现。包括 `BRANCH_UNRESOLVED`、`STATE_UNOBSERVABLE`、`ACCESSOR_OPAQUE`、`ERROR_PATH_UNKNOWN`、`TYPE_GUARANTEE_UNKNOWN`、`SPELLING_UNRESOLVED`、`GENERATED_UNKNOWN`、`REFS_PARTIAL` 和 `EFFECT_UNOBSERVABLE`。
- 固定消费仓的实跑只覆盖一个编译单元。多编译单元索引、行为回放、目标边界声明和迁移契约缺失时，报告会保留 `uncovered` 或 `manual_pending`。
- 设计检查结果是本地评审材料，不是 CI 结果，也不是提交或合并门禁通过。

## 验证

修改设计检查实现后执行

```sh
python3 -m unittest discover -s tools/lint/tests -v
timeout 240 python3 -m unittest discover -s tools/git-hooks/tests -v
git diff --check
```

修改设计检查测试时，先运行对应的 `test_design_*.py`，再运行完整 lint 测试。测试使用临时目录和本地 Git 对象，不写消费仓远端。完成真实仓回放时，记录固定提交、配置指纹、编译数据库指纹、输出指纹和未覆盖原因。
