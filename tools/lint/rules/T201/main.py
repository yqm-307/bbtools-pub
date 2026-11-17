import re


def check(source, options):
    for cm, before, after in source.variable_comments():
        offset = (source.newlines[cm.start - 2] + 1 if cm.start > 1 else 0) + cm.start_col
        if before or after or source.in_body(offset):
            continue
        short = len(re.sub(r'[/\s*]', '', cm.text)) <= options['short_comment_chars']
        if cm.kind == 'line' or cm.text.startswith(('/**', '/*!')) or (short and cm.start != cm.end):
            yield cm.start, 'variable comment candidate: above declaration, ordinary /* */; short explanation on one line', ''
