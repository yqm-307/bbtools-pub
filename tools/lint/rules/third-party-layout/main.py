"""Allow only configured gitlinks under the third-party directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'git-hooks/core'))
from runner import guarded, report, rule_input
from layout import GITLINK, changes, entries, show
from staged import contexts

THIRD_PARTY = b'third-party'


def check():
    problems = []
    for ctx in contexts(rule_input()):
        allowed = {path.encode() for path in ctx['config']['layout']['allowed_gitlinks']}
        modes = entries(ctx['tree'])
        for path in changes(ctx, 'AMT'):
            if path != THIRD_PARTY and not path.startswith(THIRD_PARTY + b'/'):
                continue
            mode = modes.get(path)
            if path in allowed and mode == GITLINK:
                continue
            problems.append(f'{show(path)}: 只允许 layout.allowed_gitlinks 中配置路径的 gitlink（{GITLINK.decode()}）新增或变更，'
                            f'实际 mode {mode.decode() if mode else "缺失"}')
    return report('E-THIRD-PARTY-LAYOUT', problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
