"""Read only the immutable index tree passed to a rule."""
import fnmatch
import re
from runner import git


def files(ctx, kinds='ACMR'):
    names = git('diff', '--name-only', '-z', '--no-renames', f'--diff-filter={kinds}',
                ctx['base'], ctx['tree'], '--').stdout.split('\0')
    return [p for p in names if p and not any(fnmatch.fnmatchcase(p, pattern)
            for pattern in ctx['config']['scope']['exclude'])]


def cxx_files(ctx):
    return [p for p in files(ctx) if re.search(r'\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp)$', p)]


def text(ctx, path):
    return git('show', f'{ctx["tree"]}:{path}').stdout


def added_lines(ctx, path):
    diff = git('diff', '-U0', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
               ctx['base'], ctx['tree'], '--', path).stdout
    lines = set()
    for m in re.finditer(r'^@@ -\S+ \+(\d+)(?:,(\d+))? @@', diff, re.M):
        start, count = int(m[1]), int(m[2] or 1)
        lines.update(range(start, start + count))
    return lines
