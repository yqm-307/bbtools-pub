"""Canonical clang-format output for both the working tree and immutable Git blobs."""
import os
import re
import subprocess
from bisect import bisect_left
from glob import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from coroutine_spacing import outside_ranges, spacing_plan


_TAIL = re.compile(rb'^[ \t]*(?:const(?:[ \t]+override)?|override);?[ \t]*\r?$', re.M)
_PARAMETER_STYLE = ('{BasedOnStyle: InheritParentConfig, BreakFunctionDeclarationParameters: true, '
                    'BreakFunctionDefinitionParameters: true, BinPackParameters: false, '
                    'AllowAllParametersOfDeclarationOnNextLine: false}')


def _replacements(binary, path, source, style, ranges=()):
    protected, _, captures = spacing_plan(source)
    # A launch macro expands to a helper followed by + or -. Give clang a synthetic operator
    # so it parses the entire RHS as a lambda, without replacing any user's own Macros config.
    marked = _apply(source, ((p, 0, b'+') for p in captures)) if captures else source
    output = subprocess.check_output([binary, '--Werror', '--output-replacements-xml', '--style=' + style,
                                      f'--assume-filename={path}', *ranges], input=marked)
    if not output:  # clang-format-ignore (unlike a clean file's empty XML element).
        return None
    try:
        root = ElementTree.fromstring(output)
    except ElementTree.ParseError as exc:
        raise ValueError(f'{path}: invalid clang-format replacement XML: {exc}') from exc
    if root.get('incomplete_format') == 'true':
        raise ValueError(f"{path}:{root.get('line', '?')}: clang-format reported incomplete formatting")
    edits = [(int(r.attrib['offset']), int(r.attrib['length']), (r.text or '').encode()) for r in root]
    if captures:
        markers = [pos + i for i, pos in enumerate(captures)]
        mapped = []
        for offset, length, replacement in edits:
            i = bisect_left(markers, offset)
            if ((i < len(markers) and markers[i] <= offset + length)
                    or (i and markers[i - 1] + 1 == offset)):
                continue  # The gap at the prefix/capture boundary is owned by spacing_plan.
            mapped.append((offset - i, length, replacement))
        edits = mapped
    return list(outside_ranges(edits, protected)) if protected else edits


def _apply(source, edits):
    pieces, cursor = [], 0
    for offset, length, replacement in edits:
        pieces.extend((source[cursor:offset], replacement))
        cursor = offset + length
    return b''.join((*pieces, source[cursor:]))


def _wrap_qualifiers(binary, path, source):
    # Limit the override to parameter lists that clang itself left on one line with a dangling qualifier.
    # A range can expand to a surrounding declaration (e.g. around raw strings): accept only local edits
    # that actually join the closing parenthesis to the qualifier. Never reformat adjacent short signatures.
    spans, ranges = [], []
    last_offset, line = 0, 1
    for tail in _TAIL.finditer(source):
        start = source.rfind(b'\n', 0, max(0, tail.start() - 1)) + 1
        head = source[start:tail.start()].rstrip()
        if not head.endswith(b')') or b'(' not in head:
            continue
        line += source.count(b'\n', last_offset, tail.start())
        last_offset = tail.start()
        ranges.append(f'--lines={line}:{line}')
        spans.append((start, start + len(head), tail.end()))
    if not ranges:
        return source
    edits = _replacements(binary, path, source, _PARAMETER_STYLE, ranges)
    if edits is None:
        raise ValueError(f'{path}: file became ignored during formatting')
    accepted, i = [], 0
    for start, gap, end in spans:
        local = []
        while i < len(edits) and edits[i][0] < end:
            offset, length, replacement = edits[i]
            if start <= offset and offset + length <= end:
                local.append(edits[i])
            i += 1
        if any(offset == gap and b'\n' in source[offset:offset + length] and repl == b' '
               for offset, length, repl in local):
            accepted.extend(local)
    return _apply(source, accepted)


def _is_ignored_without_worktree_file(binary, path):
    path = Path(path).absolute()
    for parent in path.parents:
        config = parent / '.clang-format-ignore'
        if config.is_file():
            break
    else:
        return False

    # clang-format only matches ignore rules for existing files. Give it a
    # placeholder outside the worktree; the actual source still comes from Git.
    with TemporaryDirectory(prefix='format-cpp-') as tmp:
        mirror = Path(tmp).resolve()
        probe = mirror / path.relative_to(path.anchor)
        probe.parent.mkdir(parents=True)
        probe.touch()
        prefix = escape(os.fsencode(mirror))
        rules = []
        for line in config.read_bytes().split(b'\n'):
            rule = line.strip()
            if not rule or rule.startswith(b'#'):
                continue
            negated = rule.startswith(b'!')
            pattern = rule[1:].lstrip() if negated else rule
            if pattern:
                if not pattern.startswith(b'/'):
                    pattern = os.path.normpath(os.path.join(os.fsencode(config.parent), pattern))
                rules.append((b'!' if negated else b'') + prefix + pattern)
        (mirror / '.clang-format-ignore').write_bytes(b'\n'.join(rules))
        return bool(subprocess.check_output([binary, '--list-ignored', '--', str(probe)]))


def format_source(binary, path, source):
    # Git blobs may have no worktree copy, so ignore rules need an explicit probe.
    if not Path(path).is_file() and _is_ignored_without_worktree_file(binary, path):
        return None
    current = source
    for _ in range(3):
        edits = _replacements(binary, path, current, 'file')
        if edits is None:
            return None
        result = _wrap_qualifiers(binary, path, _apply(current, edits))
        _, spaces, _ = spacing_plan(result)
        if spaces:
            result = _apply(result, spaces)
        if result == current:
            return result
        current = result
    raise ValueError(f'{path}: clang-format did not stabilize after two passes')
