"""Parse-boundary coverage: unsupported or incomplete source must surface as
T000 and exit 2, never silently pass (README: '2 表示输入/配置错误、无源码或解析不完整').
"""
import os
import unittest

from _support import LintCase, config_text


class ParseBoundaryTest(LintCase):
    """Each case proves the file is marked partial, T000 is emitted, exit=2."""

    def scan_json_with(self, rules=('T501',), extra=''):
        self.lint_config(config_text(scan=rules, extra=extra))
        return self.scan('--format', 'json')

    def assert_partial(self, p, name):
        self.assertEqual(p.returncode, 2, p.stderr + p.stdout)
        import json
        report = json.loads(p.stdout)
        self.assertIn(name, report['coverage']['partial_files'], report)
        t000 = [r for r in report['findings'] if r['rule'] == 'T000' and r['file'] == name]
        self.assertTrue(t000, report['findings'])
        return t000

    def test_unclosed_delimiter(self):
        self.put('bad.h', 'int f() {\n')
        self.assert_partial(self.scan_json_with(), 'bad.h')

    def test_unmatched_delimiter(self):
        self.put('bad.h', 'int f() { return 0; }}\n')
        self.assert_partial(self.scan_json_with(), 'bad.h')

    def test_unterminated_comment(self):
        self.put('bad.h', 'int a; /* never ends\nint b;\n')
        self.assert_partial(self.scan_json_with(), 'bad.h')

    def test_preprocessor_branch(self):
        self.put('bad.h', '#if defined(X)\nint a;\n#endif\n')
        self.assert_partial(self.scan_json_with(), 'bad.h')

    def test_function_macro(self):
        self.put('bad.h', '#define INC(x) ((x)+1)\nint a;\n')
        self.assert_partial(self.scan_json_with(), 'bad.h')

    def test_unsupported_union(self):
        self.put('bad.h', 'union U { int a; float b; };\n')
        self.assert_partial(self.scan_json_with(), 'bad.h')

    def test_braces_in_comment_ok(self):
        self.put('ok.h', '/* { } */\nint a;\n')
        p = self.scan_json_with()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_object_like_define_ok(self):
        self.put('ok.h', '#define MAX 10\nint a;\n')
        p = self.scan_json_with()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_symlink_source_not_followed(self):
        target = self.put('real.h', 'int real;\n')
        link = self.root / 'link.h'
        os.symlink(target, link)
        p = self.scan_json_with()
        self.assertEqual(p.returncode, 2)
        import json
        report = json.loads(p.stdout)
        self.assertIn('link.h', report['coverage']['partial_files'])
        t000 = [r for r in report['findings'] if r['file'] == 'link.h' and r['rule'] == 'T000']
        self.assertTrue(t000)
        self.assertIn('symlink', t000[0]['message'])

    def test_other_rules_skipped_for_invalid_source(self):
        """scan.py: non-T000 rules are skipped when source.valid is False."""
        self.put('bad.h', 'int ForTest { {\n')  # T601 name would match if it ran
        p = self.scan_json_with(rules=('T601',))
        self.assertEqual(p.returncode, 2)
        import json
        report = json.loads(p.stdout)
        self.assertEqual(self.findings(report, 'T601'), [])

    def test_no_source_files_is_partial(self):
        self.lint_config(config_text(scan=('T501',)))
        p = self.scan('--format', 'json')
        self.assertEqual(p.returncode, 2)
        import json
        report = json.loads(p.stdout)
        self.assertIn('.', report['coverage']['partial_files'])

    def test_empty_directory_scans_nothing(self):
        (self.root / 'empty').mkdir()
        self.put('real/a.h', 'int a;\n')
        self.lint_config(config_text(scan=('T501',)))
        p = self.scan('--format', 'json')
        self.assertEqual(p.returncode, 0, p.stderr)
        import json
        report = json.loads(p.stdout)
        self.assertEqual(report['coverage']['files_scanned'], 1)


if __name__ == '__main__':
    unittest.main()
