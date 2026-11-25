# bbtools 共用开发规范（根路由）

本仓提供 bbtools 家族约定与共享检查工具。通用语言规范和角色提示词由 `bbt-agent-toolkit` 维护，本仓通过 submodule 固定到 toolkit `main` 已合入的提交。项目契约、启用哪些检查以及哪些检查阻断合入，由消费仓自己定义。

| 你要做什么 | 从这里开始 |
|---|---|
| 按任务引用编码、设计或构建约束 | [四类约束](#四类约束) |
| 查角色提示词或工作流 | [角色提示词与工作流](#角色提示词与工作流) |
| 跑格式、lint 或复杂度检查 | [本地工程工具](#本地工程工具) |
| 给消费仓接入 Git hook 或 CI 检查 | [接入门禁](#接入门禁) |

## 先看引用方向

引用只能向下，不得反向：

1. 根 `README.md` 指向本仓家族特有规范与工具入口；通用部分指向 `third-party/bbt-agent-toolkit/standards/` 与 `third-party/bbt-agent-toolkit/agents/`。
2. 本仓入口只指向自己目录中的文件。
3. 同一规则只留一个完整正文，其他地方用短句说明适用层级，不复制整段。
4. 下游仓引用上游时指向上游根路由（消费仓引 `third-party/bbtools-pub/README.md`），不固定上游内部的职责目录；上游内部路径变动只改上游根路由。例外：上游声明为稳定入口的路径（如 `tools/`、`docs/cpp/`）可直接引用。

## 开工与测试前的核对

这是纪律，与任务类型无关：开始开发前、开始跑测试前各核对一次，结果写进交付说明。测试前再核对一次，是因为开发期间分支和依赖可能变过。

1. **依赖库**：确认实际使用的依赖及版本（子模块固定提交、包管理锁文件、系统库、上游仓版本）与项目声明一致；版本不明或不符，先报告，不凭印象开工。
2. **当前分支与基线**：确认所在分支、HEAD 与工作树状态；先 `git fetch`（只更新远端跟踪引用，不改工作树），再核对是否基于目标分支（通常 `main`）的 latest，落后多少、有无冲突风险。
3. **落后时**：不静默继续，也不自行 pull、rebase、merge 或重置；报告落后情况，按项目规则或用户决定处理。工作树有未提交改动时，不得为了“更新”而 stash、reset 或覆盖。
4. **证据绑定**：测试结论注明所基于的分支、提交和依赖版本；基线或依赖在测试前后变过，结论作废并重测。

正例：开工前 fetch 发现分支落后 `main` 三个提交，先报告并等处理方式，再开始编码。

反例：凭印象认为依赖没变、分支是最新，直接开发；测试通过后才发现基于一个旧基线，结论无法用于合入。

## 选择一条阅读路径

### 四类约束

四类按任务选用，不是必须读完的一套提示词。引用其中一类，不等于采用其他类或某个角色。

| 类别 | 什么时候读 | 正文入口 |
|---|---|---|
| **bbtools 系列仓库编码约束** | 在 bbtools 系列仓写代码，需要确定家族特有的命名、错误返回、类声明布局、协程语法糖或注释排版。 | [bbtools 家族 C++ 约定](docs/cpp/README.md)，按主题选文件。 |
| **C++ 通用编码约束** | 决定 C++ 代码怎么写，例如 RAII、值语义、智能指针、头文件、Doxygen 或格式；不规定 bbtools 的具体取值。 | toolkit：[C++ 写法](third-party/bbt-agent-toolkit/standards/cpp/style.md)、[文档注释](third-party/bbt-agent-toolkit/standards/cpp/documentation.md)、[格式](third-party/bbt-agent-toolkit/standards/cpp/format.md)。 |
| **通用 OOP 设计约束** | 设计或评审对象职责、状态、依赖、接口契约与生命周期；判断不依赖某种语言的语法。 | toolkit：[代码品位](third-party/bbt-agent-toolkit/standards/general/code-taste.md)、[设计专项索引](third-party/bbt-agent-toolkit/standards/general/taste/00-overview.md)、[所有权与并发](third-party/bbt-agent-toolkit/standards/general/ownership-and-concurrency.md)。 |
| **工程构建约束** | 核对构建基线、依赖、编译目标、测试注册或验证结果。 | 先按目标仓的构建与测试入口。bbtools 家族另见 [构建与测试约定](docs/cpp/build-and-test.md)；通用的增量构建、并发和超时做法，目前见 toolkit 的 [Engineer「构建与机器资源」](third-party/bbt-agent-toolkit/agents/engineer/AGENTS.md#构建与机器资源)，还没有独立的通用构建规范。 |

在消费仓的规则入口或任务说明里，写清**何时读取、读取固定版本中的哪个文件、哪些本地约束优先**。例如：在 bbtools 仓改普通 C++ 值类型，读通用 C++ 写法和家族命名约定；如果还涉及对象职责或所有权变化，再读对应的 OOP 设计专项。非 bbtools 仓可直接固定并引用 toolkit，无需引入 pub。只挂链接不会让宿主自动加载；必需规则读不到时，暂停依赖它的步骤并报出路径。

### 角色提示词与工作流

[toolkit 角色入口](third-party/bbt-agent-toolkit/agents/README.md) 提供 architect、engineer、qa、reviewer 的独立身份与接入方式；[工作流](third-party/bbt-agent-toolkit/agents/workflow.md) 说明如何分工与验收。角色说明「谁怎么干活」，上面的四类约束说明「这项工作按什么规则做」，可分别引用。

## 维护规则

- 新增专项前先确认已有场景文件无法承载，且确实有不同触发条件或风险；不要为目录完整而预建空文件。
- 公共正文只写稳定、可复用的判断方式；过程日志、审查报告、测试输出和私有来源留在仓外证据中。
- 入口、文件名和命令必须实际存在；改目录后同步更新本文件中的路径，并做链接存在性和环检测。
- 规范可以精练，但删掉会改变行为判断的约束时，要在新正文或迁移说明中交代去向。
- 遇到新的 badcase，按 toolkit [P7：用当前契约修正 badcase](third-party/bbt-agent-toolkit/standards/general/principles.md#p7) 修正唯一真源。Issue 号和阶段叙事不能代替当前契约；Review 仍须检查是否残留旧定义。

历史兼容入口 `docs/conventions.md` 已删除；不再维护第二份正文。

## 本地工程工具

- [C/C++ 格式化工具](tools/format/README.md)：按目标仓格式配置检查暂存区或全仓，也可格式化改动文件；初次使用建议先用 `--check`，不改源码和暂存区。
- [可组合 lint：快速接入](tools/lint/README.md#快速接入)：用一条命令只读扫描 C/C++，也能用于非 bbtools 仓库；规则与 Git hook 按需启用。
- [复杂度打分器](tools/complexity/README.md#环境与最短使用路径)：结构扫描、语义证据评分、基线与 ignore；从 pub 运行，`--root` 指向目标仓；用于 Review 辅助，不作为门禁。首次运行先确认 Python 和 lizard 版本。
- [本地 Git hooks](tools/git-hooks/README.md)：保留 commit/push 入口及旧配置兼容；规则与配置机制统一见 [lint](tools/lint/README.md)。

## 接入门禁

- **Git hook**：从 [本地 Git hooks](tools/git-hooks/README.md) 查 commit/push 接入和旧配置兼容。从 [lint 配置说明](tools/lint/README.md#一仓一份配置) 查如何在消费仓选择规则、阈值、排除项和阻断级别。规则独立目录、共用检查核心，不绑定消费仓。
- **CI**：从消费仓自己的 workflow 和 `scripts/ci/` 查实际运行的检查与必过项。pub 提供工具入口，不替消费仓启用 CI；本地 hook 结果不是 CI 或合入门禁的结果。

## 门禁

维护本仓前，读仓根 `AGENTS.md` 的「门禁」。授权、独立审查、已有改动保护和远端写入后的回读要求均以该处为准。
