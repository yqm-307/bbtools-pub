"""Whitespace between bbtools coroutine syntax and its operand; never rewrite macro arguments as code."""
import re


_EXPRESSIONS = {b'bbt_co_await', b'bbt_co_fire', b'bbt_co_return'}
_BLOCKS = {b'bbtco_ref', b'bbtco_defer'}
_EVENTS = re.compile(rb'bbtco_ev_(?:[wr](?:tc?|c)?|t)(?:_with_copool)?\Z')
_CALLBACKS = {b'bbtco_noexcept', b'bbtco_desc'}
_NON_MACROS = _EXPRESSIONS | {b'if', b'while', b'for', b'switch', b'return', b'sizeof', b'decltype', b'static_assert', b'catch'}
_NAME = rb'[A-Za-z_$\x80-\xff][\w$\x80-\xff]*'
_TOKEN = re.compile(
    rb'(?P<directive>\#|%:)|'
    rb'(?P<comment>//(?:\\\r?\n|[^\n])*|/\*[\s\S]*?\*/)|'
    rb'(?:u8|[LuU])?R"(?P<delim>[^()\\\s]{0,16})\([\s\S]*?\)(?P=delim)"|'
    rb'(?:u8|[LuU])?(?:"(?:\\[\s\S]|[^"\\])*"|\'(?:\\[\s\S]|[^\'\\])*\')|'
    rb'(?P<name>' + _NAME + rb')|\d[\w.\x27]*|(?P<splice>\\\r?\n)|<<|::|<:(?!:(?![:>]))|:>|\S')
_TARGET = re.compile(rb'\b(?:bbtco(?:_noexcept|_desc|_ref|_defer|_ev_\w+)?|bbt_co_(?:await|fire|return))\b')
_EMPTY_LAMBDA = re.compile(rb'(?:\s*\(\s*\))?\s*\{\s*\}')


def _logical_line_end(source, start):
    while True:
        end = source.find(b'\n', start)
        if end < 0:
            return len(source)
        if not source.endswith((b'\\', b'\\\r'), start, end):
            return end
        start = end + 1


def outside_ranges(edits, ranges):
    """Discard even a partial overlap rather than slicing a clang replacement."""
    i = 0
    for offset, length, replacement in edits:
        while i < len(ranges) and ranges[i][1] <= offset:
            i += 1
        if i == len(ranges) or offset + length <= ranges[i][0] and offset < ranges[i][0]:
            yield offset, length, replacement


def spacing_plan(source):
    if not _TARGET.search(source):
        return [], [], []
    edits, protected, parens = [], [], []
    captures, brackets = [], []
    after_capture = False
    previous = before = closed_call = b''
    end = 0
    last_target = -1
    disabled = False
    directive_start = directive_end = -1
    for token in _TOKEN.finditer(source):
        word = token[0]
        if word == b'<:':
            word = b'['
        elif word == b':>':
            word = b']'
        if token.start() < directive_end:
            if token.end() > directive_end:  # a raw literal or block comment spans physical lines
                directive_end = _logical_line_end(source, token.end())
            continue
        if directive_start >= 0:
            if _TARGET.search(source, directive_start, directive_end):
                protected.append((directive_start, directive_end))
            directive_start = -1
        if token['directive']:
            directive_start = token.start()
            directive_end = _logical_line_end(source, token.end())
            previous = before = closed_call = b''
            after_capture = False
            continue
        if token['comment']:
            control = re.match(rb'(?:/\*|//)\s*clang-format (off|on)\b', word)
            if control:
                disabled = control[1] == b'off'
            continue
        if token['splice']:
            continue
        start = token.start()
        if _TARGET.fullmatch(word):
            last_target = start
        if not disabled:
            space = None
            # In C++17 an omitted parameter list is followed directly by the body.
            if after_capture and word == b'{':
                edits.append((end, 0, b'()'))
            if previous in _EXPRESSIONS and word not in (b';', b')', b',', b']'):
                space = b' '
            elif word == b'[' and (previous == b'bbtco' or (previous == b')' and
                    (closed_call in _CALLBACKS or _EVENTS.fullmatch(closed_call)))):
                space = b' '
                captures.append(start)
            elif word == b'{' and previous in _BLOCKS:
                space = b' '
            elif before in _EXPRESSIONS and previous in (b'-', b'+') and (token['name'] or word[:1].isdigit()):
                space = b''
            if space is not None:
                gap = source[end:start]
                whitespace = b' \t\r\n' if word == b'[' and captures and captures[-1] == start else b' \t'
                if gap != space and not gap.strip(whitespace):
                    edits.append((end, start - end, space))
        after_capture = False
        if word == b'[':
            brackets.append(bool(captures and captures[-1] == start))
        elif word == b']' and brackets and brackets.pop() and not disabled:
            # Only the matching capture closer counts: [item = items[i]] is one capture list.
            empty = _EMPTY_LAMBDA.match(source, token.end())
            if empty:
                if empty[0] != b'(){}':
                    edits.append((empty.start(), len(empty[0]), b'(){}'))
            else:
                after_capture = True
        if word == b'(':
            # Both name(args) and PICK()(args) can stringify args after preprocessing.
            possible_macro = previous == b')' or (bool(re.fullmatch(_NAME, previous)) and previous not in _NON_MACROS)
            parens.append((start, previous, possible_macro))
        elif word == b')' and parens:
            opening, closed_call, possible_macro = parens.pop()
            if possible_macro and last_target > opening:
                protected.append((opening, token.end()))
        before, previous, end = previous, word, token.end()
    if directive_start >= 0 and _TARGET.search(source, directive_start, directive_end):
        protected.append((directive_start, directive_end))
    protected.extend((opening, len(source)) for opening, _, possible in parens if possible and last_target > opening)
    merged = []
    for a, b in sorted(protected):
        if not merged or merged[-1][1] < a:
            merged.append((a, b))
        elif merged[-1][1] < b:
            merged[-1] = (merged[-1][0], b)
    captures = [pos for pos, _, _ in outside_ranges(((p, 0, b'') for p in captures), merged)]
    return merged, list(outside_ranges(edits, merged)), captures
