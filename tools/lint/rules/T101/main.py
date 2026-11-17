from cpp import mutable_field


def check(source, options):
    for c in source.classes:
        fields = c['fields']
        exposed = sum(e.access == 'public' and mutable_field(e.signature) for e in fields)
        if exposed and len(fields) > options['fields']:
            public = sum(e.access == 'public' for e in c['operations'])
            yield source.line(c['start']), (f"candidate {c['name']}: fields={len(fields)}, "
                f"public_operations={public}, public_mutable_fields={exposed}; "
                'review invariants or explicit value-record exception'), c['name']
