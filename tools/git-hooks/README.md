# 本地 Git hooks

Git 入口保持不变，规则已统一放入 `tools/lint/rules/`。Python 3.11+ 标准库，Linux/WSL；不联网、不调用模型、不改源码，不替代 CI、分支保护或发布审批。

- `hooks/commit-msg` → `stages/commit/main.py`：读取提交消息与 index 快照。
- `hooks/pre-push` → `stages/push/main.py`：读取 Git 提供的实际推送对象。
- [lint 机制与扩展](../lint/README.md)：目录、meta、统一配置、规则范围、告警/阻断、超时与退出码的唯一说明。
- [推送与 review ticket](../lint/rules/review-ticket/README.md)：推送范围、凭据字段、生成与核验边界。

## 本地启用

先检查消费仓已有 `core.hooksPath`，不要覆盖其他 hook 系统。需要启用时在消费仓执行：

```sh
git config --local core.hooksPath /absolute/path/to/bbtools-pub/tools/git-hooks/hooks
```

不会自动安装或改全局配置。普通 worktree 默认共享仓库配置；禁用时恢复原值，原来未设置才执行 `git config --local --unset core.hooksPath`。

## 配置兼容

原 `.config/bbt-git-hooks.toml`（`schema_version = 1`）无需修改；`commit.rules`、`push.rules`、`scope.exclude`、`format.binary` 与默认规则顺序继续有效。原配置缺省 commit 仍为 whitespace → format → comment-form → template-layout；push 仍为 review-ticket → llm-review → format → secrets，全部默认阻断。

新增可组合 C++ 检查、每规则阈值与告警级别使用 [lint schema 2](../lint/README.md#一仓一份配置)，各仓只保留一份配置；工具不会自动迁移或开启新增规则。旧 `.config/bbt-precommit.toml` 不自动读取。

## 跳过规则

直接调用：

```sh
python3 -I <pub>/tools/git-hooks/stages/commit/main.py --skip-rules format,comment-form
```

Git 自动提交时，在 commit message 独立一行写 `--skip-rules comment-form`。支持重复参数、多行、逗号或空格分隔。`all` 选中该阶段全部规则。默认允许跳过选中的规则并打印 `SKIP`。配置 `enforce_blocks = true` 后，只要选中任何阻断项，commit 或 pre-push 就会拒绝这次操作。提交消息里的指令保留在历史中。`#` 注释和 scissors 线后的内容不作为指令。不能写 `git commit --skip-rules ...`。

commit 消息不会被 push hook 读取；手动 push 入口的 `--skip-rules` 只影响该次调用。Git 的 `--no-verify` 可以绕过本地 hook，这不是服务端安全机制。

## 本地回归

```sh
python3 -m unittest discover -s tools/git-hooks/tests -v
```

测试只在临时目录创建自有仓与本地 bare remote，不操作真实远端。本地结果不等于 CI 结果。
