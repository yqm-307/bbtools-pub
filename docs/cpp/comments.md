# C++ 注释与 Doxygen 排版约定（bbtools 家族）

**所属**：pub `docs/cpp/`，bbtools 家族特有取值；注释内容的通用规则见 `third-party/bbt-agent-toolkit/standards/general/documentation.md`，Doxygen 通用写法见 `third-party/bbt-agent-toolkit/standards/cpp/documentation.md`，本文只写 pub 家族的排版与示例。

## 1 写当前契约和必要原因

- 中文为主，术语、API、类型和标识符保持原样；assert、异常和控制台诊断使用英文，业务 payload 不为了语言统一而翻译。
- C++ 公开类、函数和文件职责用多行 `/** */` 块写 `@brief`，形态见 §2。
- 哪些声明要注释、写什么不写什么（不复述、不写 Issue 编号与历史 patch、约束不能为短而删）及其正反例，见 toolkit [通用文档规范](../../third-party/bbt-agent-toolkit/standards/general/documentation.md) 与 [P7](../../third-party/bbt-agent-toolkit/standards/general/principles.md#p7)。

## 2 公开头 Doxygen 排版

- 有调用者需要知道的公开成员函数用 `/** */` 块：首行 `@brief 摘要`，续行与摘要对齐；空一行 ` *` 后依次写 `@param`、`@return`；无参数无返回值只写 `@brief`。默认构造、默认析构和没有特殊约束的空函数可以不写注释。带参数的构造函数按普通接口写清每个参数及其所有权、寿命或前置条件。成员声明之间空一行。
- 一族函数（同名重载或同一类能力）共用一个 `@name X 系` 分组块，用 `@{`/`@}` 包住；`@brief` 与正文写这一族共享的语义。
- 组内每个有文档价值的成员函数仍要被文档化：每个成员函数上方各放一个短 `/** */` 块，只写与同族不同的 `@param`/`@return`，成员之间按 §3 空一行。没有特殊语义的默认构造、析构和空函数不为凑齐警告而补空注释。示例见 `examples/FunctionFamily.hpp`，已用 doxygen 1.15、`WARN_IF_UNDOCUMENTED`、`WARN_NO_PARAMDOC` 验证零警告。

## 3 注释形态

- 变量、常量与成员变量（包括公开字段）只注释读者需要知道而声明未表达的信息。简短说明写在声明上方单行 `/* 注释内容 */`，一个短句说不清的约束用普通多行 `/* ... */`；不写行尾注释。普通 `/* */` 不进入 Doxygen，这是有意保留源码旁说明、不逐字段生成 API 文档的取舍。特殊值、顺序或借用寿命等约束仍须留在源码中，不为消除文档警告改成空泛的 `@brief`。
- 函数、构造函数等接口以及 class/struct 类型头的注释保持原规则，不属于上述变量规则。其多行块使用 `/** */`：`/**` 独占一行，正文每行以 ` * ` 开头，` */` 独占一行。不用 `///`、单行 `/** ... */` 或行尾 `///<`。
- 注释块写在它说明的代码上方，紧贴那段代码；整组（注释块加它说明的代码）和前后代码各空一行。函数体或 `{` 开头的第一个注释块，与 `{` 之间也空一行。
- 函数体和控制流语句的行尾注释移到所说明的代码上方。被注释的语句是无花括号 `if`/`else`/`for`/`while` 的执行体时，注释放到控制头上方，不插在控制头和语句之间。
- 例外：文件第一行的 `@file` 块上方无代码，不空行；`private:` 等访问说明符后不能空行（`.clang-format` 设了 `EmptyLineAfterAccessModifier: Never`，格式门禁会删掉）；命名空间结尾只写 `}`，不写 `// namespace ...`。
- 工具或法律必需的原文保持原样，不改写成 `/** */`：`// clang-format off/on`、`NOLINT`、许可证原文、第三方头原文。
- 除上述变量说明外，实现文件里也用 `/**`：各仓 Doxygen 只扫描头文件、不提取私有成员，实现文件的注释不进文档。头文件函数体内（如模板实现头）的 `/**` 块会被 Doxygen 并入该函数的公开文档，消费仓 Doxyfile 需设 `HIDE_IN_BODY_DOCS = YES`。

正例：

```cpp
void StackPool::ReleaseOneIdle()
{

    /*
     * 逐个在锁内摘空闲并更新计数，解锁后销毁再继续：
     * 不为回收额外分配收集 vector，避免清理路径再分配失败。
     */
    ItemType* item = TakeIdleLocked();

    /**
     * 锁外 delete + Profiler 事件。
     */
    if (item != nullptr)
        FreeItem(item);
}
```

变量正例：

```cpp
/* 0 表示不限制。 */
std::size_t limit{0};

/* 按插入顺序保留；借用的元素须活到本次发送结束。 */
std::vector<View> entries;

std::string payload;
```

变量反例：`int limit; // 0 表示不限制`；给 `payload` 写三行“载荷”注释；删除 `entries` 的顺序和借用约束。函数与类型注释仍按 §2，不套用单行变量说明。

反例：`FreeItem(item); // 锁外销毁`、`size_t idle{0}; ///< 空闲数`、把默认构造和析构各写一段空泛 `@brief`、单行 `/** @brief 当前数量。 */`，以及注释块和上一段代码之间不空行。
