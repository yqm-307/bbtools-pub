"""Config schema v2 validation and scan-scope behavior (README §一仓一份配置)."""
import json
import unittest

from _support import LintCase, config_text


class ConfigRejectTest(LintCase):
    """Bad config must exit 2 with a T000-style incomplete message on stderr."""

    def setUp(self):
        super().setUp()
        self.put('a.h', 'int a;\n')

    def assert_reject(self, text, needle=None):
        self.lint_config(text)
        p = self.scan()
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn('T000', p.stderr)
        if needle:
            self.assertIn(needle, p.stderr)

    def test_bad_schema_version(self):
        self.assert_reject(config_text().replace('schema_version = 2', 'schema_version = 3'),
                           'schema_version')

    def test_schema1_rejected_by_scan_entry(self):
        """Schema 1 belongs to the legacy hook config; scan needs schema 2."""
        self.assert_reject('schema_version = 1\n[scan]\nrules = ["T501"]\n')

    def test_unknown_rule_id(self):
        self.assert_reject(config_text(scan=('T999',)))

    def test_unknown_top_level_key(self):
        # bogus must sit at top level, before any section header
        text = 'schema_version = 2\nbogus = 1\n\n[scan]\nrules = ["T501"]\n[commit]\nrules = []\n[push]\nrules = []\n'
        self.assert_reject(text, 'unknown')

    def test_duplicate_rule_id(self):
        self.assert_reject(config_text(scan=('T501', 'T501')), 'duplicate')

    def test_git_only_rule_in_scan_rules_rejected(self):
        """README: 'Git 专用规则不加入 scan.rules；加入会返回 2'."""
        self.assert_reject(config_text(scan=('review-ticket',)))
        self.assert_reject(config_text(scan=('llm-review',)))
        # git-change rules are also not C++ source rules
        self.assert_reject(config_text(scan=('whitespace',)))

    def test_unknown_option_key_rejected(self):
        self.assert_reject(config_text(scan=('T101',),
                                       extra='[rules.T101]\noptions = { bogus = 3 }\n'))

    def test_non_positive_option_rejected(self):
        self.assert_reject(config_text(scan=('T101',),
                                       extra='[rules.T101]\noptions = { fields = 0 }\n'))

    def test_invalid_level_rejected(self):
        self.assert_reject(config_text(scan=('T101',),
                                       extra='[rules.T101]\nlevel = "fatal"\n'))

    def test_exclude_needs_all_four_keys(self):
        extra = ('[[exclude]]\nrule = "T501"\npath = "*"\nsymbol = "k*"\n')  # missing reason
        self.assert_reject(config_text(scan=('T501',), extra=extra))

    def test_t000_cannot_be_suppressed(self):
        extra = ('[[exclude]]\nrule = "T000"\npath = "*"\nsymbol = "*"\nreason = "x"\n')
        self.assert_reject(config_text(extra=extra), 'T000')

    def test_both_config_files_rejected(self):
        """README: '两个配置文件同时存在时报错，不做隐式合并' — enforced at hook layer."""
        self.lint_config(config_text())
        self.put('.config/bbt-git-hooks.toml', 'schema_version = 1\n')
        # scan entry itself only reads lint.toml; coexistence is a hook-layer error,
        # verified in test_hook_integration.py. Here we only assert scan still works.
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stderr)


class ScopeExcludeTest(LintCase):
    def test_scope_exclude_skips_files(self):
        self.put('src/keep.h', 'int kRpcV2A;\n')
        self.put('tests/skip.h', 'int kRpcV2B;\n')
        cfg = config_text(scan=('T501',), extra='[scope]\nexclude = ["tests/*", "*/tests/*"]\n')
        self.lint_config(cfg)
        report = self.scan_json()
        files = {r['file'] for r in self.findings(report, 'T501')}
        self.assertEqual(files, {'src/keep.h'})
        self.assertEqual(report['coverage']['excluded_files'], ['tests/skip.h'])

    def test_scope_exclude_in_hook_scope_is_also_reported(self):
        self.put('gen.pb.h', 'int kRpcV2A;\n')
        self.put('keep.h', 'int clean;\n')
        cfg = config_text(scan=('T501',), extra='[scope]\nexclude = ["*.pb.h"]\n')
        self.lint_config(cfg)
        report = self.scan_json()
        self.assertEqual(self.findings(report, 'T501'), [])
        self.assertIn('gen.pb.h', report['coverage']['excluded_files'])


class ScanEntryTest(LintCase):
    def test_missing_root_is_error(self):
        p = self.run_cmd(__import__('sys').executable, '-I',
                         str(self.tools / 'lint/lint.py'),
                         '--root', str(self.root / 'nonexistent'))
        self.assertEqual(p.returncode, 2)

    def test_text_output_shape(self):
        self.put('a.h', 'int kRpcV2A;\n')
        self.lint_config(config_text(scan=('T501',)))
        p = self.scan()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertRegex(p.stdout, r'a\.h:1 T501 warn .*kRpcV2A')
        self.assertIn('files=1', p.stderr)
        # Warnings alone must not fail the scan (README: 即使有告警也不返回 1).
        self.assertNotEqual(p.returncode, 1)

    def test_default_scan_rules_from_meta(self):
        """Omitting [scan].rules discovers default_enabled rules."""
        self.put('a.h', 'int kRpcV2A;\n')
        self.lint_config('schema_version = 2\n')
        report = self.scan_json()
        self.assertIn('T501', report['config']['scan']['rules'])
        self.assertNotIn('T202', report['config']['scan']['rules'])

    def test_auto_discovery_of_config(self):
        """lint.py finds .config/lint.toml walking up from --root."""
        self.put('sub/a.h', 'int kRpcV2A;\n')
        self.lint_config(config_text(scan=('T501',)))
        p = self.run_cmd(__import__('sys').executable, '-I',
                         str(self.tools / 'lint/lint.py'),
                         '--root', str(self.root), '--format', 'json')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('kRpcV2A', p.stdout)


if __name__ == '__main__':
    unittest.main()
