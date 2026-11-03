# bbtools 共用开发规范

把共同原则与场景职责分开：**先读原则，再选当前场景；只有触发专项条件才继续展开。**这些是可供人和工具阅读的普通文档，不创建额外角色或自动加载全部文件。

## 从这里开始

[共用原则](docs/principles.md) 定义优先级与不可破坏的约束；已读且版本未变就复用。再选择本次任务：

| 当前在做什么 | 职责入口 | 按需专项，由入口说明触发条件 |
|---|---|---|
| 设计接口、边界和机制 | [design.md](docs/design.md) | 不预建无需求的专项 |
| 编写或修改实现 | [coding.md](docs/coding.md) | [C++](docs/coding-cpp.md)、[文档与注释](docs/coding-documentation.md) |
| 评审代码、设计或文档 | [review.md](docs/review.md) | [生命周期与扩展](docs/review-lifecycle.md) |
| 设计行为与回归用例 | [testcase.md](docs/testcase.md) | [并发与生命周期](docs/testcase-concurrency.md) |

例如：普通 C++ 修改读原则、coding 和 coding-cpp；涉及异步关闭的评审再展开 review-lifecycle。纯文档评审不因同仓有网络模块而加载并发专项；只跑既定测试也不重做用例设计。

## 接入与维护

- 消费仓引用已审查的固定提交及对应入口，保留本仓明确差异；这些链接不承诺自动抓取或同步远端。
- 原则回答“为什么与什么不能破坏”，职责回答“本场景要负责什么”，专项只补触发后的要求。同一规则只在一处写全，其他位置只引用，不循环要求读完全部文件。
- 只有真实场景和已有内容值得独立阅读时才新增 `coding-*.md`、`review-*.md` 或 `testcase-*.md`，不预建空分类。
- 来源依据留在私有证据中；公开内容去除敏感信息。当前仓库的明确决策优先，不因通用规范迁移夹带无关修改。

旧 [conventions.md](docs/conventions.md) 保留为兼容入口，不再维护另一份正文。
