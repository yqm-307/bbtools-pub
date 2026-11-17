from cpp import HEADERS


def check(source, options):
    if source.path.suffix not in HEADERS and not any(source.exists(source.path.with_suffix(ext)) for ext in HEADERS):
        yield 1, 'candidate implementation has no same-directory same-stem header', source.path.stem
