"""Scan-mode rule behavior: positive/negative per rule, contract-based expectations."""
import json
import unittest

from _support import LintCase, config_text


def fields(n, access='public', const=False):
    decl = 'const int' if const else 'int'
    lines = [f'{decl} f{i};' for i in range(n)]
    if access == 'public':
        return 'struct Big {\npublic:\n' + '\n'.join(f'  {x}' for x in lines) + '\n};\n'
    return 'class Big {\n' + '\n'.join(f'  {x}' for x in lines) + '\npublic:\n  void op();\n};\n'


class T101Test(LintCase):
    """T101: fields > threshold AND at least one public mutable field (README §T101)."""

    def scan_t101(self, extra=''):
        self.lint_config(config_text(scan=('T101',), extra=extra))
        return self.scan_json()

    def test_public_mutable_over_threshold_warns(self):
        self.put('a.h', fields(11))
        rows = self.findings(self.scan_t101(), 'T101')
        self.assertEqual(len(rows), 1, rows)
        self.assertIn('Big', rows[0]['symbol'])
        self.assertIn('public_mutable_fields=11', rows[0]['message'])

    def test_all_private_fields_not_reported(self):
        self.put('a.h', fields(12, access='private'))
        self.assertEqual(self.findings(self.scan_t101(), 'T101'), [])

    def test_at_threshold_not_reported(self):
        self.put('a.h', fields(10))
        self.assertEqual(self.findings(self.scan_t101(), 'T101'), [])

    def test_const_public_fields_not_mutable(self):
        self.put('a.h', fields(11, const=True))
        self.assertEqual(self.findings(self.scan_t101(), 'T101'), [])

    def test_threshold_option_override(self):
        self.put('a.h', fields(6))
        extra = '[rules.T101]\noptions = { fields = 5 }\n'
        rows = self.findings(self.scan_t101(extra), 'T101')
        self.assertEqual(len(rows), 1, rows)
        self.assertIn('fields=6', rows[0]['message'])

    def test_fields_count_includes_private(self):
        """README 覆盖边界: T101 的字段数包含私有字段, 触发需公开可变字段."""
        text = ('struct Big {\npublic:\n  int pub0;\n  int pub1;\nprivate:\n'
                + '\n'.join(f'  int p{i};' for i in range(9)) + '\n};\n')
        self.put('a.h', text)
        rows = self.findings(self.scan_t101(), 'T101')
        self.assertEqual(len(rows), 1, rows)
        self.assertIn('fields=11', rows[0]['message'])
        self.assertIn('public_mutable_fields=2', rows[0]['message'])


class T102Test(LintCase):
    def test_member_lock_warns(self):
        self.put('a.cc', 'void f() {\n  std::lock_guard<std::mutex> g(this->mu_);\n}\n')
        self.lint_config(config_text(scan=('T102',)))
        rows = self.findings(self.scan_json(), 'T102')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['symbol'], 'mu_')

    def test_local_lock_not_reported(self):
        self.put('a.cc', 'void f() {\n  std::lock_guard<std::mutex> g(local_mutex);\n}\n')
        self.lint_config(config_text(scan=('T102',)))
        self.assertEqual(self.findings(self.scan_json(), 'T102'), [])


class T201Test(LintCase):
    """T201: comments above variable declarations only; skip in-body and inline."""

    def scan_t201(self, extra=''):
        self.lint_config(config_text(scan=('T201',), extra=extra))
        return self.scan_json()

    def test_line_comment_above_variable_warns(self):
        self.put('a.h', '// 数量上限。\nint limit{0};\n')
        rows = self.findings(self.scan_t201(), 'T201')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['line'], 1)

    def test_block_comment_above_variable_ok(self):
        self.put('a.h', '/* 数量上限。 */\nint limit{0};\n')
        self.assertEqual(self.findings(self.scan_t201(), 'T201'), [])

    def test_doxygen_style_above_variable_warns(self):
        self.put('a.h', '/** 数量上限。 */\nint limit{0};\n')
        rows = self.findings(self.scan_t201(), 'T201')
        self.assertEqual(len(rows), 1)

    def test_comment_inside_function_body_skipped(self):
        self.put('a.h', 'int f() {\n  // 内部说明\n  int x = 1;\n  return x;\n}\n')
        self.assertEqual(self.findings(self.scan_t201(), 'T201'), [])

    def test_trailing_comment_skipped(self):
        self.put('a.h', 'int x; // 尾注释\n')
        self.assertEqual(self.findings(self.scan_t201(), 'T201'), [])


class T202Test(LintCase):
    """T202: default_enabled=false in meta; only runs when added to scan.rules."""

    def test_default_off_not_in_default_set(self):
        self.put('a.h', '/* 数量。 */\nint limit{0};\n')
        # No [scan].rules -> defaults() from meta default_enabled
        p = self.scan_json()
        self.assertNotIn('T202', p['counts'])
        self.assertEqual(self.findings(p, 'T202'), [])

    def test_enabled_reports_short_variable_comment(self):
        self.put('a.h', '/* 数量。 */\nint limit{0};\n')
        self.lint_config(config_text(scan=('T202',)))
        rows = self.findings(self.scan_json(), 'T202')
        self.assertEqual(len(rows), 1)


