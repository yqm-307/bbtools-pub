"""C++ comment scanner; lexical check, not a compiler."""
import re
from dataclasses import dataclass
ACCESS_SPECIFIER = re.compile(r"^(public|protected|private)\s*:$")

@dataclass
class Comment:
    kind: str  # 'line' | 'block'
    start: int  # 1-based 行号
    end: int
    start_col: int
    end_col: int  # 注释最后一个字符所在列
    text: str


def scan(text: str) -> tuple[list[Comment], dict[int, list[int]]]:
    """返回全部注释与每行代码字符所在列；字符串、字符、原始字符串字面量里的 `//` 不算注释。"""
    comments: list[Comment] = []
    code_cols: dict[int, list[int]] = {}
    i, line, col, n = 0, 1, 0, len(text)

    def advance(k: int) -> None:
        nonlocal i, line, col
        for _ in range(k):
            if i < n and text[i] == '\n':
                line, col = line + 1, 0
            else:
                col += 1
            i += 1

    def mark_code() -> None:
        code_cols.setdefault(line, []).append(col)

    while i < n:
        c = text[i]
        if c == '/' and text.startswith('//', i):
            start, start_col, begin = line, col, i
            while i < n and text[i] != '\n':
                advance(1)
            comments.append(Comment('line', start, start, start_col, col - 1, text[begin:i]))
        elif c == '/' and text.startswith('/*', i):
            start, start_col, begin = line, col, i
            advance(2)
            while i < n and not text.startswith('*/', i):
                advance(1)
            advance(1)
            end, end_col = line, col
            advance(1)
            comments.append(Comment('block', start, end, start_col, end_col, text[begin:i]))
        elif c == '"' and re.search(r'(^|[^\w])(u8|u|U|L)?R$', text[max(0, i - 3):i]):
            m = re.match(r'"([^()\\\s]{0,16})\(', text[i:])
            delim = m.group(1) if m else None
            close = text.find(f'){delim}"', i) if delim is not None else -1
            stop = n if delim is None or close < 0 else close + len(delim) + 2
            while i < stop:
                mark_code()
                advance(1)
        elif c in '"\'':
            if c == "'" and _is_digit_separator(text, i):
                mark_code()
                advance(1)
                continue
            mark_code()
            advance(1)
            while i < n and text[i] != c and text[i] != '\n':
                if text[i] == '\\':
                    mark_code()
                    advance(1)
                mark_code()
                advance(1)
            mark_code()
            advance(1)
        else:
            if not c.isspace():
                mark_code()
            advance(1)
    return comments, code_cols


def _is_digit_separator(text: str, i: int) -> bool:
    """C++14 数字分隔符 `1'000`：引号前是以数字开头的记号。"""
    j = i
    while j > 0 and (text[j - 1].isalnum() or text[j - 1] in "_.'"):
        j -= 1
    return j < i and text[j].isdigit()


def comment_violations(path: str, text: str, added: set[int]) -> list[str]:
    """按 documentation.md §7 只检查与本次新增行相交的注释。"""
    lines = text.split('\n')
    comments, code_cols = scan(text)
    found = []

    def line_at(no: int) -> str:
        return lines[no - 1].strip() if 1 <= no <= len(lines) else ''

    for cm in comments:
        if not added.intersection(range(cm.start, cm.end + 1)):
            continue
        problems = []
        before = any(c < cm.start_col for c in code_cols.get(cm.start, []))
        after = any(c > cm.end_col for c in code_cols.get(cm.end, []))
        if cm.kind == 'line':
            problems.append('用了 `//` 注释，改为多行 `/** */` 块')
        elif cm.start == cm.end:
            problems.append('单行块注释，改为 `/**`、正文、` */` 各占一行')
        else:
            if not cm.text.startswith('/**'):
                problems.append('块注释以 `/*` 开头，改为 `/**`')
            if line_at(cm.start) not in ('/*', '/**'):
                problems.append('`/**` 未独占一行')
            if line_at(cm.end) != '*/':
                problems.append('` */` 未独占一行')
            if any(not re.fullmatch(r'\s*\*(?: .*|\s*)', line)
                   for line in lines[cm.start:cm.end - 1]):
                problems.append('正文每行必须以 ` * ` 开头')
        if before or after:
            problems.append('行尾/行内注释，移到所说明代码的上方')
        if cm.kind == 'block' and not before and cm.start > 1:
            prev = line_at(cm.start - 1)
            if prev and not ACCESS_SPECIFIER.match(prev):
                problems.append('注释块上方没有空行')
        if cm.kind == 'block' and not after and cm.start > 1 and '@{' not in cm.text:
            if cm.end < len(lines) and not line_at(cm.end + 1):
                problems.append('注释块和它说明的代码之间有空行，应紧贴')
        if problems:
            found.append(f'{path}:{cm.start}: ' + '；'.join(problems))
    return found


