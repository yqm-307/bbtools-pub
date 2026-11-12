import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import guarded, rule_input, report, git, HookError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scanner import comment_violations
from staged import cxx_files, text, added_lines

def check():
    ctx = rule_input()
    for path in cxx_files(ctx):
        found = comment_violations(path, text(ctx, path), added_lines(ctx, path))
        if found:
            return report('E-COMMENT-FORM', found)
    return 0

if __name__ == '__main__':
    sys.exit(guarded(check))
