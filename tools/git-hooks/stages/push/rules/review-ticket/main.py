import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import guarded, rule_input
from pushed import candidates, load_ticket, validate


def check():
    ctx = rule_input()
    for info in candidates(ctx):
        if info['code']:
            path, ticket = load_ticket(info)
            validate(path, ticket, info)
    return 0


if __name__ == '__main__':
    sys.exit(guarded(check))
