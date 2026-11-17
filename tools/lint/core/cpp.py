"""Shared lexical C++ model; no project policy or rule dispatch lives here."""
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
import re
import scanner

EXTENSIONS = {'.h', '.hh', '.hpp', '.hxx', '.cc', '.cpp', '.cxx', '.c'}
HEADERS = {'.h', '.hh', '.hpp', '.hxx'}
LEXEMES = re.compile(
    r'//[^\n]*|/\*[\s\S]*?\*/|(?:u8|u|U|L)?R"(?P<delim>[^()\\\s]{0,16})\([\s\S]*?\)(?P=delim)"'
    r'|\b\d[\w.\x27]*|(?:u8|u|U|L)?"(?:\\[\s\S]|[^"\\])*"'
    r"|'(?:\\[\s\S]|[^'\\])+'")
CLASSES = re.compile(r'\b(class|struct)\s+(\w+)\s*(?:final\s*)?(?::[^;{}]+)?\s*\{')


@dataclass
class Member:
    signature: str
    body: str | None
    offset: int
    access: str


def blank(text):
    return ''.join('\n' if c == '\n' else ' ' for c in text)


def without_templates(text):
    while re.search(r'<[^<>]*>', text):
        text = re.sub(r'<[^<>]*>', '', text)
    return text


def method(signature):
    value = without_templates(signature).split('{', 1)[0]
    if re.search(r'\b(using|typedef|friend|static_assert)\b', value):
        return False
    if re.search(r'\boperator\s*(?:[^\w\s]+|\w+)\s*\(', value):
        return True
    value = value.split('=', 1)[0]
    return '(' in value


def members(code, start, end, pairs, access):
    """Split immediate declarations; skip nested types, bodies and initializers."""
    result = []
    begin = start
    i = start
    while i < end:
        access_match = re.match(r'\s*(public|private|protected)\s*:', code[i:end]) if i == begin else None
        if access_match:
            access = access_match[1]
            i += access_match.end()
            begin = i
            continue
        char = code[i]
        if char in '([' and i in pairs:
            i = pairs[i] + 1
            continue
        if char == '{' and i in pairs:
            signature = code[begin:i].strip()
            stop = pairs[i]
            if re.search(r'\b(class|struct|enum|union)\b', signature):
                i = stop + 1
                begin = i
                continue
            if method(signature):
                result.append(Member(signature, code[i + 1:stop], begin, access))
                i = stop + 1
                begin = i
                continue
            i = stop + 1
            continue
        if char == ';':
            signature = code[begin:i].strip()
            if signature:
                result.append(Member(signature, None, begin, access))
            begin = i + 1
        i += 1
    return result


class Source:
    def __init__(self, path, text, exists):
        self.path = Path(path)
        self.text = text
        self.exists = exists
        self.newlines = [i for i, c in enumerate(text) if c == '\n']
        self.issues = []
        self.classes = []
        self.code = ''
        self.pairs = {}
        self.valid = False
        self.parse(text)

    def line(self, offset):
        return bisect_right(self.newlines, offset) + 1

    def incomplete(self, line, message):
        self.issues.append((line, message, ''))

    def parse(self, text):
        line = self.line
        code = LEXEMES.sub(lambda m: blank(m[0]), text)
        # Unconsumed quote/comment openers indicate malformed or unsupported lexemes.
        if re.search(r'["\x27]|/\*', code):
            self.incomplete(1, 'incomplete: unterminated or unsupported literal/comment')
        for directive in re.finditer(r'^\s*#\s*(if\w*|elif|else|define)\b[^\n]*(?:\\\n[^\n]*)*', code, re.M):
            if directive[1] == 'define' and not re.search(r'\([^)]*\)|\S+\s+\S+', directive[0].split('define', 1)[1].strip()):
                continue
            self.incomplete(line(directive.start()), 'incomplete: preprocessor branches/macros not expanded')
        code = re.sub(r'^\s*#[^\n]*(?:\\\n[^\n]*)*', lambda m: blank(m[0]), code, flags=re.M)
        pairs = {}
        stack = []
        for i, char in enumerate(code):
            if char in '{([':
                stack.append((char, i))
            elif char in '})]':
                if not stack or stack[-1][0] != dict(zip('})]', '{(['))[char]:
                    self.incomplete(line(i), 'incomplete: unmatched delimiter')
                    return
                _, opening = stack.pop()
                pairs[opening] = i
        if stack:
            self.incomplete(line(stack[-1][1]), 'incomplete: unclosed delimiter')
            return
        self.classes = []
        # ponytail: lexical declarations only; use a compiler AST if macro/template fidelity is required.
        matched_types = set()
        for match in CLASSES.finditer(code):
            if re.search(r'\benum\s*$', code[max(0, match.start() - 16):match.start()]):
                continue
            matched_types.add(match.start())
            opening = match.end() - 1
            if opening not in pairs:
                continue
            end = pairs[opening]
            entries = members(code, opening + 1, end, pairs, 'public' if match[1] == 'struct' else 'private')
            fields = []
            operations = []
            for entry in entries:
                signature = entry.signature
                if re.match(r'^(using|typedef|friend|enum|class|struct|static_assert)\b', signature):
                    continue
                if method(signature):
                    operations.append(entry)
                elif scanner.variable_declaration(signature + ';'):
                    if not re.search(r'\bstatic\b', signature):
                        fields.append(entry)
                else:
                    self.incomplete(line(entry.offset), f'incomplete: unclassified member of {match[2]}')
            self.classes.append({'name': match[2], 'start': match.start(), 'end': end,
                                 'fields': fields, 'operations': operations})
        for match in re.finditer(r'\b(class|struct|union)\s+[^;{}<>]*\{', code):
            if (match.start() not in matched_types
                    and not re.search(r'\benum\s*$', code[max(0, match.start() - 16):match.start()])):
                self.incomplete(line(match.start()), 'incomplete: unsupported type declaration')
        self.code, self.pairs, self.valid = code, pairs, True

    def top_classes(self):
        return [c for c in self.classes if not any(
            other['start'] < c['start'] < other['end'] for other in self.classes)]

    def in_body(self, offset):
        # ponytail: non-declaration braces count as bodies; AST needed for macro-heavy syntax.
        for opening, end in self.pairs.items():
            if self.code[opening] != '{' or not opening < offset < end:
                continue
            start = max(self.code.rfind(c, 0, opening) for c in ';{}') + 1
            prefix = self.code[start:opening].strip()
            if re.search(r'\b(namespace|class|struct|union|enum)\b[^;{}]*$', prefix):
                continue
            if re.fullmatch(r'(?:inline\s+)?extern\s*', prefix):
                continue
            return True
        return False

    def variable_comments(self):
        comments, columns = scanner.scan(self.text)
        clean = self.code.splitlines()
        for cm in comments:
            before = any(c < cm.start_col for c in columns.get(cm.start, []))
            after = any(c > cm.end_col for c in columns.get(cm.end, []))
            declaration = clean[cm.start - 1] if before or after else (clean[cm.end] if cm.end < len(clean) else '')
            if scanner.variable_declaration(declaration):
                yield cm, before, after


def mutable_field(signature):
    declaration = without_templates(re.split(r'=|\{', signature, maxsplit=1)[0])
    qualifiers = declaration.rsplit('*', 1)[-1] if '*' in declaration else declaration
    return not re.search(r'\b(const|constexpr)\b', qualifiers)
