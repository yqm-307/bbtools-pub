# 推送检查与审查凭据

## push 门禁与 review ticket

push 检查的是即将发布的范围，不是当前 HEAD：已有远端 ref 取 `旧远端 commit..目标`（旧对象本地不可读则拒绝，不自动 fetch）；新分支取目标中不在该远程已有分支里的提交，找不到远程时按整个历史处理。多个 ref 任一不满足就终止 push；tag 解引用到 commit，指向非 commit 的 tag 拒绝；删除 ref 没有候选代码，打印 SKIP。

### ticket

review 完成后产出一份 JSON ticket，随仓库提交，路径 `.config/review-tickets/<YYYY-MM-DD>/<被审查 commit>.json`。ticket 里要写被审查的代码 commit 哈希，而提交 ticket 本身会产生新的哈希，所以 ticket 单独放在紧随其后的 commit 里；这个 commit 只能改 `.config/review-tickets/`，否则它自己就成了需要 ticket 的代码 commit。push 范围里只有 ticket 提交、没有代码提交时不再要求新的 ticket。

生成骨架（不会调用审查者，也不替你审查）：

```sh
python3 -I <pub>/tools/lint/rules/review-ticket/new.py --base <BASE> [--commit <SHA>]
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

