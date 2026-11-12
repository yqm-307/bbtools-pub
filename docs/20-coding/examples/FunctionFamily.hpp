/**
 * @file FunctionFamily.hpp
 * @brief 一族函数文档格式示例。
 */
#pragma once
#include <string>
#include <cstddef>

/**
 * @brief 示例缓冲。
 */
struct Buffer {};

/**
 * @brief 示例连接。
 */
class T {
public:
    /**
     * @name Read 系
     * @brief 读取已到达的数据，提供多种输出形态。
     *
     * 共享语义：失败时不写输出、不消费数据；成功返回前数据已从连接移交。
     * @{
     */

    /**
     * @param out 输出区
     * @param size 容量
     */
    void Read(char* out, int size);

    /**
     * @param out 追加到末尾
     */
    void Read(std::string& out);

    /**
     * @param out 目标缓冲
     */
    void Read(Buffer& out);

    /**
     * @param out 目标缓冲，不可为空
     */
    void Read(Buffer* out);

    /**
     * @return 丢弃的字节数
     */
    std::size_t Read();

    /**
     * @param n 字节数
     * @return 不足 n 时为已有部分
     */
    std::string ReadNByte(std::size_t n);

    /**
     * @}
     */
};
