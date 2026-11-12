import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import guarded, rule_input, report
from formatcheck import violations


def check():
    return report('E-FORMAT', violations(rule_input()))


if __name__ == '__main__':
    sys.exit(guarded(check))
