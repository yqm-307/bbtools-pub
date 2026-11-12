import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import guarded, rule_input, report, git, HookError

def check():
    ctx = rule_input()
    p = git('diff', '--check', ctx['base'], ctx['tree'], '--', check=False)
    if p.returncode not in (0, 2):
        raise HookError(p.stderr or 'git diff --check failed')
    if p.returncode:
        return report('E-WHITESPACE', [x for x in p.stdout.splitlines() if x])
    return 0

if __name__ == '__main__':
    sys.exit(guarded(check))
