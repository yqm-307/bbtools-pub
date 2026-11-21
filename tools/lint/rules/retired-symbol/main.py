"""Check exact retired spellings on changed C++ source lines, including test seams."""
import fnmatch
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'git-hooks/core'))
from runner import guarded, report, rule_input
from staged import added_lines, contexts, files, text
from cpp import EXTENSIONS, LEXEMES, blank


def check():
    problems = []
    for ctx in contexts(rule_input()):
        for path in files(ctx, excluded=()):
            if Path(path).suffix not in EXTENSIONS | {'.inl', '.ipp'}:
                continue
            names = {name for entry in ctx['config']['retired']
                     if fnmatch.fnmatchcase(path, entry['path']) for name in entry['symbols']}
            if not names:
                continue
            source = text(ctx, path)
            code = LEXEMES.sub(lambda m: blank(m[0]), source)
            added = added_lines(ctx, path)
            for n, line in enumerate(code.split('\n'), 1):
                if n not in added:
                    continue
                line = re.sub(r'^\s*#\s*include(?:_next)?\b\s*(?:<[^>]*>)?', '', line)
                for name in sorted(names.intersection(re.findall(r'\b\w+\b', line))):
                    problems.append(f'{path}:{n}: 已退役标识符 {name}')
    return report('E-RETIRED-SYMBOL', problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
