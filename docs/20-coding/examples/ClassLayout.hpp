/**
 * @file ClassLayout.hpp
 * @brief 类布局示例：构造与析构、公开接口、私有方法、私有数据分别成块。
 */
#pragma once

#include <cstddef>
#include <functional>
#include <vector>

/**
 * @brief 演示类声明和注释层次的进度读取器，不代表完整的数据读取协议。
 */
class Reader {
public:
    Reader() {}

    ~Reader() {}

public:
    /**
     * @brief 当前已读取的字节数。
     *
     * @return 已读取的字节数。
     */
    std::size_t Progress() const { return m_progress; }

    /**
     * @brief 累计进度，并在启用通知时调用进度回调。
     *
     * @param n 本次新增的字节数。
     * @pre 累计结果不超过 std::size_t 的表示范围。
     */
    void Advance(std::size_t n);

private:
    /**
     * @brief 内部空钩子，用于展示私有短函数的紧凑写法。
     */
    void _HookOnData() {}

    /**
     * @brief 更新内部计数并分发进度通知。
     *
     * @param n 本次新增的字节数。
     */
    void _AdvanceProgress(std::size_t n);

private:
    std::size_t m_progress{0};
    bool m_notify{true};                           // 关闭后仍累计进度，但不发送通知。
    std::function<void(std::size_t)> m_onProgress; // 在 Advance 的调用线程同步执行。

    /**
     * 读取器独占的缓冲存储。借用其中元素不延长存储寿命；
     * 扩容或销毁后，原有指针、引用和迭代器可能失效。
     * 当前示例只展示复杂成员的说明位置，不实现缓冲读写。
     */
    std::vector<char> m_data;
};
