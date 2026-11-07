# Complexity：结构扫描与语义打分器

这是可运行的本地 CLI，不会修改被扫描仓库、baseline 或 ignore，也不会联网、调用模型、提交或修改 CI。

本工具已纳入共用 Review 的辅助检查，**只作参考，不作为提交或合并门禁**；适用范围和结果处理规则以 pub 根路径 `docs/30-review/README.md` 的“复杂度工具只作参考”为准。以下退出码保留原始分析状态，不自动转换成 Review 结论。

- `scan`：用固定版本 lizard 采集 C++ 函数的 CogC、CCN、有效行数和参数数，可对比 Git 基准或旧报告。
- `prepare`：为一个具名能力收集显式选定的实现、调用者、契约，生成带源码哈希和五维判据的语义评估包。
- `score`：读取人工或模型提供的结构化评估，验证源码引用、聚合两轮判断，输出 U/R/A/L/G 五维等级、增量和例外状态。它不负责生成评估，更不把结构计数冒充语义判断。

## 环境与最短使用路径

需要 Python 3.11+、Git（仅 Git 基准功能需要）、lizard 1.25.0。依赖固定在 [requirements.txt](requirements.txt)；可复用已有满足版本的虚拟环境。需要新环境时，由使用者执行：

```sh
python3 -m venv .venv-complexity
.venv-complexity/bin/python -m pip install -r tools/complexity/requirements.txt
.venv-complexity/bin/python tools/complexity/complexity.py --help
```

以下命令从 pub 仓库执行，`python` 代表上述虚拟环境的解释器。`--root` 指向被分析仓库；`--config`、`--baseline`、`--ignore`、`--output` 等文件参数相对于当前工作目录；评估包中的源码路径相对于 `--root`。

```sh
# 与目标分支的 merge-base 对比；包含当前工作区未提交的源码变化。
python tools/complexity/complexity.py scan --root ../bbtools-infra \
  --config tools/complexity/config.example.toml --base origin/main \
  --output infra-complexity.json

# 明确比较某个提交，而不是 merge-base。
python tools/complexity/complexity.py scan --root ../bbtools-infra \
  --base HEAD --base-mode commit --format markdown

# 不给基准时是存量清单；完整 JSON 报告可以由维护者选为 baseline。
python tools/complexity/complexity.py scan --root ../bbtools-infra --output inventory.json
python tools/complexity/complexity.py scan --root ../bbtools-infra \
  --baseline inventory.json --output current.json
```

输出文件必须不存在，避免覆盖旧证据或误写源文件。工具不会自动建立输出目录。不指定输出则写 stdout；错误说明写 stderr。`--format` 支持 `json`、`markdown`、`github`；后者只输出 annotation 文本，不会发布评论或修改 workflow。JSON 是完整证据，Markdown/GitHub 是摘要。

## 评分和退出码

结构阈值默认 `CogC > 25`、`CCN > 15`、`nloc > 100`、`参数 > 6`。语义默认 `等级 >= 2`、比基线增长至少 1 级；新根因单独判定。等级是顺序尺度，不相加成百分制总分。

无基准时只列 `inventory`；有基准时只有新增或恶化的超阈值项发 warning。同一根因的多个语义维度聚合为一条，未出现的旧根因只记 `unmatched_baseline`，不自动宣称修复。模型、rubric、确认次数、作用域或契约不兼容时记 `not_comparable`，不生成虚假的前后差值。

| 退出码 | 含义 |
|---|---|
| 0 | 分析完整；默认 warning 模式不阻塞。0 不表示没有复杂度问题，也不证明语义评估准确。 |
| 1 | 配置 `quality_policy = "fail"`，且有未被有效 ignore 接受的新增/恶化告警。 |
| 2 | 配置/输入/依赖错误，或覆盖不完整。包括证据过期、无匹配源码、预算不足、重复身份无法区分、语义未知或复核缺失。 |

第一版对 `partial` 统一返回 2，比分层设计中的可配置 coverage 策略更保守；不允许把未检查当通过。

## 配置与 baseline

运行配置见 [config.example.toml](config.example.toml)。可以只填要覆盖的键：对象按键合并，数组整体替换。支持结构阈值、范围、五维开关与阈值、确认次数、最低增量和文件/字节预算。未知键、错误类型和越界值直接报错。

设计文档 `docs/10-design/examples/semantic-complexity.toml` 是更大范围的拟议协议，**不能直接给本 CLI 使用**。首版没有路径 overrides、自定义维度、AST 引用图、net/churn、远程模型配置或自动 baseline prune；不默默接受这些尚未实现的配置。

结构与语义 baseline 各使用同类完整 JSON 报告。baseline 只记录存量，不代表认可设计。质量阈值调整不改变原始计数；评估方法或覆盖范围改变则不可直接比较。基线内容和评估来源由维护者负责审核，本工具不提供签名或身份认证。

## 语义层：先准备证据，再输入评估

使用真实路径替换下列示例；一个包对应一个能力。源码和注释是数据，不是给模型的操作指令。文件包可能包含私有代码，只有使用者确认后才可自行发给模型。

