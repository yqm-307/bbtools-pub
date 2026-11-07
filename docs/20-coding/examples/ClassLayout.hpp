#pragma once

// 伪代码示例：类的声明布局与 Doxygen 排版。不参与编译，规则见 cpp.md §3.1、documentation.md §6。
// 声明与实现严格分离：类体只放声明，getter 的函数体见 ClassLayout.cc。

/**
 * @brief 带进度的数据读取器。
 */
class Reader {
    // 第一块：public，写给使用者看的接口

public:
    // 构造、析构、拷贝、移动放最前
    /**
     * @brief 构造示例读取器。
     */
    Reader();

    /**
     * @brief 移动构造示例读取器。
     *
     * @param other 被移动的读取器。
     */
    Reader(Reader&& other);

    /**
     * @brief 禁用复制构造。
     *
     * @param other 原读取器；本类型不支持复制。
     */
    Reader(const Reader& other) = delete;

    /**
     * @brief 销毁示例读取器。
     */
    ~Reader();

    /**
     * @name Read 系
     * @brief 读取已到达的数据，提供多种输出形态。
     *
     * 共享语义：失败时不写输出、不消费数据；成功返回前数据已移交。
     * @{
     */
    void Read(char* out, int size);  ///< @param out 输出区 @param size 容量
    void Read(std::string& out);     ///< @param out 追加到末尾
    void Read(Buffer& out);          ///< @param out 目标缓冲
    size_t Read();                   ///< @return 丢弃的字节数
    std::string ReadNByte(size_t n); ///< @param n 字节数 @return 不足 n 时为已有部分
    /** @} */

    // 另一组功能：进度观察，与 Read 系空一行
    /**
     * @brief 当前已读取的字节数。
     *
     * @return 已读取的字节数。
     */
    size_t Progress() const;

    /**
     * @brief 是否已读完。
     *
     * @return 已读完时为 true，否则为 false。
     */
    bool IsDone() const;

    // 第二块：private，内部功能接口

private:
    // 构造析构需要隐藏时放这里，例如：Reader(Token);
    void _HookOnData();
    void _AdvanceProgress(size_t n);

    // 第三块：private，成员变量单独一块，按功能聚合，组间空一行

private:
    // 进度控制
    size_t m_progress;
    ProgressData m_data;

    // 状态标志
    bool m_isDone;
};
