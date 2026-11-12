"""clang-format dry run over the C/C++ files of one base..tree change, shared by commit and push."""
from pathlib import Path
import subprocess
from runner import HookError
from staged import cxx_files, text


def violations(ctx):
    problems = []
    for path in cxx_files(ctx):
        p = subprocess.run([ctx['config']['format']['binary'], '--dry-run', '--Werror',
                            '--style=file', '--fallback-style=none', f'--assume-filename={path}'],
                           input=text(ctx, path), text=True, capture_output=True)
        parent = Path(path).absolute().parent
        if not any((p / '.clang-format').is_file() or (p / '_clang-format').is_file()
                   for p in (parent, *parent.parents)):
            raise HookError(f'{path}: missing .clang-format')
        if p.returncode:
            problems.append(f'{path}: {p.stderr.strip()}')
    return problems