```sh
python tools/complexity/complexity.py prepare --root ../bbtools-infra \
  --unit 'Server::Start' --scenario '启动已配置的服务' \
  --file bbt/infra/rpc/Server.cc \
  --consumer tests/rpc_net/Test_rpc_v2_session.cc \
  --contract docs/guides/rpc-net.md --base HEAD --base-mode commit \
  --output server-packet.json

python tools/complexity/complexity.py score --root ../bbtools-infra \
  --packet server-packet.json --reviews server-reviews.json \
  --output server-score.json

# 对比先前完成的同能力评估；当前包和评估仍需匹配当前源码。
python tools/complexity/complexity.py score --root ../bbtools-infra \
  --packet next-packet.json --reviews next-reviews.json \
  --baseline server-score.json --output next-score.json
```

`--file`、`--consumer`、`--contract` 可重复；三类上下文都需要。可用 `--base` 加入所选文件在旧提交中的内容，缺失旧文件表示当时不存在。第一版不会自动发现调用链，也不能只因为三个文件存在就证明上下文完备；评估者必须如实设置 `context_sufficient`。

评估 JSON 的字段约定：

- 顶层：`schema_version: 1`、原样复制包中的 `packet_digest`、`evaluator: {name, version}`、`rounds`。evaluator 标明具体人工评估流程版本或实际模型/提示版本，不填虚构身份。
- 每轮：不同的 `review_id`、布尔 `context_sufficient`、实际检查的 `assessed_axes` 数组（通常 U/R/A/L/G）、`findings` 数组。没有问题可为空数组，但不能省掉已检查维度。
- 每个 finding：稳定的 `root_cause`、`levels`（U/R/A/L/G 必须全部出现，值为整数 0–3 或 null）、`burden`、`necessity`、`counterevidence`、`simpler_direction` 和 `evidence` 数组。
- 每个 evidence：`path`、`version`（after/before）、1 起始的 `start_line`、`end_line`、确实出现在该范围中的 `quote`。

下面仅展示一条 finding 的形状，不是本仓实际评估，不可把它当模型输出：

```json
{
  "root_cause": "manual-assembly",
  "levels": {"U": 2, "R": 0, "A": 2, "L": 0, "G": null},
  "burden": "填写实际调用者必须维护的额外步骤",
  "necessity": "填写需求、安全和兼容性核对结论",
  "counterevidence": "填写最强的反对本告警的依据",
  "simpler_direction": "填写保留必要契约的简化方向",
  "evidence": [{
    "path": "bbt/example.cc", "version": "after",
    "start_line": 1, "end_line": 3, "quote": "必须替换成真实源码片段"
  }]
}
```

默认要求两轮；同根因取较低等级，跨告警阈值分歧或任何 null 保留为 uncertain。不完整字段/缺失复核不会变成零分；省略一轮后把 `confirmations=1` 显式配置才采用单轮模式，并标 `single_assessment`。复核 ID 仅用于区分记录，工具不能验证两轮真的独立。

语义层只验证证据存在、内容未变以及规则计算，不验证自然语言推理正确。报告保留原始评估，不使用模型自报 confidence 作为准确率。实际模型调用和人工标注校准尚未接入。

## 带理由的 ignore

从 JSON finding 复制 `finding_id`、`rule`、`unit`、`evidence_digest`，在维护者管理的 TOML 中添加精确条目：

```toml
[[ignore]]
finding_id = "替换为报告的64位哈希"
rule = "semantic" # 或 structural.cognitive_complexity 等
unit = "Server::Start"
evidence_digest = "替换为报告的64位哈希"
reason = "此边界用于隔离第三方类型；附上适用契约和人工判断依据。"
# expires_on = "2027-01-01"
```

扫描/评分时用 `--ignore path/to/ignore.toml`。缺理由、格式错误、重复 ID 会失败。过期或证据改变时标 `needs_review`，不会继续抑制告警；未命中的条目保留为 `unused_ignores`，不会自动删除。语义 ignore 接受整个根因而非偷偷只接受某一维。

结构指纹使用函数所在行范围的词法 token，忽略空白和注释；同一行有多个函数时指纹可能包含邻居，属于保守失效。语义指纹绑定所有上下文全文哈希，因此调用者、契约注释或格式变化都会要求重新评估。

## 已知边界与验证入口

- lizard 是词法度量，不是 C++ 编译器；没有编译数据库也能扫描，但不能证明语法正确、穷尽条件编译或建立精确调用图。
- 它可能丢失模板特化信息。重名成员用内容指纹区分；内容变化后无法可靠配对则不硬判新增，完全相同且仍重名的定义报告覆盖不完整。
- 仅对唯一、同符号且同内容的跨文件搬移配对。不能可靠识别的重命名列为未配对，不自动宣称修复。
- 不跟随目录符号链接；选中的文件符号链接或越界路径拒绝。默认只扫描 include 中的 C++ 文件；其他语言不是当前支持范围。
- 结构和语义分别报告，不自动把结构热点当成全部语义候选。单实现类、包装层和新增行数不会被自动定罪。
- CLI 的测试包含合成评估，仅证明规则与数据链路，不证明模型准确率或设计阈值合理。

```sh
python -m unittest discover -s tools/complexity/tests -v
```
