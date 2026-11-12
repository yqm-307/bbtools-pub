# 本地 Git hooks

Python 3.11+ 标准库实现，运行环境为 Linux/WSL（规则超时用进程组终止）。不联网、不调用模型、不改源码；只在本地启用。不替代 CI、分支保护或发布审批，也不防伪。

## 布局与执行

```text
git-hooks/
├── hooks/            Git 入口（core.hooksPath 指向这里）
│   ├── commit-msg
│   └── pre-push
├── core/             共享实现与示例配置
│   ├── runner.py     配置、按序执行、跳过、超时、统一渲染
│   ├── staged.py     暂存快照读取
│   ├── pushed.py     推送范围与 ticket 读取
│   ├── formatcheck.py  commit 与 push 共用的格式检查
│   └── config.example.toml
├── stages/           按阶段收纳入口与规则
│   ├── commit/       main.py + rules/<规则名>/
│   ├── push/         main.py + rules/<规则名>/
│   └── _template/    新规则骨架
└── tests/
```

- `hooks/commit-msg` → `stages/commit/main.py`：读取提交消息，再运行机械规则。
- `hooks/pre-push` → `stages/push/main.py`：读取 Git 提供的实际推送对象，核对 review ticket 并现场检查格式与密钥。
- `stages/<阶段>/rules/<规则名>/main.py`：每条规则独立目录和 Python 子进程，辅助脚本也放在该目录；同目录的 `meta.toml` 是规则元数据，缺项即报错（见「规则协议」）。

默认 commit 顺序：`whitespace` → `format` → `comment-form` → `template-layout`。
默认 push 顺序：`review-ticket` → `llm-review` → `format` → `secrets`；各仓在配置里按需选用。

任一规则返回非零立即停止，后续规则不运行。退出码：0 通过；1 违规；2 工具、配置或运行错误。规则崩溃返回其他非零也会被拒绝；以 1 退出却没有合法报告（如脚本崩溃）按 ERROR 处理并保留 traceback，不会当作成功。超时终止整个规则进程组。缺脚本、缺工具、未知配置、未知跳过规则均报错。

## 本地启用

在消费仓执行（不会自动安装，也不会改全局 Git 配置）：

```sh
git config --local core.hooksPath /absolute/path/to/bbtools-pub/tools/git-hooks/hooks
```

启用前检查已有 `core.hooksPath`，不要覆盖其他 hook 系统。普通 worktree 默认共享仓库配置。禁用时恢复启用前的值；原来未设置才用 `git config --local --unset core.hooksPath`。

仓根配置为 `.config/bbt-git-hooks.toml`，只写需要覆盖的键，见 [示例](core/config.example.toml)。配置和格式规则使用本地工作区文件。规则按配置数组顺序执行，不按目录排序；增加规则目录后还需加入对应数组。`scope.exclude` 作用于 C++ 格式/注释/模板路径，空白检查仍覆盖全部变更。

旧 `tools/precommit` 已由此工具替代，旧暂存树章不再使用。消费仓旧 `.config/bbt-precommit.toml` 不会自动读取，需要按新示例迁移；原 `scope.exclude` 可原样移入。未安装的 `tools/githooks/` 草稿不属于此入口。

## 跳过规则

直接调用入口：

```sh
python3 -I <pub>/tools/git-hooks/stages/commit/main.py --skip-rules format,comment-form
```

Git 自动提交时，把同样的指令写在 commit message 的独立一行：

```text
refactor(stack): 拆分栈池类型

--skip-rules comment-form
```

支持重复参数/多行，逗号或空格分隔规则名；`all` 跳过当前阶段所有规则。跳过会打印 `SKIP`，消息指令保留在提交历史中。`#` 注释和 scissors 线后的内容不作为指令。不是 Git 自身的参数，不能写 `git commit --skip-rules ...`。

commit 消息不会被 push hook 读取，不会顺带豁免推送检查。手动调 push 入口时也能使用 `--skip-rules`，但只影响该次手动调用；后续正常 `git push` 仍重新检查。Git 自身的 `--no-verify` 能绕过本地 hook，这不是服务端安全机制。

## 检查范围

commit 读取本次 index 生成的不可变 tree（兼容 `git commit --only <path>` 的临时 index），不把未暂存源码当作待提交源码。格式检查覆盖改动的整个 C/C++ 文件，注释检查只覆盖与新增/修改行相交的注释；未改的旧注释不拦。字符串中的 `//` 不是注释。它是词法检查，不是完整 C++ 解析器，不判断注释意图或模板语义。

合并提交对比 HEAD，**不再取两个父提交差异的交集**，避免漏掉对方分支带来的实际内容。删除文件不送给 formatter；新文件禁用旧 `impl/` 和 `*Impl.hpp` 模板路径。`format` 使用本地 clang-format 和 `.clang-format`，不自动安装或修改版本；工具版本仍由消费仓维护。

## 规则协议

每条规则目录必须有 `meta.toml`，键恰好是：`id`（与目录名一致）、`stage`（`commit` 或 `push`）、`kind`、`title`、`fix`（失败后下一步具体做什么，写给 agent）、`docs`（pub 仓库内的规范路径）。缺项、多余键、取值不符都在加载时报错。

