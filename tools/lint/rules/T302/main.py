from cpp import HEADERS


def check(source, options):
    top = source.top_classes()
    if source.path.suffix in HEADERS and top and source.path.stem not in [c['name'] for c in top]:
        yield source.line(top[0]['start']), 'candidate file stem matches no defined top-level class/struct', source.path.stem