class T301Test(LintCase):
    def test_long_file_warns(self):
        self.put('a.cc', '\n'.join(f'int x{i};' for i in range(11)) + '\n')
        self.lint_config(config_text(scan=('T301',),
                                     extra='[rules.T301]\noptions = { file_lines = 10 }\n'))
        rows = self.findings(self.scan_json(), 'T301')
        self.assertEqual(len(rows), 1)
        self.assertIn('11', rows[0]['message'])

    def test_short_file_ok(self):
        self.put('a.cc', 'int x;\n')
        self.lint_config(config_text(scan=('T301',)))
        self.assertEqual(self.findings(self.scan_json(), 'T301'), [])


class T302Test(LintCase):
    def test_stem_mismatch_warns(self):
        self.put('mismatch.h', 'struct Other {};\n')
        self.lint_config(config_text(scan=('T302',)))
        rows = self.findings(self.scan_json(), 'T302')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['symbol'], 'mismatch')

    def test_stem_match_ok(self):
        self.put('match.h', 'struct match {};\n')
        self.lint_config(config_text(scan=('T302',)))
        self.assertEqual(self.findings(self.scan_json(), 'T302'), [])

    def test_implementation_file_not_checked(self):
        self.put('impl.cc', 'struct Other {};\n')
        self.lint_config(config_text(scan=('T302',)))
        self.assertEqual(self.findings(self.scan_json(), 'T302'), [])


class T303Test(LintCase):
    def test_implementation_without_header_warns(self):
        self.put('alone.cc', 'int alone() { return 0; }\n')
        self.lint_config(config_text(scan=('T303',)))
        rows = self.findings(self.scan_json(), 'T303')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['symbol'], 'alone')

    def test_implementation_with_header_ok(self):
        self.put('paired.cc', 'int paired() { return 0; }\n')
        self.put('paired.h', 'int paired();\n')
        self.lint_config(config_text(scan=('T303',)))
        self.assertEqual(self.findings(self.scan_json(), 'T303'), [])


class T304Test(LintCase):
    def test_mixed_header_warns(self):
        text = ('constexpr int K = 1;\n'
                'struct A { int x; };\n'
                'struct B { int y; };\n'
                'int free_fn();\n')
        self.put('mixed.h', text)
        self.lint_config(config_text(scan=('T304',)))
        rows = self.findings(self.scan_json(), 'T304')
        self.assertEqual(len(rows), 1)

    def test_single_type_header_ok(self):
        self.put('single.h', 'struct A { int x; };\n')
        self.lint_config(config_text(scan=('T304',)))
        self.assertEqual(self.findings(self.scan_json(), 'T304'), [])


class T401Test(LintCase):
    def test_static_forwarder_shell_warns(self):
        text = ('struct Sh {\n'
                '  static int a() { return Impl::a(); }\n'
                '  static int b() { return Impl::b(); }\n'
                '};\n')
        self.put('sh.h', text)
        self.lint_config(config_text(scan=('T401',)))
        rows = self.findings(self.scan_json(), 'T401')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['symbol'], 'Sh')

    def test_single_forwarder_not_reported(self):
        self.put('one.h', 'struct One {\n  static int a() { return Impl::a(); }\n};\n')
        self.lint_config(config_text(scan=('T401',)))
        self.assertEqual(self.findings(self.scan_json(), 'T401'), [])

    def test_class_with_fields_not_reported(self):
        text = ('struct Has {\n  int x;\n'
                '  static int a() { return Impl::a(); }\n'
                '  static int b() { return Impl::b(); }\n};\n')
        self.put('has.h', text)
        self.lint_config(config_text(scan=('T401',)))
        self.assertEqual(self.findings(self.scan_json(), 'T401'), [])

    def test_non_forwarding_static_not_reported(self):
        text = ('struct N {\n'
                '  static int a() { return 1; }\n'
                '  static int b() { int v = f(); return v + 1; }\n};\n')
        self.put('n.h', text)
        self.lint_config(config_text(scan=('T401',)))
        self.assertEqual(self.findings(self.scan_json(), 'T401'), [])


class T501Test(LintCase):
    def test_v2_identifier_warns(self):
        self.put('a.h', 'int kRpcV2Timeout;\n')
        self.lint_config(config_text(scan=('T501',)))
        rows = self.findings(self.scan_json(), 'T501')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['symbol'], 'kRpcV2Timeout')

    def test_plain_identifier_ok(self):
        self.put('a.h', 'int kTimeout;\n')
        self.lint_config(config_text(scan=('T501',)))
        self.assertEqual(self.findings(self.scan_json(), 'T501'), [])

    def test_exclude_symbol_suppression(self):
        """[[exclude]] rule/path/symbol/reason suppresses matching candidates."""
        self.put('a.h', 'int kRpcV2Timeout;\nint kOtherV2Name;\n')
        extra = ('[[exclude]]\nrule = "T501"\npath = "*"\nsymbol = "kRpcV2*"\n'
                 'reason = "public RPC contract"\n')
        self.lint_config(config_text(scan=('T501',), extra=extra))
        report = self.scan_json()
        rows = self.findings(report, 'T501')
        self.assertEqual([r['symbol'] for r in rows], ['kOtherV2Name'])
        self.assertEqual(report['coverage']['suppressed'], {'T501': 1})


class T601Test(LintCase):
    def test_test_seam_warns(self):
        self.put('a.h', 'int ForTestOnly();\n')
        self.lint_config(config_text(scan=('T601',)))
        rows = self.findings(self.scan_json(), 'T601')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['symbol'], 'ForTestOnly')

    def test_clean_identifier_ok(self):
        self.put('a.h', 'int RegularName();\n')
        self.lint_config(config_text(scan=('T601',)))
        self.assertEqual(self.findings(self.scan_json(), 'T601'), [])


if __name__ == '__main__':
    unittest.main()
