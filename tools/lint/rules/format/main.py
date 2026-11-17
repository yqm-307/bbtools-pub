import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'git-hooks/core'))
from runner import guarded, rule_input, report
from formatcheck import violations
from staged import contexts


def check():
    problems = []
    for ctx in contexts(rule_input()):
        problems += violations(ctx)
    return report('E-FORMAT', problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
