// 伪代码示例：与 ClassLayout.hpp 配套，即使只返回一个成员，实现也写在这里。

size_t Reader::Progress() const
{
    return m_progress;
}

bool Reader::IsDone() const
{
    return m_isDone;
}
