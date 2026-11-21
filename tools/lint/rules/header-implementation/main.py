"""Report recognizable function definitions in interface headers for human review."""
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'git-hooks/core'))
from runner import guarded, report, rule_input
from staged import added_lines, contexts, cxx_files, text
from cpp import HEADERS, Source

FUNCTION = re.compile(r'\b(~?\w+)\s*\([^;{}]*\)\s*(?:const\s*|noexcept\s*|override\s*|final\s*|&\s*)*(?:->\s*[^;{}]+)?$')
CONTROL = {'if', 'for', 'while', 'switch', 'catch', 'requires'}
NONTRIVIAL = re.compile(r'\b(?:if|for|while|switch|try|new|delete|lock_guard|unique_lock|scoped_lock|make_unique|make_shared)\b|\.lock\s*\(')


def findings(path, contents, added):
    source = Source(path, contents, lambda _: False)
    for opening, end in sorted(source.pairs.items()):
        if source.code[opening] != '{':
            continue
        start = max(source.code.rfind(c, 0, opening) for c in ';{}') + 1
        prefix = source.code[start:opening].strip()
        match = FUNCTION.search(prefix)
        if not match or match[1] in CONTROL or re.search(r'\b(?:constexpr|consteval)\b', prefix):
            continue
        if source.in_body(opening):
            continue
        begin_line = source.line(source.code.find(prefix, start))
        if not any(n in added for n in range(begin_line, source.line(end) + 1)):
            continue
        template = bool(re.search(r'\btemplate\s*<', prefix))
        for cls in source.classes:
            if cls['start'] < opening < cls['end']:
                pos = cls['start']
                begin = max(source.code.rfind(c, 0, pos) for c in ';{}') + 1
                template |= bool(re.search(r'\btemplate\s*<', source.code[begin:pos]))
        if template or NONTRIVIAL.search(source.code[opening + 1:end]):
            target = f'__T{Path(path).stem}.hpp' if template else '.cc（header-only 模块用实现头）'
            yield f'{path}:{source.line(opening)}: {match[1]} 实现在接口头中，建议评估移到 {target}'


def check():
    problems = []
    for ctx in contexts(rule_input()):
        for path in cxx_files(ctx):
            header = Path(path)
            if header.suffix in HEADERS and not header.name.startswith('__T'):
                problems.extend(findings(path, text(ctx, path), added_lines(ctx, path)))
    return report('E-HEADER-IMPLEMENTATION', problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
