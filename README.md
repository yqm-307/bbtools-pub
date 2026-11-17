# bbtools 共用开发规范（根路由）

这份仓库把 bbtools 家族特有的开发规范与本地工程工具聚在一起；通用语言规范与角色方法已迁出，消费仓通过 `third-party/bbt-agent-toolkit/`（submodule，由协调者稍后添加，链接暂时无法解析属预期）引用。

## 先看引用方向

引用只能向下，不得反向：

1. 根 `README.md` 指向本仓家族特有规范与工具入口；通用部分指向 `third-party/bbt-agent-toolkit/standards/` 与 `third-party/bbt-agent-toolkit/agents/`。
2. 本仓入口只指向自己目录中的文件。
3. 同一规则只留一个完整正文，其他地方用短句说明适用层级，不复制整段。

### 通用 → toolkit

- 通用原则：`third-party/bbt-agent-toolkit/standards/general/principles.md`
- 审美与代码品味：`third-party/bbt-agent-toolkit/standards/general/code-taste.md`
- 注释内容：`third-party/bbt-agent-toolkit/standards/general/documentation.md`
- C++ 通用写法：`third-party/bbt-agent-toolkit/standards/cpp/style.md`
- C++ Doxygen 通用写法：`third-party/bbt-agent-toolkit/standards/cpp/documentation.md`
- C++ 格式：`third-party/bbt-agent-toolkit/standards/cpp/format.md`
- 角色方法（architect/engineer/qa/reviewer）与多智能体工作流：`third-party/bbt-agent-toolkit/agents/`

### 家族特有 → docs/

- C++ 命名与类型、头文件与类布局、协程语法糖、注释与 Doxygen 排版、构建与测试：`docs/cpp/`
- 语义复杂度设计与示例配置：`tools/complexity/docs/`

### 工具 → tools/

- 复杂度打分器：`tools/complexity/`
- 本地 Git hooks：`tools/git-hooks/`

## 开工与测试前的核对

这是纪律，与任务类型无关：开始开发前、开始跑测试前各核对一次，结果写进交付说明。测试前再核对一次，是因为开发期间分支和依赖可能变过。

1. **依赖库**：确认实际使用的依赖及版本（子模块固定提交、包管理锁文件、系统库、上游仓版本）与项目声明一致；版本不明或不符，先报告，不凭印象开工。
2. **当前分支与基线**：确认所在分支、HEAD 与工作树状态；先 `git fetch`（只更新远端跟踪引用，不改工作树），再核对是否基于目标分支（通常 `main`）的 latest，落后多少、有无冲突风险。
3. **落后时**：不静默继续，也不自行 pull、rebase、merge 或重置；报告落后情况，按项目规则或用户决定处理。工作树有未提交改动时，不得为了“更新”而 stash、reset 或覆盖。
4. **证据绑定**：测试结论注明所基于的分支、提交和依赖版本；基线或依赖在测试前后变过，结论作废并重测。

正例：开工前 fetch 发现分支落后 `main` 三个提交，先报告并等处理方式，再开始编码。

反例：凭印象认为依赖没变、分支是最新，直接开发；测试通过后才发现基于一个旧基线，结论无法用于合入。

## 选择一条阅读路径

第一步读本根路由，再按当前职责进入：

| 当前任务 | 入口 | 需要时再展开 |
|---|---|---|
| 设计 API、模块边界、失败与关闭语义 | 工具 `agents/architect/`（toolkit） | 语义复杂度指标与告警口径：`tools/complexity/docs/semantic-complexity.md` |
| 编写或修改实现 | `docs/cpp/`（家族特有 C++） + 工具 `agents/engineer/`（toolkit） | C++ 通用写法 `standards/cpp/style.md` |
| 评审代码、设计或文档 | 工具 `agents/reviewer/`（toolkit） | 生命周期与扩展专项同 `agents/reviewer/` |
| 设计、精简行为与回归用例 | 工具 `agents/qa/`（toolkit） | 并发与生命周期、按阶段运行同 `agents/qa/` |
| 长程任务拆给多个智能体 | 工具 `agents/workflow.md`（toolkit） | 无专项文件；调度器、模型与命令不在本层 |

“需要时”由场景入口中的触发条件决定，不按仓库里出现了某个目录就全量加载。例如：改一个普通 C++ 值类型：通用原则 → `docs/cpp/naming-and-types.md`；不读生命周期专项。

## 维护规则

- 同一条规则只有一个完整正文，其他地方用短句说明适用层级，不复制整段。
- 新增专项前先确认已有场景文件无法承载，且确实有不同触发条件或风险；不要为目录完整而预建空文件。
- 公共正文只写稳定、可复用的判断方式；过程日志、审查报告、测试输出和私有来源留在仓外证据中。
- 入口、文件名和命令必须实际存在；改目录后同步更新本文件中的路径，并做链接存在性和环检测。
- 规范可以精练，但删掉会改变行为判断的约束时，要在新正文或迁移说明中交代去向。
- 每次遇到新的 badcase，先判断它是否改变当前用户或后来维护者必须知道的事实；需要知道就直接修正唯一真源、代码、测试、文档或提示词中的当前措辞，不把旧句子留着再追加补丁。历史原因默认留在 commit、ADR、审查报告或私有证据中。
- 只有兼容性、迁移、安全或不可逆决策确实依赖历史时，稳定正文才保留最小背景；Issue 号和阶段叙事不能代替当前契约。Review 必须检查新概念后是否仍残留旧定义。

历史兼容入口 `docs/conventions.md` 已删除；不再维护第二份正文。

## 本地工程工具

- [复杂度打分器](tools/complexity/README.md)：结构扫描、语义证据评分、基线与 ignore；尚未接入 CI。
- [本地 Git hooks](tools/git-hooks/README.md)：commit 机械检查、push 前核对随仓库提交的 review ticket 并现场检查格式与密钥；规则有统一的 meta 与报错协议，首错即停，支持 `--skip-rules`；仓库适配写在 `.config/bbt-git-hooks.toml`。

## 门禁

- 须先获用户授权：commit、push、开 PR、付费调用、破坏性操作、新依赖、CI/发布变更、删除或重命名公开的规范路径与工具入口（可能已被消费仓引用）、改变公共规则的适用范围。任务会产生改动时，开工时一次问清是否授权 commit/push/开 PR，授权覆盖整段任务；未授权则停在 commit 前，交付改动与验证结果。
- 只改获授权范围，保留他人已有改动；远端写入后回读确认目标对象。
