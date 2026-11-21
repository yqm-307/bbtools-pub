"""Directory-shape helpers over one immutable Git tree; no checkout.

Git pathnames are arbitrary bytes: nothing here decodes them, so a tree entry
with an undecodable name cannot break the comparison. Use show() to print one.
"""
import subprocess
from runner import HookError

GITLINK = b'160000'


def _raw(*args):
    """Verbatim Git stdout: path bytes keep their identity, never re-decoded."""
    p = subprocess.run(['git', *args], capture_output=True, timeout=30)
    if p.returncode:
        raise HookError(p.stderr.decode('utf-8', 'backslashreplace').strip()
                        or f'git {args} failed ({p.returncode})')
    return p.stdout


def entries(tree):
    """Relative path bytes -> mode bytes for every file and gitlink in the tree."""
    result = {}
    for row in _raw('ls-tree', '-r', '-z', '--full-tree', tree).split(b'\0'):
        if row:
            header, path = row.split(b'\t', 1)
            result[path] = header.split()[0]
    return result


def roots(modes):
    """Top-level directory name bytes the tree occupies; a top-level plain file is not one."""
    return {path.partition(b'/')[0] for path, mode in modes.items() if b'/' in path or mode == GITLINK}


def changes(ctx, kinds='ACMR'):
    """Changed path bytes between the context trees, unfiltered (layout looks at the whole tree)."""
    names = _raw('diff', '--name-only', '-z', '--no-renames', f'--diff-filter={kinds}',
                 ctx['base'], ctx['tree'], '--').split(b'\0')
    return [path for path in names if path]


def show(path):
    """Printable form of path bytes; undecodable bytes stay visible instead of being replaced."""
    return path.decode('utf-8', 'backslashreplace')
