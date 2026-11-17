import re


def check(source, options):
    for c in source.classes:
        operations = c['operations']
        if (not c['fields'] and len(operations) >= options['forwarders']
                and all('static' in e.signature.split() and e.body is not None
                        and re.fullmatch(r'\s*(?:return\s+)?[\w:.>\-]+\([^;{}]*\);\s*', e.body)
                        for e in operations)):
            yield source.line(c['start']), f"candidate {c['name']}: {len(operations)} static single-call methods; verify contract value", c['name']
