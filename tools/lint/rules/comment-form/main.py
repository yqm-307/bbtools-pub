import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'git-hooks/core'))
from runner import guarded, rule_input, report, git, HookError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'core'))
from scanner import comment_violations
from staged import cxx_files, text, added_lines, contexts

def check():
    for ctx in contexts(rule_input()):
        for path in cxx_files(ctx):
            found = comment_violations(path, text(ctx, path), added_lines(ctx, path))
            if found:
                return report('E-COMMENT-FORM', found)
    return 0

if __name__ == '__main__':
    sys.exit(guarded(check))
