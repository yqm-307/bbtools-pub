"""Compare frozen Git blobs with the public formatter, for both commit and push."""
from pathlib import Path
import subprocess
import sys
from runner import HookError
from staged import cxx_files

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'format'))
from cpp_format import format_source


def violations(ctx):
    problems = []
    for path in cxx_files(ctx):
        parent = Path(path).absolute().parent
        if not any((p / '.clang-format').is_file() or (p / '_clang-format').is_file()
                   for p in (parent, *parent.parents)):
            raise HookError(f'{path}: missing .clang-format')
        source = subprocess.check_output(['git', 'cat-file', 'blob', f'{ctx["tree"]}:{path}'], timeout=30)
        formatted = format_source(ctx['config']['format']['binary'], path, source)
        if formatted is not None and formatted != source:
            problems.append(f'{path}: C/C++ format differs')
    return problems
