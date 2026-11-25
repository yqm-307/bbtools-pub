# 协程语法糖优先（bbtools 家族）

**所属**：pub `docs/cpp/`，bbtools 家族特有取值；协程相关的通用写法见 `third-party/bbt-agent-toolkit/standards/cpp/style.md`，本文只写 bbtools 家族的语法糖约定。

## 1 使用语法糖，不直接调内部接口

库为常见协程意图提供语法糖（启动协程、休眠、让出、defer、等 fd 事件、创建同步原语、`bbt_co_async`/`bbt_co_await`）。同一个意图有语法糖就用语法糖，不直接调用调度器或协程内部接口：读者认的是意图名，不用从 TLS 指针和调度器调用里还原“这是在启动协程”。语法糖只是稳定 API 的薄封装，语义与底层调用一致。

**入口与真源**：`#include <bbt/coroutine/coroutine.hpp>` 是唯一入口，它的文件头指向使用说明；语法糖的意图、用法、返回值、异常、生命期和已知缺口写在 `syntax/SyntaxMacro.hpp` 文件头及各宏的注释里，把它当 API 手册读，不需要读内部实现。本规范不复制那份手册，也不另列对照表，避免两处说法漂移。

**缺能力时补语法糖，不绕内部**：语法糖表达不了所需语义时（例：显式栈大小、指定目标 Processer）：

1. 先在 `SyntaxMacro.hpp` 的“已知缺口”里确认这是已登记的缺口；
2. 缺口确实阻塞当前工作时，提议给语法糖补一个薄封装，同步更新那份手册和对应测试；
3. 补之前的临时直接调用，必须在调用处写明原因，并指向对应的缺口条目。

语法糖的改动按公共接口对待：保持“意图 → 用法”的形式，不改变已有宏的行为，不新增只为单个调用点服务的宏。

使用时的陷阱同样以那份手册为准（例如 `bbtco_yield` 自带结尾分号，不能写在无花括号的 `if ... else` 里）。写注释或文档引用宏的行为前，先核对头文件当前内容，不凭印象。

正例：`bbtco_noexcept(&ok) [lease] { ... };` 一眼读出“启动协程并检查注册结果”；需要 128 KiB 栈时直接调用带栈大小的重载，旁边写“语法糖暂无栈大小入口，见已知缺口”。

反例：同一个仓里同一种意图一处写 `bbtco`，一处写 `g_scheduler->RegistCoroutineTask(...)`，又没有说明原因，读者无法判断两种写法是否有语义差别；或者为了避开缺口去读 Scheduler 内部再自己拼一套。

## 2 检查低层调用

在[消费仓 lint 配置](../../tools/lint/README.md#一仓一份配置)的 `scan.rules` 中显式加入 `coroutine-sugar`，即可扫描调度、挂起、同步原语工厂和 async 内部 helper 的直接使用候选。它只按源码词法匹配，不解析类型，也不自动修复；是否接入 Git hook 由消费仓决定。扫描退出 `2` 表示未完成，不是通过。

验证底层接口的用例、协程库内部或已知语法糖缺口，可以在调用处标注例外；说明为何仍需直接调用。例如：

```cpp
// bbt-lint: ignore-next-line coroutine-sugar -- explicit stack size is required here
g_scheduler->RegistCoroutineTask(stack_size, callback);
```

同一行可用 `bbt-lint: ignore coroutine-sugar`；也识别 `NOLINT(coroutine-sugar)` 和 `NOLINTNEXTLINE(coroutine-sugar)`。这些标记只针对该规则。
