# C++ 命名与类型约定（bbtools 家族）

**所属**：pub `docs/cpp/`，仅描述 bbtools 家族在 C++ 上的取值；通用 C++ 写法（RAII、值语义、智能指针、`volatile` 与原子、`noexcept`、头文件公共边界、声明与实现拆分的通用判断、运算符重载与宏的边界、易用接口与谨慎抽象、回调与资源）见 `third-party/bbt-agent-toolkit/standards/cpp/style.md`，本文只写覆盖或补充。

## 1 语言基线与依赖

- 以仓库真实构建配置的 C++17 为基线，不静默提升标准。标准库有成熟能力时先复用；不足时积极使用项目已选、成熟且适合的 Boost 组件，不因“不是 std”重复造轮子。新增依赖还要评估许可、安全、平台、维护、体积和退出路径。

## 2 命名取值

| 项 | 取值 |
|---|---|
| 类型、方法、函数 | `PascalCase` |
| class 数据成员 | `m_` 加 `snake_case`（如 `m_run_status`） |
| 非公开方法 | 同样用 `PascalCase`，可见性由 `private` 表达；不加前导下划线（下划线紧接大写的名字被 C++ 保留，见 `third-party/bbt-agent-toolkit/standards/general/naming.md`）。存量 `_Xxx` 不顺手改名，改名先核消费者与兼容 |
| 指针别名 | `Ptr`/`SPtr`/`UPtr`，分别对应非拥有裸指针、共享和唯一持有 |
| 命名空间 | 按模块组织，最多三层；模板服务于类型安全和稳定复用，避免技巧性、难诊断的元编程 |
| 纯虚接口类 | `I` 前缀，放 `interface/`（如 `ICoLock`、`ICoroutine`）；接口文件只含纯虚函数与必要类型 |
| 变量与参数 | `snake_case`；单位和布尔含义写进名字，如 `timeout_ms` |
| struct 纯数据字段 | 不加前缀 |
| 静态成员 | `s_` 前缀 |
| 常量 | 新的文件作用域常量用 `kName`；局部 `const` 变量（如 `const int retry_count`）不必用 `k` |
| 枚举值 | 跟所在文件既有风格（如 `CO_RUNNING`、`COMUTEX_FREE`）；新的独立模块可用 `kName`，同一文件不混用 |

函数名的动词约定（动词+对象、简单词、不口语）见 `third-party/bbt-agent-toolkit/standards/general/naming.md` 的「函数命名」一节；可选的机器扫描用 `tools/lint` 的 `func-naming` 规则（默认关闭）。

存量风格与新代码冲突时，不借一次改动重命名全仓。

## 3 错误返回

- 类型安全的结果、状态或异常表达，沿用模块已公开的返回码契约；只有确实保证不抛时才写 `noexcept`。
- 可失败操作建议同时提供出参版与返回值版，行为一致：

```cpp
errcode TryRead(Buffer& out);
tuple<Buffer, errcode> TryRead();
```

- 带选项的 `Read` 同理；返回值版直接调用出参版实现即可。错误码在 `tuple` 中永远放最后，coroutine 仓用 `TupleErr<T...>`（`tuple<T..., ErrOpt>`）；`ErrTuple`（错误在前）属存量，新接口不沿用。

正例：一个请求对象被一个明确 owner 持有，异步任务只借用到完成事件；若必须共享，说明共享原因和最后释放责任。

反例：用 `shared_ptr` 掩盖谁该结束任务的问题；把错误码放在 `tuple` 非末尾位置。
