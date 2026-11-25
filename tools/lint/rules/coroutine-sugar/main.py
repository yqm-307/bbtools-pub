"""Enforce the public coroutine syntax layer over low-level runtime calls."""
import re

import scanner


RULE = 'coroutine-sugar'

PATTERNS = (
    (re.compile(r'\bRegistCoroutineTaskOn\b'), 'bbtco has no target-Processer form; add a skip comment with the documented gap reason'),
    (re.compile(r'\bRegistCoroutineTask\b'), 'use bbtco, bbtco_noexcept, or bbtco_desc; add a skip comment for an explicit-stack-size gap'),
    (re.compile(r'\bHook_Sleep\b'), 'use bbtco_sleep'),
    (re.compile(r'\bYieldAndPushGCoQueue\b'), 'use bbtco_yield'),
    (re.compile(r'\bYieldUntilFd(?:Readable|Writeable|Ex)\b'), 'use bbtco_wait_for; add a skip comment when the low-level status code is required'),
    (re.compile(r'\b(?:CoCond|CoMutex|CoRWMutex)::Create\b'), 'use the matching bbtco_make_co* macro'),
    (re.compile(r'\bCoPool::Create\b'), 'use bbtco_make_copool'),
    (re.compile(r'\bCoPoller::CreateEvent\b'), 'use the matching bbtco_ev_* macro'),
    (re.compile(r'\b(?:MakeAsyncOperation|BindAsyncOperation|AwaitHelper|FireHelper|AsyncReturn)\b'),
     'use bbt_co_bind, bbt_co_await, or bbt_co_fire instead of async internals'),
    (re.compile(r'\b(?:_CoHelper|_EventHelper|_WaitForHelper)\b'), 'use the public coroutine syntax macro'),
)

IGNORE = re.compile(
    r'(?:bbt-lint:\s*ignore(?:-next-line)?\s+coroutine-sugar\b|'
    r'NOLINT(?:NEXTLINE)?\(coroutine-sugar\))'
)


def ignored_lines(text):
    ignored = set()
    comments, _ = scanner.scan(text)
    for comment in comments:
        for offset, line in enumerate(comment.text.splitlines()):
            line_no = comment.start + offset
            for match in IGNORE.finditer(line):
                if 'next-line' in match[0].lower() or 'NOLINTNEXTLINE' in match[0]:
                    ignored.add(line_no + 1)
                else:
                    ignored.add(line_no)
    return ignored


def check(source, options):
    ignored = ignored_lines(source.text)
    for pattern, message in PATTERNS:
        for match in pattern.finditer(source.code):
            line = source.line(match.start())
            if line not in ignored:
                yield line, message, match[0]
