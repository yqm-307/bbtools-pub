# 协程语法糖优先（bbtools 家族）

**所属**：pub `docs/cpp/`，bbtools 家族特有取值；协程相关的通用写法见 `third-party/bbt-agent-toolkit/standards/cpp/style.md`，本文只写 bbtools 家族的语法糖约定。

## 1 使用语法糖，不直接调内部接口

库为常见协程意图提供语法糖（启动协程、休眠、让出、defer、等 fd 事件、创建同步原语、`bbt_co_async`/`bbt_co_await`）。同一个意图有语法糖就用语法糖，不直接调用调度器或协程内部接口：读者认的是意图名，不用从 TLS 指针和调度器调用里还原“这是在启动协程”。语法糖只是稳定 API 的薄封装，语义与底层调用一致。

**入口与真源**：`#include <bbt/coroutine/coroutine.hpp>` 是唯一入口，它的文件头指向使用说明；语法糖的意图、用法、返回值、异常、生命期和已知缺口写在 `syntax/SyntaxMacro.hpp` 文件头及各宏的注释里，把它当 API 手册读，不需要读内部实现。本规范不复制那份手册，也不另列对照表，避免两处说法漂移。

**缺能力时补语法糖，不绕内部**：语法糖表达不了所需语义时（例：显式栈大小、指定目标 Processer）：

1. 先在 `SyntaxMacro.hpp` 的“已知缺口”里确认这是已登记的缺口；
2. 缺口确实阻塞当前工作时，提议给语法糖补一个薄封装，同步更新那份手册和对应测试；
3. 补之前的临时直接调用，必须在调用处写明原因，并指向对应的缺口条目。

语法糖的改动按公共接口对待：保持“意图 → 用法”的形式。涉及异步返回类型或执行入口的语义迁移属于破坏性 API 变更，必须同步迁移声明、实现、调用方和测试。

使用时的陷阱同样以那份手册为准（例如 `bbtco_yield` 自带结尾分号，不能写在无花括号的 `if ... else` 里）。写注释或文档引用宏的行为前，先核对头文件当前内容，不凭印象。

正例：`bbtco_noexcept(&ok) [lease]() { ... };` 一眼读出“启动协程并检查注册结果”；需要 128 KiB 栈时直接调用带栈大小的重载，旁边写“语法糖暂无栈大小入口，见已知缺口”。

反例：同一个仓里同一种意图一处写 `bbtco`，一处写 `g_scheduler->RegistCoroutineTask(...)`，又没有说明原因，读者无法判断两种写法是否有语义差别；或者为了避开缺口去读 Scheduler 内部再自己拼一套。

### 调用点排版

启动协程或注册事件读作 **启动前缀 + 空格 + 完整的 C++ lambda**。前缀自己的实参不拆开：`bbtco_noexcept(&ok) [state]() { … };`、`bbtco_desc("read") [fd]() { … };`、`bbtco_ev_r(fd) [state](int fd, short ev) { … };`（含协程池变体）。从 `[` 起按 lambda 而不是普通函数定义排版；无参也显式写 `()`，无参空体写 `bbtco [](){};`。真实参数、`mutable`、返回类型及捕获方式保持原意。普通 lambda 不强制补 `()`。`bbtco_ref`、`bbtco_defer` 的宏已提供捕获和参数，调用处只跟代码块。

表达式前留一个空格：`bbt_co_await Read()`、`bbt_co_fire op`、`bbt_co_return -1`；已有的括号属于操作数，写 `bbt_co_return (a + b)`。不要为了排版额外加括号。函数式或类型式写法如 `bbt_co_return_ref(value)`、`bbt_co_bind(f)`、`bbt_co_async(T)`、`bbtco_wait_for(...)`、`bbtco_sleep(ms)`、`bbtco_make_*()` 不加这一格；`bbtco_yield;`、`bbt_co_return_void;` 的分号前也不加。

## 2 用确定性机制约束异步调用

异步语义属于 API 契约，不能只靠注释、命名或调用者自觉维持。凡是可能挂起当前协程的操作，公开返回类型必须携带异步操作标记，并且只能通过与该类型匹配的 `await` 或 `fire` 入口执行。

- `bbt_co_await expr;` 在当前协程中执行操作并等待完成。
- `bbt_co_fire expr;` 将操作提交给 detached 协程，不等待最终结果。
- 普通返回值没有对应的 helper 重载，`bbt_co_await ordinary();` 必须在编译期失败。
- 异步操作对象不提供业务可调用的执行运算符。普通调用只构造操作描述，不能绕过 `await` 或 `fire` 执行函数体。
- `fire` 只放弃最终完成结果，不放弃提交失败和后台错误的处理责任。操作之间有顺序依赖时必须使用 `await`。

实现优先使用返回类型、模板匹配、偏特化和运算符重载建立硬边界。`[[nodiscard]]`、`-Werror=unused-result` 与静态检查用于补充“操作被暂存后遗失”等 C++ 类型系统无法单独判断的路径。新增语法糖必须同步提供正例、负例和可运行的编译期断言。

这个原则适用于协程库、infra adapter、framework 控制面及其他返回可能挂起操作的模块。下游 API 不得把 async 操作降级成普通返回值，也不得用注释重新解释成同步调用。

## 3 用 lint 固化语法糖边界

严格仓库可以在[消费仓 lint 配置](../../tools/lint/README.md#一仓一份配置)中启用 `coroutine-sugar`，把规则加入 `scan.rules`、`commit.rules` 和 `push.rules`。规则会检查直接调用 `RegistCoroutineTask`、`Hook_Sleep`、`YieldAndPushGCoQueue`、`YieldUntilFd*`、同步原语工厂、协程事件工厂及 async 内部 helper，并要求改用对应的 `bbtco_*` 或 `bbt_co_*` 入口。它只按源码词法匹配，不解析类型，也不自动修复；是否接入 Git hook 由消费仓决定。扫描退出 `2` 表示未完成，不是通过。

特殊测试、库内部实现和已登记的语法糖缺口可以在调用处跳过当前检测。跳过必须写出原因，支持下面两种形式：

```cpp
// bbt-lint: ignore-next-line coroutine-sugar -- explicit stack size is required here
g_scheduler->RegistCoroutineTask(stack_size, callback);

detail::Hook_Sleep(1); // bbt-lint: ignore coroutine-sugar -- verifies the raw hook
```

同一行可用 `bbt-lint: ignore coroutine-sugar`；规则也接受 `NOLINT(coroutine-sugar)` 和 `NOLINTNEXTLINE(coroutine-sugar)`。这些标记只针对 `coroutine-sugar`，不关闭其他规则。
