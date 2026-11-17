def check(source, options):
    count = len(source.text.splitlines())
    if count > options['file_lines']:
        yield 1, f'candidate {count} lines > {options["file_lines"]}; review responsibilities', ''
