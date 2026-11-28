"""nested-type-alias: 使用点显式模板嵌套达三层(含三层)须拆业务别名。

契约要点: 兄弟分支取最大、叶子/namespace/const/ref 不计层级、不用别名展开、
using/typedef 定义放过、注释/字符串/常见比较/模板函数调用不误计；规则默认开启，
显式空 scan.rules 不再启用。
"""
import unittest

from _support import LintCase, config_text

RULE = 'nested-type-alias'


class NestedTypeAliasTest(LintCase):
    def scan_rule(self, extra=''):
        self.lint_config(config_text(scan=(RULE,), extra=extra))
        return self.findings(self.scan_json(), RULE)

    def test_three_level_named_decls_warn(self):
        """字段/变量/参数/返回值等普通具名类型声明达到三层(含)即报，每处使用点一条。"""
        text = (
            'struct Ledger {\n'
            '  std::map<std::string, std::vector<std::pair<int, Entry>>> by_name;\n'
            '  std::vector<std::map<int, std::vector<Entry>>> per_day;\n'
            '  void load(const std::map<std::string, std::vector<std::pair<int, Entry>>>& rows);\n'
            '  std::map<std::string, std::vector<std::pair<int, Entry>>> snapshot() const;\n'
            '};\n'
        )
        self.put('a.h', text)
        rows = self.scan_rule()
        self.assertEqual(len(rows), 4, rows)
        self.assertEqual([r['line'] for r in rows], [2, 3, 4, 5])

    def test_two_levels_not_reported(self):
        """上边界阴性: 两层不触发; 兄弟分支都浅时取最大仍为两层。"""
        text = (
            'std::map<std::string, std::vector<int>> index;\n'
            'std::map<std::vector<int>, std::list<std::string>> routes;\n'
        )
        self.put('a.h', text)
        self.assertEqual(self.scan_rule(), [])

    def test_deep_sibling_drives_report(self):
        """分支取最大: 浅分支不救深分支, 且整条声明只报一次。"""
        self.put('a.h', 'std::map<std::vector<int>, '
                        'std::map<std::string, std::map<int, Task>>> plan;\n')
        rows = self.scan_rule()
        self.assertEqual(len(rows), 1, rows)

    def test_leaf_namespace_const_ref_do_not_count(self):
        """叶子类型、namespace 限定、const/引用不计入层级, 二层组合保持阴性。"""
        text = (
            'namespace ns { struct Widget {}; }\n'
            'std::vector<std::pair<const ns::Widget*, int>> slots;\n'
        )
        self.put('a.h', text)
        self.assertEqual(self.scan_rule(), [])

    def test_alias_definition_and_usage_not_reported(self):
        """using/typedef 定义本身放过; 使用点只写别名, 不展开别名找深层嵌套。"""
        text = (
            'using Ledger = std::map<std::string, std::vector<std::pair<int, Entry>>>;\n'
            'using Row = std::vector<std::pair<int, Entry>>;\n'
            'typedef std::map<std::string, Row> Ledger2;\n'
            'Ledger ledger;\n'
            'Ledger2 ledger2;\n'
        )
        self.put('a.h', text)
        self.assertEqual(self.scan_rule(), [])

    def test_multiline_decl_anchors_at_outer_template(self):
        """跨行声明: 结果锚定在最外层模板所在行, 不锚在收尾 >> 行。"""
        text = (
            'struct Cache {\n'
            '  std::map<\n'
            '      std::string,\n'
            '      std::vector<std::pair<int, CacheEntry>>> entries;\n'
            '};\n'
        )
        self.put('a.h', text)
        rows = self.scan_rule()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]['line'], 2)

    def test_default_on_empty_rules_disable(self):
        """默认开启: 普通扫描走默认集即命中; 显式 scan.rules=[] 不再启用。"""
        self.put('a.h', 'std::map<std::string, std::vector<std::pair<int, Entry>>> index;\n')
        report = self.scan_json()
        self.assertEqual(len(self.findings(report, RULE)), 1, report['findings'])
        self.lint_config(config_text(scan=()))
        report = self.scan_json()
        self.assertNotIn(RULE, report['counts'])
        self.assertEqual(self.findings(report, RULE), [])

    def test_noise_forms_not_counted(self):
        """注释、字符串、常见比较、模板函数调用本身不产生层级误计。"""
        text = (
            '// std::map<std::string, std::vector<std::pair<int, Entry>>> 注释示例\n'
            'const char* kHint = "map<vector<pair<int, Entry>>>";\n'
            'bool ok = a < b;\n'
            'auto it = lookup<int>(rows);\n'
            'std::map<int, int> plain;\n'
        )
        self.put('a.h', text)
        self.assertEqual(self.scan_rule(), [])


if __name__ == '__main__':
    unittest.main()
