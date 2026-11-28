#!/usr/bin/env python3
"""Format or check C/C++ files using the repository's clang-format style."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpp_format import format_source


CPP_EXTENSIONS = {'.c', '.cc', '.cpp', '.cxx', '.h', '.hh', '.hpp', '.hxx', '.inl', '.ipp'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument('--all', action='store_true', help='select all tracked C/C++ files')
    selected.add_argument('--staged', action='store_true', help='check C/C++ blobs in the Git index')
    parser.add_argument('--check', action='store_true', help='check without changing files or the Git index')
    args = parser.parse_args()
    if args.staged and not args.check:
        parser.error('--staged requires --check')
    os.chdir(os.fsdecode(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'])).rstrip('\n'))
    if not any(Path(name).is_file() for name in ('.clang-format', '_clang-format')):
        parser.error('missing repository .clang-format or _clang-format')

    binary = os.environ.get('CLANG_FORMAT', 'clang-format')
    wanted = os.environ.get('CLANG_FORMAT_VERSION', '23.1.3')
    if not wanted:
        parser.error('CLANG_FORMAT_VERSION must not be empty')
    version = subprocess.check_output([binary, '--version'], text=True).strip()
    reported = re.search(r'\bclang-format version (\S+)', version)
    if not reported or reported[1] != wanted:
        parser.error(f'need clang-format {wanted}; got {version}')

    def paths(*args):
        data = subprocess.check_output(['git', *args, '-z'])
        return {Path(os.fsdecode(p)) for p in data.split(b'\0') if p}

    staged_links = set()
    if args.all:
        candidates = paths('ls-files')
    elif args.staged:
        candidates = paths('diff', '--cached', '--name-only', '--diff-filter=ACMR')
        entries = subprocess.check_output(['git', 'ls-files', '--stage', '-z'])
        staged_links = {Path(os.fsdecode(entry.partition(b'\t')[2]))
                        for entry in entries.split(b'\0') if entry.startswith(b'120000 ')}
    else:
        candidates = paths('diff', '--cached', '--name-only') | paths('ls-files', '-mo', '--exclude-standard')
    files = sorted(p for p in candidates if p.suffix in CPP_EXTENSIONS and 'third-party' not in p.parts)
    checked, changed = 0, {}
    for path in files:
        if args.staged:
            if path in staged_links:
                raise ValueError(f'{path}: staged symbolic link is not a C/C++ source blob; check it with --check --all')
            source = subprocess.check_output(['git', 'cat-file', 'blob', f':{path}'])
        else:
            resolved = path.resolve()
            if resolved != path.absolute():
                if not args.check:
                    continue
                if not resolved.is_relative_to(Path.cwd()) or not resolved.is_file():
                    raise ValueError(f'{path}: symbolic link does not resolve to a file inside the repository')
            if not path.is_file():
                if args.check and args.all:
                    raise ValueError(f'{path}: tracked file is missing from the worktree')
                continue
            source = path.read_bytes()
        formatted = format_source(binary, path, source)
        if formatted is None:
            continue
        checked += 1
        if formatted != source:
            if args.check:
                print(f'{path}: C/C++ format differs', file=sys.stderr)
            changed[path] = formatted
    if args.check and changed:
        print(f'Format failed: {len(changed)}/{checked} C/C++ files differ', file=sys.stderr)
        return 1
    for path, formatted in changed.items():
        path.write_bytes(formatted)
    print(f'Format OK: {checked} C/C++ files checked, {len(changed)} updated')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        sys.exit(f'format-cpp: {error}')