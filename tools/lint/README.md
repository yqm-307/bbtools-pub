# 可组合 lint

规则独立于 Git 阶段；同一 C++ 检查用于全量存量清单和 hook 改动文件。Python 3.11+ 标准库，无安装依赖，不联网、不改源码、不调用模型、不自动启用 hook 或接入 CI。告警是人工复核候选，不是缺陷判决。

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
│   └── hook.py             index/推送对象到源文件检查的适配
└── rules/
    ├── _template/          新 C++ 规则模板
    └── <id>/               meta.toml + main.py（可含规则私有辅助脚本）
```

Git 入口保留在 `tools/git-hooks/hooks/`；阶段目录只保留入口，规则全部放在本目录。Git 范围、ticket 与历史配置名在 Git 适配层处理，C++ 核心不内置仓名、协议名或项目排除项。`format` 在 commit/push 共用一份实现。

全量模式读取工作区 `.h/.hh/.hpp/.hxx/.c/.cc/.cpp/.cxx`，不跟随源码软链接。文本 stdout 为 `file:line rule warn message`，stderr 为覆盖摘要；JSON 包含有效配置、逐项命中、按规则计数、排除文件、抑制数量及解析不完整文件。路径相对 `--root`；计数是诊断条目数，不是缺陷数。

退出码：全量 **0** 表示未检测到扫描覆盖错误，即使有告警也不返回 1；**2** 表示输入/配置错误、无源码或解析不完整，不是通过。hook **0** 表示没有阻断项（可以有 WARN），**1** 表示规则违规且配置为阻断，**2** 表示工具/配置/解析错误；错误不能用 warn 降级。hook 按配置顺序执行，阻断或错误时首错即停；warn 会打印诊断并继续，不能称为 PASS。

hook 的 C++ 候选规则扫描本次改动文件的完整内容：commit 使用 index 冻结 tree，push 使用实际推送对象和旧远端/新分支边界；不读未暂存源码，不扫描无改动文件。头实现配对也基于同一 Git tree。既有 `comment-form` 仍只检查与新增/修改行相交的注释，`secrets` 仍只查新增行，`template-layout` 仍只查新增路径，其他既有检查的范围不变。

## 一仓一份配置

新配置为仓根 `.config/lint.toml`，完整示例见 [config.example.toml](config.example.toml)。全量入口缺省从 `--root` 向上查找它，或用 `--config` 显式指定。hook 仍支持原 `.config/bbt-git-hooks.toml` 的 schema 1；也可在该旧路径直接升级为 schema 2，但全量入口须显式指定。两个配置文件同时存在时报错，不做隐式合并。未迁移旧配置的仓库不需要任何修改；无配置的 hook 保持既有默认规则，新 schema 未写的 hook 阶段默认为空。

| 键 | 意义 |
|---|---|
| `schema_version = 2` | 新配置版本；原 schema 1 由 Git 适配层按原默认值转换 |
| `timeout_seconds = 60` | hook 每个规则子进程超时；超时终止整个进程组 |
| `[scan].rules` | 全量启用的 C++ 规则 ID，顺序执行；省略时从 meta 的 `default_enabled` 发现 |
| `[commit].rules` / `[push].rules` | 各阶段启用的规则 ID 数组；不存在阶段绑定目录 |
| `[rules.<id>].level` | `block`（默认）或 `warn`，只影响 hook 违规，不改变全量告警模式 |
| `[rules.<id>].options` | 覆盖规则 meta 中的正整数阈值；未知阈值拒绝 |
| `[scope].exclude` | 路径 glob 数组，缩小源码检查范围；既有 whitespace/secrets 保留原范围 |
| `[[exclude]]` | `rule/path/symbol/reason` 四个非空字符串，按符号抑制 C++ 候选；T000 不可抑制 |
| `[format].binary` | clang-format 可执行文件路径；不自动安装，不修改消费仓格式配置 |

数组整体替换，未知键、类型错误、重复 ID、缺失规则、非法 meta 都报错。路径和符号使用 `fnmatchcase`，`*` 可跨 `/`；无符号诊断用 `symbol = "*"`。hook 路径相对仓根，全量相对 `--root`，两种跑法希望完全相同的排除范围时应扫描仓根。只有 `rules.<id>` 参数表不代表启用；启用由运行模式的 rules 数组决定。

示例中的 proto/测试路径和 `kRpcV2*` 公开常量排除是 bbtools 消费策略，不在框架或规则中写死。纯值记录、配置快照不能按 `*State`、`*Options` 一概放行，应按实际职责配置例外并写理由。

## 规则协议与扩展

每个目录的 `meta.toml` 必填字符串：`id`（等于目录名）、`interface`、`kind`、`title`、`fix`、`docs`（仓库内规范路径）。ID 匹配 `[A-Za-z][A-Za-z0-9-]*`。可选：布尔 `default_enabled`（默认 false）、`[options]` 正整数默认阈值。缺项、多余键、非法值均拒绝。

- `interface = "cpp"`：`main.py` 导出 `check(source, options)`，返回或 yield `(行号, 消息, 符号)`；行号从 1 开始，无符号用空字符串。两种入口调用同一函数。`source` 提供 `path/text/code/pairs/classes/line(offset)/top_classes()/variable_comments()/in_body(offset)/exists(path)`；`code` 已屏蔽字符串、注释和预处理行。不可变源码、词法信息与目录存在性由 core 提供，不要自行重读工作区文件。
- `interface = "git-change"`：兼容既有空白、格式、注释形态和模板路径检查，stdin JSON 提供 `config/base/tree` 或 push `updates`；通过 `staged.contexts()` 取得改动范围。
- `interface = "git-push"`：ticket、审查证据、密钥等既有推送检查，需要推送上下文，不伪造全量源码扫描的证据。Git 专用规则不加入 `scan.rules`；加入会返回 2。
- `kind = "auto"` 表示现场检查，`attested` 表示只核对提交的证据，不执行实际审查。

Git 专用脚本通过返回 0；违规退出 1，并在 stdout 输出一个 JSON 对象：`code`（`E-` 开头大写错误码）、非空字符串数组 `problems`、可选 `fix`。可复用 `runner.report()` / `RuleFail`。工具错误退出 2；以 1 退出却没有合法报告仍是 ERROR。C++ 规则无需重复这层进程协议，由适配器处理。目录内代码是受信任本地插件，不是沙箱；不要联网、修改源码或启动脱离进程组的后台任务。全量入口在本进程加载 C++ 检查；hook 用独立进程隔离并限制运行时间。

新增一条规则不改 runner：

1. 复制 `rules/_template/` 到 `rules/my-rule/`，把 meta 的 id 改为 `my-rule`，填写标题、修法和文档路径。
2. 在 `main.py` 填写 `check(source, options)`；需要阈值时只在同目录 meta 的 `[options]` 定义默认值。
3. 配置数组加一行/一个 ID：全量加到 `scan.rules`，hook 加到 `commit.rules` 或 `push.rules`；用 `[rules.my-rule] level = "warn"` 选择不阻断。新增目录不会自动开启 hook。C++ 规则放进 hook 前先确认改动文件不含条件编译或复杂宏：解析不完整时 hook 返回 2，`warn` 不能降级。

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

## 覆盖边界与验证

这是词法启发式，不展开宏、不做完整 C++ 语义解析、继承分析、预处理求值或编译数据库解析。未检测出的复杂声明仍可能漏计，`partial_files` 为空也不是 AST 完整性证明。初始化器、属性、函数指针、匿名类型、模板特化、复杂运算符、const 别名及注释归属尤其需要人工复核。函数体边界按花括号上下文推断；复杂宏可能无法识别。T101 的字段数包含私有字段，但触发必须有公开可变字段。T202 即使开启也只列人工候选。

规则语义变更仍需独立审查；本地运行不等于 CI 或合入门禁通过。现有 hook 回归入口：

```sh
python3 -m unittest discover -s tools/git-hooks/tests -v
```

测试只使用自有临时仓与本地 bare remote，不访问真实远端。新增候选规则的系统性测试由独立 QA 补充；不把存量扫描或扩展示例当成完整规则回归。
