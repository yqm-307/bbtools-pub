import re


def check(source, options):
    for match in re.finditer(r'\b\w*(?:ForTest|TestAccess|for_test|test_inject)\w*\b', source.code):
        yield source.line(match.start()), f'candidate test seam {match[0]} in scanned production scope', match[0]
