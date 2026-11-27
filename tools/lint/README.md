# 可组合 lint

规则独立于 Git 阶段；同一 C++ 检查用于全量存量清单和 hook 改动文件。Python 3.11+ 标准库，无安装依赖，不联网、不改源码、不调用模型、不自动启用 hook 或接入 CI。告警是人工复核候选，不是缺陷判决。

## 快速接入

**先跑只读扫描，不改配置或 hook。** 已固定 `bbtools-pub` submodule 的仓库，在消费仓根目录运行：

```sh
python3 -B third-party/bbtools-pub/tools/lint/lint.py --root .
```

其他 C/C++ 项目也可以用独立检出的 pub，把脚本路径换成该检出中的 `tools/lint/lint.py`；仅扫描时，目标无需是 Git 仓库。建议固定到 pub `main` 已合入的版本。`--root` 可以改成实际的手写源码目录，避免首次把第三方代码、构建输出也扫进去；报告和排除路径都相对于该目录。没有找到 `.config/lint.toml` 且未传 `--config` 时使用默认扫描规则；旧 `.config/bbt-git-hooks.toml` 不会被这条命令自动读取。默认扫描不需要 clang-format。

**先固定扫描范围和规则，再决定是否设为门禁。** 新仓可先在 `.config/lint.toml` 写 `schema_version = 2` 和一个 `[scan]` 的 `rules` 列表。已有 schema 1 hook 的仓库可以保持原样试扫；要接入新规则，再把现有配置迁到 schema 2，显式保留实际启用的阶段、规则顺序与排除项。不要同时保留两个配置文件，也不要整份照搬 [bbtools 配置示例](config.example.toml)：退役符号、排除路径和审查规则是采用方的策略。如何接到本地 Git，见 [Git hooks](../git-hooks/README.md#本地启用)。

**接入 CI 时先决定要检查什么。** 消费仓可在 checkout 到固定的 pub 版本后运行同一全量命令。退出 `0` 仍可能有告警，退出 `2` 表示扫描未完整完成；只接命令退出码不会把告警变成阻断。先在代表性目录确认覆盖情况，再决定哪些规则要进必过检查。仓库可复用不等于语言通用：目前全量源码扫描面向 C/C++，`coroutine-sugar` 等家族规则按需显式启用。

## 入口与布局

```sh
python3 tools/lint/lint.py --root /path/to/source --config tools/lint/config.example.toml
python3 tools/lint/lint.py --root /path/to/source --config tools/lint/config.example.toml --format json
```

```text
lint/
├── lint.py                 全量扫描入口
├── config.example.toml     消费仓配置示例
├── core/
│   ├── configuration.py    配置校验与规则参数
│   ├── registry.py         按目录发现规则、加载 meta 与检查
│   ├── cpp.py              C++ 词法模型、直接成员与作用域线索
│   ├── scanner.py          唯一的注释词法扫描与形态检查实现
│   ├── scan.py             共用扫描、抑制、覆盖诊断与报告
│   ├── hook.py             index/推送对象到源文件检查的适配
│   └── layout.py           Git tree 的顶层目录与 gitlink 模式
└── rules/
    ├── _template/          新 C++ 规则模板
    └── <id>/               meta.toml + main.py（可含规则私有辅助脚本）
```

Git 入口保留在 `tools/git-hooks/hooks/`；阶段目录只保留入口，规则全部放在本目录。Git 范围、ticket 与历史配置名在 Git 适配层处理，C++ 核心不内置仓名、协议名或项目排除项。`format` 在 commit/push 共用一份实现。

全量模式读取工作区 `.h/.hh/.hpp/.hxx/.c/.cc/.cpp/.cxx`，不跟随源码软链接。文本 stdout 为 `file:line rule warn message`，stderr 为覆盖摘要；JSON 包含有效配置、逐项命中、按规则计数、排除文件、抑制数量及解析不完整文件。路径相对 `--root`；计数是诊断条目数，不是缺陷数。

退出码：全量 **0** 表示未检测到扫描覆盖错误，即使有告警也不返回 1；**2** 表示输入/配置错误、无源码或解析不完整，不是通过。hook **0** 表示没有阻断项（可以有 WARN/NOTE），**1** 表示存在 fatal/error 级违规，**2** 表示工具/配置/解析错误；错误不能用 warn 降级。hook 按配置顺序执行：fatal 级违规首错即停，error 级违规记为未通过、继续执行其余规则、结尾统一报告并退出 1；warn 打印逐条诊断并放行，notice 只打印一行简注并放行，两者都不能称为 PASS。

hook 违规级别（`[rules.<id>].level`，默认 `fatal`）：

| level | 违规时行为 | 用途 |
|---|---|---|
| `fatal` | 首错即停，退出 1 | 必须立即处理的确定性检查（格式、密钥等） |
| `error` | 记为未通过，继续跑完其余规则，结尾统一报告，退出 1 | 阻断提交但希望一次看全所有违规 |
| `warn` | 逐条打印诊断，放行 | 人工复核候选 |
| `notice` | 一行简注（规则名与条数），放行 | 低优先候选，只提示存在感 |

工具/配置/解析错误始终是退出码 2，不属于任何 level、不能降级。schema 1 的旧配置没有 level 概念，行为等同全部 fatal（与原 block 一致）；唯一的例外是 header-implementation，它在两种 schema 下都被固定为 warn/notice。

hook 的 C++ 候选规则扫描本次改动文件的完整内容：commit 使用 index 冻结 tree，push 使用实际推送对象和旧远端/新分支边界；不读未暂存源码，不扫描无改动文件。头实现配对也基于同一 Git tree。既有 `comment-form` 仍只检查与新增/修改行相交的注释，`secrets` 仍只查新增行，`template-layout` 仍只查新增路径，其他既有检查的范围不变。

## 设计检查（显式启用，只报告）

从 [config.example.toml](config.example.toml) 复制注释中的 `[design]` 段到独立审查配置，填写项目自己的头边界、目标、禁边及迁移契约。要共用 `[scope]`、`[rules]`、`[[retired]]` 等设置，可把现有配置复制到审查文件再追加该段；不要把 `[design]` 写进供旧 hook 调用的自动发现配置。

完整的使用契约、30 个检查键、报告状态、扩展方式和当前边界见 [设计检查使用说明](docs/design-checks.md)。

```sh
python3 tools/lint/lint.py --root /path/to/fixed-snapshot --config /path/to/design.toml --design --format json
python3 tools/lint/lint.py --root /path/to/fixed-snapshot --config /path/to/design.toml --design --lang zh --format text
python3 tools/lint/lint.py --root /path/to/fixed-snapshot --config /path/to/design.toml --design --check design.caller-maintains-owner-state --format json
```

- 普通模式不变。设计模式只选择 `[design].rules` 与 `[design].manual` 启用项；`--check` 缩小输出范围，不强制启用。未指定 `--check` 时列出 30 个内置键，包括 `disabled`。`--lang zh` 将告警正文显示为简体中文，省略或使用 `--lang en` 时保持英文；机器状态和报告证据字段保持原样。
- 语义项使用本机 `PATH` 上已安装且受信任的 clangd，实测后端 23.1.0。`cdb` 以 `--root` 为基准，默认 `build-vscode/compile_commands.json`；1.1 与 3.3 需要该文件。没有 CDB 而允许试探的静态项按文件后缀使用固定 C++17 或 C11，并加入 `-I <root>`，不能当成构建配置。CDB 应对应所查快照；每个文件只支持一种配置。工具不执行 CDB 命令，也不使用消费仓 `.clangd`、编译器插件、驱动查询或项目脚本。只接受语言版本、宏定义/撤销、包含目录和受控语法检查选项；调试、诊断、依赖文件和目标文件参数会被安全忽略，未知选项仍报告未覆盖。clangd 的临时配置在系统临时目录（尊重 `TMPDIR`）；不建后台索引。
- 2.1、2.2 使用 clangd 解析的实际 include；目标与禁止关系来自配置，不从路径名猜测；2.2 不覆盖链接或全局符号依赖。3.4 的 `forbidden` 约束已归属生产目标的函数声明拼写，并不证明 ABI 可见性。T102/T401/T601/T501/T202 的原候选由 `Scan` 复用，词法事实不等于语义判决。
- 2.4、5.1、5.2、5.3 加 `--baseline <rev>`，且 `--root` 必须为 Git 仓根；历史检查读取 `baseline..HEAD` 的 Git 对象，不读取 index。5.1 复用既有 `retired-symbol` 的新增行协议。要让 AST 和历史证据对应同一版本，用干净的固定提交快照，而不是在有本地修改的工作树混合两类结果。
- `checks` 和 `counts.by_key` 明列零命中；`not_reported` 只表示该检查支持的形状无命中。`uncovered`、`manual_pending`、`disabled` 和 `coverage.missing_inputs/partial` 都不是干净。JSON 的 `coverage.tus` 列出实际解析的 TU，`index=none` 表示不证明跨 TU 语义。`candidate` 是线索，未运行行为重放；`violation` 只对显式声明的机器可判约束。退出 0 是生成报告且无选中项为 `uncovered`，即使报候选或违规；2 是工具/配置问题或启用项未覆盖。
- 2.3 保留无法由 AST 解析的 T401 线索及其位置，标记 `CHAIN_UNRESOLVED`；没有 T401 线索时不生成 finding，即使词法范围本身未覆盖完整。1.3、4.3、6.3 的空证据包用 `checks[].reason` 说明为什么没有可交接的证据；实际覆盖不足才报 `CHAIN_PARTIAL` / `FLOW_PARTIAL`，不从空包推断契约缺失。2.3 收紧后的候选只在调用方、包装层与委托目标均可定位时出现；类型标记、所有权、同步与错误转换语义各自排除，不凭单个实现定罪。
- R1（相似函数）与 R2（复杂度增量）是可选评审线索，不进推荐配置。它们需要 lizard 1.25.0 测量后端（`[design."design.<key>"].lizard_path` 或环境已安装的匹配版本）。配置路径只能指向当前 Python 环境内的 lizard 安装，消费仓不能借配置执行任意 Python 代码；缺失或路径不受信时报 `uncovered/NO_MEASUREMENT_BACKEND`，其余检查结果照常保留。R2 复用 tools/complexity 的测量与基线差量：`--baseline` 下只报新增/恶化，无基线时超阈函数明确标记为存量。R1/R2 的测量不依赖 clangd。

**增添/停用示例。** 在受信任的工具副本中创建 `rules/_design/example.py`。消费仓不能通过配置指定 Python 插件路径：

```python
from design import Check


def check(ctx, result):
    for path, text in ctx.sources.items():
        for n, line in enumerate(text.splitlines(), 1):
            if line.rstrip().endswith('DESIGN-REVIEW?'):
                result.gap('MARKER_UNRESOLVED', f'{path}:{n}: ambiguous review marker')
            elif line.rstrip().endswith('DESIGN-REVIEW'):
                result.add(path, n, 'DESIGN-REVIEW', 'explicit text marker',
                           {'marker': 'DESIGN-REVIEW'})


CHECKS = [Check('example-marker', 'explicit-review-marker', 'clue', check,
                missing_codes=('MARKER_UNRESOLVED',))]
```

把 `"example-marker"` 加到 `[design].rules`，用 `--check example-marker` 运行。移除该键可停用；其他项仍按各自配置执行，入口无需修改。设计插件是受信任的产品代码；新增检查应声明使用的证据与不能检查的输入，并有正反例。

`Check(..., missing_codes=...)` 只登记当前检查的特殊缺输入码，不是消费配置项；不用特殊码可省略该参数。`NO_AST`、`NO_INDEX`、`NO_BUILD_DB`、`NO_TARGET_GRAPH`、`NO_BOUNDARY_DECL`、`NO_CONTRACT`、`NO_BASELINE`、`NO_HISTORY`、`NO_BEHAVIOR_HARNESS` 是共用码，不必重复登记。`result.gap(...)` 或 `result.add(..., missing=...)` 使用未登记的特殊码时，工具报错退出 2，不生成报告。示例中 `DESIGN-REVIEW` 仍产生候选；`DESIGN-REVIEW?` 表示无法确定，报告 `uncovered/MARKER_UNRESOLVED`。

## 一仓一份配置

新配置为仓根 `.config/lint.toml`，完整示例见 [config.example.toml](config.example.toml)。全量入口缺省从 `--root` 向上查找它，或用 `--config` 显式指定。已有 schema 1 的仓库见 [Git hook 配置兼容](../git-hooks/README.md#配置兼容)；也可在旧 `.config/bbt-git-hooks.toml` 直接升级为 schema 2，但全量入口须用 `--config` 显式指定旧路径。两份配置并存时，hook 报错而不合并；全量入口仍只读取一份配置。无配置的 hook 保持既有默认规则，新 schema 未写的 hook 阶段默认为空。

| 键 | 意义 |
|---|---|
| `schema_version = 2` | 新配置版本；原 schema 1 由 Git 适配层按原默认值转换 |
| `timeout_seconds = 60` | hook 每个规则子进程超时；超时终止整个进程组 |
| `enforce_blocks = true` | 当 `--skip-rules` 选中本阶段的任一阻断项时，commit 或 pre-push 拒绝此次操作；默认 `false`，允许跳过选中的规则。 |
| `[[retired]]` | `path` 为仓内路径 glob，`symbols` 为本作用域已经确认退役的 ASCII 标识符数组。按仓维护。 |
| `[scan].rules` | 全量启用的 C++ 规则 ID，顺序执行；省略时从 meta 的 `default_enabled` 发现 |
| `[commit].rules` / `[push].rules` | 各阶段启用的规则 ID 数组；不存在阶段绑定目录 |
| `[rules.<id>].level` | `fatal`（默认）/`error`/`warn`/`notice`，只影响 hook 违规，不改变全量告警模式；语义见上文级别表 |
| `[rules.<id>].options` | 覆盖规则 meta 中的正整数阈值；未知阈值拒绝 |
| `[scope].exclude` | 路径 glob 数组，缩小源码检查范围；既有 whitespace/secrets 保留原范围 |
| `[layout]` | `allowed_roots` / `allowed_gitlinks` 为精确路径数组，只被 new-root 和 third-party-layout 读取；默认空，启用对应规则时不可为空 |
| `[[exclude]]` | `rule/path/symbol/reason` 四个非空字符串，按符号抑制 C++ 候选；T000 不可抑制 |
| `[format].binary` | clang-format 可执行文件路径；不自动安装，不修改消费仓格式配置 |

数组整体替换，未知键、类型错误、重复 ID、缺失规则、非法 meta 都报错。路径和符号使用 `fnmatchcase`，`*` 可跨 `/`；无符号诊断用 `symbol = "*"`。hook 路径相对仓根，全量相对 `--root`，两种跑法希望完全相同的排除范围时应扫描仓根。只有 `rules.<id>` 参数表不代表启用；启用由运行模式的 rules 数组决定。

示例中的 proto/测试路径和 `kRpcV2*` 公开常量排除是 bbtools 消费策略，不在框架或规则中写死。纯值记录、配置快照不能按 `*State`、`*Options` 一概放行，应按实际职责配置例外并写理由。

## 规则协议与扩展

### commit 与 pre-push 的阻断项、告警项

[示例配置](config.example.toml) 在两个阶段都运行 whitespace、format、comment-form、template-layout、retired-symbol 和 header-implementation。前三项按现有范围检查。template-layout 拦截新增的旧式路径。推送额外执行 review-ticket、llm-review 和 secrets。采用前核对本仓排除路径、退役名与原有检查，迁移到单一配置并启用两个 Git 入口。

- **阻断**。retired-symbol 只在 `[[retired]].path` 匹配的手写 C/C++ 文件逐行检查本次新增或改动的物理行。匹配完整标识符，跳过字符串、注释和 include 路径。显式路径独立于 `scope.exclude`，使已列入退役范围的测试接缝也能被检查。宏拼接、跨行拼写和文档迁移需要另行验收。
- **告警**。header-implementation 在改动涉及的接口头函数上报告能识别的模板体，以及带分支、循环、加锁、分配等线索的普通函数体。输出位置和目标文件建议。该规则只允许 `warn` 或 `notice`，普通 getter、需要调用处可见的 constexpr 定义和 `__T` 实现头可保留。词法匹配仅为人工挑选候选，复杂语法可能漏报。
- **运行边界**。提交看暂存对象，推送看各目标树相对基线的净变更。工具和配置错误保持退出码 2。规则集读取本地工作区配置，Git 的 `--no-verify` 仍可绕过客户端。托管端强制合入需要独立的 required check。

### 目录布局规则（默认关闭）

new-root 和 third-party-layout 比较 base 与目标 tree 的目录形态，不读工作区，也不内置任何仓名、顶层目录或 gitlink 白名单：允许项全部来自配置。两者都是 `git-change` 规则，只能加入 `commit.rules` 或 `push.rules`，加入 `scan.rules` 按非 C++ 规则返回 2。

- **new-root**。顶层目录取每个非顶层文件路径的首段，以及顶层 gitlink 本身；目标 tree 相对 base 新增、且不在 `layout.allowed_roots` 中的顶层目录各报一条。已有目录内的新增、修改、删除不报，因此首次创建约定目录由配置放行，日常在存量目录里加减文件不受影响。
- **third-party-layout**。本次改动涉及 `third-party` 本身或 `third-party/` 下的路径时，只有「路径在 `layout.allowed_gitlinks` 中、且目标 tree 里该路径是 gitlink（160000）」才放行；新增普通文件、放进未登记的 gitlink、把 gitlink 换成普通目录都会报到该路径。删除不在检查范围：消失的路径不再出现在目标 tree 里。
- **配置校验**。启用某条规则但 `[layout]` 对应名单缺失或为空时按配置错误处理（退出码 2），不会静默通过；名单只接受精确路径，`allowed_roots` 必须是不含 `/` 的顶层名，`allowed_gitlinks` 必须指向 `third-party` 或它内部的路径。

```toml
[commit]
rules = ["whitespace", "format", "comment-form", "template-layout", "new-root", "third-party-layout"]

[layout]
allowed_roots = ["tooling", "third-party"]
allowed_gitlinks = ["third-party/example-dep"]
```

不启用时无需写 `[layout]`：schema 1 的旧配置和没列这两个 ID 的 schema 2 配置行为不变，默认 `allowed_roots`、`allowed_gitlinks` 都是空数组，只有启用对应规则才要求非空。

每个目录的 `meta.toml` 必填字符串：`id`（等于目录名）、`interface`、`kind`、`title`、`fix`、`docs`（仓库内规范路径）。ID 匹配 `[A-Za-z][A-Za-z0-9-]*`。可选：布尔 `default_enabled`（默认 false）、`[options]` 正整数默认阈值。缺项、多余键、非法值均拒绝。

- `interface = "cpp"`：`main.py` 导出 `check(source, options)`，返回或 yield `(行号, 消息, 符号)`；行号从 1 开始，无符号用空字符串。两种入口调用同一函数。`source` 提供 `path/text/code/pairs/classes/line(offset)/top_classes()/variable_comments()/in_body(offset)/exists(path)`；`code` 已屏蔽字符串、注释和预处理行。不可变源码、词法信息与目录存在性由 core 提供，不要自行重读工作区文件。
- `interface = "git-change"`：兼容既有空白、格式、注释形态、模板路径和目录布局检查，stdin JSON 提供 `config/base/tree` 或 push `updates`；通过 `staged.contexts()` 取得改动范围。
- `interface = "git-push"`：ticket、审查证据、密钥等既有推送检查，需要推送上下文，不伪造全量源码扫描的证据。Git 专用规则不加入 `scan.rules`；加入会返回 2。
- `kind = "auto"` 表示现场检查，`attested` 表示只核对提交的证据，不执行实际审查。

Git 专用脚本通过返回 0；违规退出 1，并在 stdout 输出一个 JSON 对象：`code`（`E-` 开头大写错误码）、非空字符串数组 `problems`、可选 `fix`。可复用 `runner.report()` / `RuleFail`。工具错误退出 2；以 1 退出却没有合法报告仍是 ERROR。C++ 规则无需重复这层进程协议，由适配器处理。目录内代码是受信任本地插件，不是沙箱；不要联网、修改源码或启动脱离进程组的后台任务。全量入口在本进程加载 C++ 检查；hook 用独立进程隔离并限制运行时间。

新增一条规则不改 runner：

1. 复制 `rules/_template/` 到 `rules/my-rule/`，把 meta 的 id 改为 `my-rule`，填写标题、修法和文档路径。
2. 在 `main.py` 填写 `check(source, options)`；需要阈值时只在同目录 meta 的 `[options]` 定义默认值。
3. 配置数组加一行/一个 ID：全量加到 `scan.rules`，hook 加到 `commit.rules` 或 `push.rules`；用 `[rules.my-rule] level = "error"` 选择阻断但继续执行其余规则，`"warn"`/`"notice"` 选择放行。新增目录不会自动开启 hook。C++ 规则放进 hook 前先确认改动文件不含条件编译或复杂宏：解析不完整时 hook 返回 2，`warn` 不能降级。

## C++ 候选规则

阈值筛选候选，不定义新的强制代码规范。T201/T202 属于家族审美，其余 T1xx/T3xx/T4xx/T5xx/T6xx 是 C++ 通用结构线索，T000 是覆盖诊断。

| ID | 线索与默认阈值 |
|---|---|
| T000 | 不可读、预处理宏/分支、未分类成员、未闭合词法或括号等；始终保留，不可禁用/抑制 |
| T101 | 直接非静态字段数 `> fields = 10` **且存在公开可变字段**；struct 默认 public、class 默认 private；公开操作多但字段全私有不报；const/constexpr 字段不作为公开可变字段 |
| T102 | 同一行的 lock_guard/unique_lock/scoped_lock 使用 `.mu`/`->mutex` 等成员；无法证明是外部所有者 |
| T201 | 只看函数体外、紧贴简单变量声明上方的注释；普通 `/* */`，`short_comment_chars = 48` 以内单行；跳过函数体、行内和行尾注释 |
| T202 | 短变量注释内容人工复核，`short_comment_chars = 48`；**默认关闭，不建议自动删除**，特殊值/范围/顺序/所有权/寿命约束必须保留 |
| T301 | 文件总行数 `> file_lines = 1000`，包括空行和注释，不证明多职责 |
| T302 | 头文件 stem 不匹配任何顶层 class/struct；职责命名也可能合理 |
| T303 | 实现无同目录同 stem 头文件；不做跨 TU 符号配对 |
| T304 | 头文件有多个类型、数据成员、类外 constexpr 与自由接口；不理解职责 |
| T401 | 无字段类的全部操作都是 static 单调用内联定义，至少 `forwarders = 2`；不判断 ABI 或适配价值 |
| T501 | 标识符含大写 V 加数字；不查字符串、注释、数字值，不自动改名 |
| T601 | 生产范围标识符含 ForTest/TestAccess/for_test/test_inject；不追踪匿名测试全局状态 |
| `coroutine-sugar` | 按标识符筛查协程低层调用（Scheduler、Coroutine、同步原语、async 内部接口）候选；默认关闭，严格仓库显式启用；例外写法见 [协程语法糖](../../docs/cpp/coroutine.md#3-用-lint-固化语法糖边界) |

## 覆盖边界与验证

这是词法启发式，不展开宏、不做完整 C++ 语义解析、继承分析、预处理求值或编译数据库解析。未检测出的复杂声明仍可能漏计，`partial_files` 为空也不是 AST 完整性证明。初始化器、属性、函数指针、匿名类型、模板特化、复杂运算符、const 别名及注释归属尤其需要人工复核。函数体边界按花括号上下文推断；复杂宏可能无法识别。T101 的字段数包含私有字段，但触发必须有公开可变字段。T202 即使开启也只列人工候选。

规则语义变更仍需独立审查；本地运行不等于 CI 或合入门禁通过。现有 hook 回归入口：

```sh
python3 -m unittest discover -s tools/git-hooks/tests -v
```

测试只使用自有临时仓与本地 bare remote，不访问真实远端。新增候选规则的系统性测试由独立 QA 补充；不把存量扫描或扩展示例当成完整规则回归。
