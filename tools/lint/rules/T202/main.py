import re


def check(source, options):
    for cm, _, _ in source.variable_comments():
        if len(re.sub(r'[/\s*]', '', cm.text)) <= options['short_comment_chars']:
            yield cm.start, 'candidate only: check redundant name translation; retain special values/range/order/ownership/lifetime', ''
