"""Git blob adapter for source rules; no checkout or temporary source tree."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'git-hooks/core'))
from runner import git, guarded, rule_input, report
from staged import contexts, files, text
from cpp import EXTENSIONS
from scan import Scan


def check():
    ctx = rule_input()
    rule = sys.argv[1]
    scan = Scan(Path.cwd(), ctx['config'], [rule])
    for change in contexts(ctx):
        entries = git('ls-tree', '-r', '-z', change['tree']).stdout.split('\0')
        modes = {}
        for entry in entries:
            if entry:
                header, path = entry.split('\t', 1)
                modes[path] = header.split()[0]
        for path in files(change):
            if Path(path).suffix not in EXTENSIONS or not scan.included(path):
                continue
            if modes.get(path) == '120000':
                scan.emit(path, 1, 'T000', 'incomplete: symlink source not followed')
                continue
            scan.text(path, text(change, path), lambda p: p.as_posix() in modes)
    problems = [f'{r["file"]}:{r["line"]}: {r["rule"]} {r["message"]}' for r in scan.rows]
    if scan.partial:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 2
    return report('E-' + rule.upper(), problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
