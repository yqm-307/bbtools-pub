/**
 * @file ClassLayout.cc
 * @brief 类布局示例的非平凡实现；空函数和单语句访问器保留在主头。
 */
#include "ClassLayout.hpp"

void Reader::Advance(std::size_t n)
{
    _AdvanceProgress(n);
    _HookOnData();
}

void Reader::_AdvanceProgress(std::size_t n)
{
    m_progress += n;
    if (m_notify && m_onProgress)
        m_onProgress(m_progress);
}
