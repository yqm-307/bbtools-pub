# C++ 头文件与类布局约定（bbtools 家族）

**所属**：pub `docs/cpp/`，bbtools 家族特有取值；头文件与公共边界的通用判断见 `third-party/bbt-agent-toolkit/standards/cpp/style.md`，本文只写覆盖或补充。

## 1 头文件与公共边界

- 公开类型有可定位的 `.hpp`；内聚小类型可以共处，不因类数机械拆文件。存在非内联实现时配 `.cc`，接口与命名空间、目录保持一致。
- 公共边界（不泄漏内部类型、文档承诺与实现一致）按通用规范，见 `third-party/bbt-agent-toolkit/standards/cpp/style.md`「公共边界与易用接口」。
- 头文件使用 `#pragma once`，include 按对应头、标准库、项目公共头、子模块头组织；避免依赖传递 include 让调用者“碰巧能编译”。
- 声明与实现拆分的家族取值：非模板的非平凡实现放 `.cc`；模板实现放同目录的 `__TXxx.hpp`，由主头末尾包含；复杂实现保持类体外定义，让类体可当接口目录读。何时 header-only、何时保留编译单元按通用规范。
- 模板实现示例：`examples/FunctionFamily.hpp`（同族函数的 Doxygen 分组，与 `comments.md` §2 对应）；类布局示例：`examples/ClassLayout.hpp` 与 `examples/ClassLayout.cc`（两文件可配对编译）。

## 2 类的声明布局

类体按三个块排列，块之间空一行；每个块内按语义、功能聚合，功能组之间空一行。目标是有条理、分块适当（不密集、不离散）。

1. `public:` 写给使用者看的接口。先放构造、析构、拷贝、移动；再放功能接口，按功能聚合，一族函数共用一个注释（见 `comments.md` §2）。构造需要隐藏时不放这里。
2. `private:` 内部功能接口，如 `HookXxx`。需要隐藏的构造、析构也放这里。
3. `private:` 成员变量单独一个块，按功能聚合，组间空一行，例如进度控制相关的 `progress`、`data` 放一起，与 `is_flag` 之类的空一行隔开。

```cpp
class T {
public:
    T() {}

    /**
     * @brief 使用初始容量构造对象。
     *
     * @param capacity 初始容量。
     */
    explicit T(size_t capacity);

    ~T() {}

public:
    int Progress() const { return m_progress; }
    void Run();

private:
    void HookXxx();

private:
    size_t m_progress{0};

    /* 关闭后仍保留当前进度。 */
    bool m_is_flag{false};

    /*
     * 复杂状态的所有权和失效条件写在成员上方，避免把重要约束压缩到行尾。
     */
    ProgressData m_data;
};
```

## 3 接口易用性的家族示例

易用接口、谨慎抽象、运算符重载与宏的通用边界见 `third-party/bbt-agent-toolkit/standards/cpp/style.md`「公共边界与易用接口」「运算符与宏的边界」。本仓补充：

- 运算符重载的家族示例：`net::Buffer` 用 `<<`、`>>` 表达写入、读出。
- 宏的家族取值：语法糖与声明元数据宏用 `bbt_` / `BBTATTR_` 等模块前缀，如 `bbt_co_async(...)`、`BBTATTR_*`；公开头里出现的宏必须在文档中说明展开含义。
- 文档化的例外：协程挂起点语法糖 `bbt_co_await` 隐藏挂起控制流，是文档化的例外，用法见 `coroutine.md`；不推广到其他宏。
