"""Run the same source checks over filesystem text or immutable Git blobs."""
from collections import Counter
from fnmatch import fnmatchcase
from cpp import Source
from configuration import rule_options
from registry import load_meta, load_check


class Scan:
    def __init__(self, root, config, rules):
        self.root, self.config = root, config
        self.rows, self.partial, self.excluded = [], set(), []
        self.files, self.suppressed = 0, Counter()
        self.checks = []
        for rule in dict.fromkeys(['T000', *rules]):
            meta = load_meta(rule)
            if meta['interface'] != 'cpp':
                raise ValueError(f'{rule}: this entry requires C++ source rules, not Git evidence checks')
            self.checks.append((rule, load_check(rule), rule_options(config, rule, meta)))

    def emit(self, path, line, rule, message, symbol=''):
        if rule == 'T000':
            self.partial.add(path)
        for item in self.config['exclude']:
            if (item['rule'] == rule and fnmatchcase(path, item['path'])
                    and fnmatchcase(symbol, item['symbol'])):
                self.suppressed[rule] += 1
                return
        self.rows.append({'file': path, 'line': line, 'rule': rule, 'severity': 'warn',
                          'symbol': symbol, 'message': message})

    def included(self, path):
        if any(fnmatchcase(path, mask) for mask in self.config['scope']['exclude']):
            self.excluded.append(path)
            return False
        return True

    def text(self, path, text, exists):
        self.files += 1
        source = Source(path, text, exists)
        for rule, check, options in self.checks:
            if rule != 'T000' and not source.valid:
                continue
            for line, message, symbol in check(source, options):
                if (type(line) is not int or line < 1 or not isinstance(message, str)
                        or not message or not isinstance(symbol, str)):
                    raise ValueError(f'{rule}: invalid finding tuple')
                self.emit(path, line, rule, message, symbol)

    def file(self, file):
        path = file.relative_to(self.root).as_posix()
        if not self.included(path):
            return
        if file.is_symlink():
            self.emit(path, 1, 'T000', 'incomplete: symlink source not followed')
            return
        try:
            text = file.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as error:
            self.emit(path, 1, 'T000', f'incomplete: {error}')
            return
        self.text(path, text, lambda p: (self.root / p).is_file())

    def report(self):
        return {'schema_version': 1, 'tool_version': '2', 'root': str(self.root), 'config': self.config,
                'coverage': {'mode': 'lexical_candidates_not_semantic_validation',
                             'files_scanned': self.files, 'partial_files': sorted(self.partial),
                             'excluded_files': self.excluded, 'suppressed': dict(self.suppressed)},
                'counts': dict(Counter(r['rule'] for r in self.rows)),
                'findings': sorted(self.rows, key=lambda r: (r['file'], r['line'], r['rule']))}
