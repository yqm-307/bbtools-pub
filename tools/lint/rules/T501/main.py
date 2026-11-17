import re


def check(source, options):
    for match in re.finditer(r'\b[A-Za-z_]\w*V[0-9]+\w*\b', source.code):
        yield source.line(match.start()), f'candidate historical identifier {match[0]}; not an automatic rename', match[0]
