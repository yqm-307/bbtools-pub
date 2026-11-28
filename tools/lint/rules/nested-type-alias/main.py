"""Find deep template spellings in ordinary C++ declarations, without expanding aliases."""
import re


# Work on Source.code: offsets survive masking of comments, literals and directives.
TOKEN = re.compile(r'(?:(?P<arrow>->)\s*)?(?P<name>(?:[A-Za-z_]\w*\s*::\s*)*[A-Za-z_]\w*)'
                   r'(?P<opening>\s*<(?![=<]))?|\d\w*|::|<<|<=|>=|\S')
TRAILING_END = re.compile(r'\s*(?:(?:override|final)\s*)*(?=[;{=])')
DECLARATOR = re.compile(r'\s*(?:(?:const\b|volatile\b|[&*])\s*)*(?:[A-Za-z_]\w*|(?=[,)]))')


def check(source, options):
    if source.path.suffix == '.c':
        return
    stack = []
    peak = 0
    alias = False
    previous = ''
    for token in TOKEN.finditer(source.code):
        word = token[0]
        if word in (';', '{', '}', 'using', 'typedef'):
            stack.clear()
            alias = word in ('using', 'typedef')
        elif not alias and token['opening'] and token['name'] not in ('template', 'operator'):
            if not stack:
                peak = 0
            stack.append(token)
            peak = max(peak, len(stack))
        elif stack and word == '>':
            opening = stack.pop()
            if not stack and peak >= 3 and (DECLARATOR.match(source.code, token.end())
                    or opening['arrow'] and TRAILING_END.match(source.code, token.end())):
                yield (source.line(opening.start('name')),
                       f'裸类型嵌套 {peak} 层；请给内层组合取业务别名，保留外层所有权。',
                       ''.join(opening['name'].split()))
        elif stack and not (word in (',', '*', '&', '::', 'const', 'volatile')
                            or previous != '>' and (token['name'] or word[0].isdigit())):
            # Do not carry template depth through expressions such as a < b < c > d, or across statements.
            stack.clear()
        previous = word