`kind` 区分两类检查：`auto` 由 hook 在该阶段现场执行，结果以实跑为准；`attested` 不执行，只核对提交的证据是否齐全合格。

违规时规则退出 1，并在 stdout 输出一个 JSON 对象：`code`（`E-` 开头的大写错误码）、`problems`（非空字符串数组，每条带位置和原因）、可选 `fix`（覆盖 meta 里的默认做法）。规则用 `runner.report(code, problems, fix)` 或 `raise RuleFail(...)` 输出，由 runner 统一渲染：

```text
FAIL llm-review  [E-LLM-REVIEW-MISSING]  缺少基于 LLM 的代码审查证据 (attested)
  问题：<ticket 路径>: checks 里没有 id 为 llm-review 的检查项
  怎么办：先对 BASE..代码 commit 的完整改动做基于 LLM 的代码审查……
  规范（pub 仓库）：docs/30-review/README.md
  已通过：review-ticket    未通过：llm-review (attested)    未运行：format, secrets
```

新规则从 `stages/_template/` 复制到 `stages/<阶段>/rules/<id>/`，改 `meta.toml`，再把 id 加入配置数组。通过时退出 0；工具、配置或环境错误抛 `HookError`（退出 2）。目录中的脚本是受信任本地代码，不是沙箱，不要在规则里写源码、联网或启动脱离进程组的后台任务。

## push 门禁与 review ticket

push 检查的是即将发布的范围，不是当前 HEAD：已有远端 ref 取 `旧远端 commit..目标`（旧对象本地不可读则拒绝，不自动 fetch）；新分支取目标中不在该远程已有分支里的提交，找不到远程时按整个历史处理。多个 ref 任一不满足就终止 push；tag 解引用到 commit，指向非 commit 的 tag 拒绝；删除 ref 没有候选代码，打印 SKIP。

### ticket

review 完成后产出一份 JSON ticket，随仓库提交，路径 `.config/review-tickets/<YYYY-MM-DD>/<被审查 commit>.json`。ticket 里要写被审查的代码 commit 哈希，而提交 ticket 本身会产生新的哈希，所以 ticket 单独放在紧随其后的 commit 里；这个 commit 只能改 `.config/review-tickets/`，否则它自己就成了需要 ticket 的代码 commit。push 范围里只有 ticket 提交、没有代码提交时不再要求新的 ticket。

生成骨架（不会调用审查者，也不替你审查）：

```sh
python3 -I <pub>/tools/git-hooks/stages/push/rules/review-ticket/new.py --base <BASE> [--commit <SHA>]
```

骨架的 `result` 是 `pending`，并按配置里的 `attested` 规则预置 `checks`。审查者填写后，字段如下：

| 字段 | 要求 |
|---|---|
| `schema_version` | 固定 `1` |
| `date` | `YYYY-MM-DD`，与所在目录一致 |
| `commit` | 被审查的代码 commit，与文件名一致 |
| `base` | `commit` 的严格祖先；审查范围是 `base..commit` 的完整改动，不是只审最后一次提交 |
| `result` | `pass`、`fail` 或 `pending`；只有 `pass` 才继续校验，才允许 push |
| `reviewer`、`summary` | 非空：谁审的、结论与覆盖范围 |
| `checks[]` | 每项 `id`、`kind`、`status`（`pass` 才算通过）、`summary`、`evidence` |

### 规则

- `review-ticket`（auto）：核对上表字段、`commit` 与代码 commit 一致、`base` 是严格祖先；任何非 `pass` 的检查项都会列在错误里。
- `llm-review`（attested）：`checks` 里要有 `id` 为 `llm-review` 的项，`kind=attested`、`status=pass`、`summary` 非空，`evidence.reviewer` 与 `evidence.scope`（覆盖的范围）非空。hook 不调用模型，只核对这份证据。
- `format`（auto）：对推送范围内改动的 C/C++ 文件现场运行 clang-format，不信任 ticket。
- `secrets`（auto）：用正则扫描推送范围的新增行：私钥块、AWS access key、GitHub token，以及 `password`、`secret`、`token`、`api_key` 一类的赋值（值需同时含字母和数字，占位符、`${...}` 和含括号的值不拦）。报告不回显匹配内容。覆盖面有限，会漏报也会误报；确认是误报时在该行写 `bbt-secrets:allow`。需要更强的检测时接入 gitleaks。

### 边界

- 没有机械手段证明 review 真的做过：`llm-review` 只保证 ticket 格式合格、证据字段齐全，靠审查者自觉与各仓 AGENTS 约束。
- amend、rebase 会改变代码 commit 的哈希，旧 ticket 随之找不到，需对新哈希重新审查并生成 ticket。
- 新分支且找不到远程时，会要求整个历史里最新的代码 commit 有 ticket。
- Git 自身的 `--no-verify` 能绕过本地 hook；本工具不做服务端校验。

## 验证

```sh
python3 -m unittest discover -s tools/git-hooks/tests -v
```

测试只在临时目录创建自有 Git 仓库和 bare remote，不操作实际远端。覆盖真实 commit/push、跳过、首错停止、超时、index 隔离、特殊文件名、规则协议与 meta 校验、ticket 缺失/未填/失败/过期、llm-review 证据、现场格式与密钥检查。
