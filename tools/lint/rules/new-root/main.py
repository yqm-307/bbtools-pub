"""Report top-level directories a change introduces outside layout.allowed_roots."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'git-hooks/core'))
from runner import guarded, report, rule_input
from layout import entries, roots, show
from staged import contexts


def check():
    problems = []
    for ctx in contexts(rule_input()):
        allowed = {name.encode() for name in ctx['config']['layout']['allowed_roots']}
        before, after = roots(entries(ctx['base'])), roots(entries(ctx['tree']))
        problems += [f'{show(name)}/: 新增顶层目录 {show(name)} 不在 layout.allowed_roots 中'
                     for name in sorted(after - before - allowed)]
    return report('E-NEW-ROOT', problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
