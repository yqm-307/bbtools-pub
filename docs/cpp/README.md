# C++ 规范入口（bbtools 家族特有）

本目录只留 bbtools 家族在 C++ 上的特有约定；通用 C++ 规范（写法、文档、格式）位于 `third-party/bbt-agent-toolkit/standards/cpp/`（submodule，已固定到 toolkit `main` 已合入的提交）。

## 阅读路径

| 内容 | 位置 |
|---|---|
| C++ 通用写法（RAII、值语义、智能指针、`volatile`/`atomic`、`noexcept`、头文件公共边界、声明与实现拆分、运算符重载与宏、易用接口与谨慎抽象、回调与资源） | [C++ 写法](../../third-party/bbt-agent-toolkit/standards/cpp/style.md) |
| C++ Doxygen 通用写法 | [文档注释](../../third-party/bbt-agent-toolkit/standards/cpp/documentation.md) |
| C++ 机械格式（`.clang-format`） | [clang-format](../../third-party/bbt-agent-toolkit/standards/cpp/format.md) |

以下是 bbtools 家族特有约定：

| 内容 | 位置 |
|---|---|
| 命名与类型取值（`PascalCase`、`m_`、`Ptr/SPtr/UPtr`、`TupleErr`、命名空间层数） | [命名与类型](naming-and-types.md) |
| 头文件与公共边界（`.hpp`/`.cc`、`__TXxx.hpp`、类声明布局、宏 `bbt_co_async`/`BBTATTR_*`、`net::Buffer` 示例） | [头文件与类布局](class-and-headers.md) |
| 协程语法糖（`bbt_co_async`/`bbt_co_await`、`SyntaxMacro.hpp` 手册、已知缺口） | [协程语法糖](coroutine.md) |
| 注释与 Doxygen 排版形态（家族专有示例） | [注释与排版](comments.md) |
| 项目格式配置、CMake 目标与 CTest 标签 | [构建与测试](build-and-test.md) |

示例：`examples/ClassLayout.hpp`、`examples/ClassLayout.cc`、`examples/FunctionFamily.hpp`。

正反例保留；同一规则只留一个完整正文，其他地方用短句链接上表，不复制正文。
