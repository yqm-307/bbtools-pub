import re
from cpp import HEADERS, blank


def check(source, options):
    top = source.top_classes()
    outer = list(source.code)
    for c in top:
        start, end = c['start'], c['end']
        outer[start:end + 1] = blank(source.code[start:end + 1])
    outer = ''.join(outer)
    if (source.path.suffix in HEADERS and any(c['fields'] for c in top) and len(top) > 1
            and re.search(r'\bconstexpr\b', outer) and re.search(r'\w+\s*\([^;{}]*\)\s*;', outer)):
        yield source.line(top[0]['start']), 'candidate header combines stateful types, constants and free interfaces', ''
