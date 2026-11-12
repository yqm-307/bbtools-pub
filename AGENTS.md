# AGENTS.md — bbtools-pub

## 定位

本仓是 bbtools 各仓共用的开发规范与本地工程工具：设计、编码、Review、用例设计、长程任务工作流的判断规范，以及复杂度打分器和本地 Git hooks。不承载任何仓库私有规则、业务契约或运行时代码。

各消费仓（`bbtools-coroutine`、`bbtools-infra`、`bbt-framework`）通过 submodule 或并列检出引用本仓；与消费仓自己的 `AGENTS.md` 或 `docs/` 冲突时以消费仓为准。

## 真源入口（按任务读取，不全量预载）

| 任务 | 入口 |
|---|---|
| 改规范正文、新增或调整专项 | [README.md](README.md) 的阅读路径与「维护规则」，再进入对应职责目录 |
| 改本地 Git hooks | [tools/git-hooks/README.md](tools/git-hooks/README.md) |
| 改复杂度打分器 | [tools/complexity/README.md](tools/complexity/README.md) |
| 开工与测试前核对依赖、分支、是否 latest | [README.md](README.md)「开工与测试前的核对」 |

## 本仓特有规则

- 规范写给所有消费仓：表达保持抽象通用，不绑定某个消费仓；技术专项（如 C++）放进对应职责目录；容易模糊的规则补正例和反例。仓库私有规则写回该仓自己的 `AGENTS.md`。
- 同一规则只留一个完整正文，其他地方用短句指向它；新增专项前先确认已有文件无法承载。改目录或文件名后，同步 `README.md` 的路径，并检查链接都存在、引用方向只向下（见 README「先看引用方向」）。
- 消费仓无论用 submodule 还是并列检出，都只能引用本仓 `main` 已合入的提交（submodule 固定到该提交）；未合入的改动和工作树未提交内容不能被引用，也不能当作规范证据。
- 工具改动的验证：改 hooks 跑 `python3 -m unittest discover -s tools/git-hooks/tests -v`；改复杂度打分器跑 `python -m unittest discover -s tools/complexity/tests -v`（环境见其 README）。hooks 测试只在临时目录建自己的仓库和 bare remote，complexity 测试只用临时源码、报告和配置文件，都不碰真实远端。工具未接入 CI 前，不把本地结果表述为 CI 结果。
- 纯文档改动的最低验证：`git diff --check` 加链接存在性检查。「读过规范」不算构建、测试或 Review 通过。

## 门禁

- 须先获用户授权：commit、push、开 PR、付费调用、破坏性操作、新依赖、CI/发布变更、删除或重命名公开的规范路径与工具入口（可能已被消费仓引用）、改变公共规则的适用范围。任务会产生改动时，开工时一次问清是否授权 commit/push/开 PR，授权覆盖整段任务；未授权则停在 commit 前，交付改动与验证结果。
- 提交标题 `<type>(<scope>): <简洁中文说明>`，单次提交不混无关变更；Author 固定为用户本人 `yqm-307`：用本机 git 配置（`user.name=yqm-307`）直接提交，不加 `--author`，不使用 agent 身份。不直推 `main`、不自行合并。
- 受保护文件（含本文件）和改变规则含义的改动须没参与编写的人独立审查；其余按风险自审并附验证结果。
- 只改获授权范围，保留他人已有改动；远端写入后回读确认目标对象。
