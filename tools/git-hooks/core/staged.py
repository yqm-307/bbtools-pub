"""Read only the immutable index tree passed to a rule."""
import fnmatch
import re
from runner import git


def contexts(ctx):
    if 'updates' not in ctx:
        yield ctx
        return
    from pushed import candidates
    for info in candidates(ctx):
        yield {'config': ctx['config'], 'base': info['base'], 'tree': info['tip']}


def files(ctx, kinds='ACMR', *, excluded=None):
    names = git('diff', '--name-only', '-z', '--no-renames', f'--diff-filter={kinds}',
                ctx['base'], ctx['tree'], '--').stdout.split('\0')
    if excluded is None:
        excluded = ctx['config']['scope']['exclude']
    return [p for p in names if p and not any(fnmatch.fnmatchcase(p, pattern) for pattern in excluded)]


def cxx_files(ctx):
    return [p for p in files(ctx) if re.search(r'\.(c|cc|cpp|cxx|h|hh|hpp|hxx|inl|ipp)$', p)]


def text(ctx, path):
    return git('show', f'{ctx["tree"]}:{path}').stdout


def added_lines(ctx, path):
    diff = git('diff', '-U0', '--inter-hunk-context=0', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
               ctx['base'], ctx['tree'], '--', ':(literal)' + path).stdout
    lines = set()
    for m in re.finditer(r'^@@ -\S+ \+(\d+)(?:,(\d+))? @@', diff, re.M):
        start, count = int(m[1]), int(m[2] or 1)
        lines.update(range(start, start + count))
    return lines
