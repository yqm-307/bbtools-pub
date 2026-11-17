import re


def check(source, options):
    for match in re.finditer(r'\b(?:unique_lock|lock_guard|scoped_lock)\b[^;\n]*(?:->|\.)\s*(\w*(?:mu|mutex)\w*)', source.code):
        yield source.line(match.start()), 'candidate external member lock; verify ownership boundary', match[1]
