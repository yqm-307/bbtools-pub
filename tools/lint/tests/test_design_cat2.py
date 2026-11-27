"""2 边界与依赖（2.1–2.5）的冻结预期（T2，来源：映射 §1.2 五行 + §4.5）。

2.1/2.2 为可定类：边界声明与禁边声明在夹具配置中显式给出（T2 声明的按键输入
契约，见 design_fixtures.py 文件头），缺失时 uncovered。2.4 为历史项，用自有
临时仓 + --baseline（GitCase，不触碰真实远端）。
"""
import unittest

from design_fixtures import DesignCase, DesignGitCase, expected_contract_ref

CFG_21_FULL = ('[design."2.1"]\n'
               'private = ["runtime/internal/*.h"]\n'
               'allow = ["runtime/internal/test_support.h"]\n'
               '[design."2.1".targets]\n'
               '"app/*" = "app"\n'
               '"runtime/*" = "runtime"\n')
BAD_21 = {'app/client.cc':
          '#include "runtime/internal/poller.h"\nint main() { return poll(); }\n',
          'runtime/internal/poller.h': 'int poll();\n'}
LEGAL_21 = {
    'runtime/own.cc': '#include "runtime/internal/poller.h"\nvoid own() { poll(); }\n',
    'tests/ts.cc': '#include "runtime/internal/test_support.h"\nvoid ts() { support(); }\n',
    'app/client_bad.cc': BAD_21['app/client.cc'],
    'runtime/internal/poller.h': 'int poll();\n',
    'runtime/internal/test_support.h': 'void support();\n',
}
CFG_21_NO_DECL = ('[design."2.1".targets]\n'
                  '"app/*" = "app"\n'
                  '"runtime/*" = "runtime"\n')
CFG_21_NO_TARGETS = ('[design."2.1"]\n'
                     'private = ["runtime/internal/*.h"]\n'
                     'allow = ["runtime/internal/test_support.h"]\n')

CFG_22_FULL = ('[design."2.2".graph]\n'
               'targets = { "core/*" = "core", "app/*" = "app", "asm/*" = "assemble" }\n'
               'forbidden = [["core", "app"]]\n'
               'assembly = ["assemble"]\n')
BAD_22 = {'core/impl.cc': '#include "app/api.h"\nvoid core_fn() { app_fn(); }\n',
          'app/api.h': 'void app_fn();\n'}
LEGAL_22 = {
    'asm/main.cc': ('#include "core/util.h"\n#include "app/api.h"\n'
                    'void assemble() { core_fn(); app_fn(); }\n'),
    'core/impl_bad.cc': BAD_22['core/impl.cc'],
    'core/util.h': 'void core_fn();\n',
    'app/api.h': 'void app_fn();\n',
}
CFG_22_NO_GRAPH = ''
CFG_22_NO_FORBIDDEN = ('[design."2.2".graph]\n'
                       'targets = { "core/*" = "core", "app/*" = "app", "asm/*" = "assemble" }\n'
                       'assembly = ["assemble"]\n')

BAD_23 = {'shell.h': ('struct Impl { static int a() { return 1; } static int b() { return 2; } };\n'
                      'class Sh {\n'
                      '  friend int caller();\n'
                      '  static int a() { return Impl::a(); }\n'
                      '  static int b() { return Impl::b(); }\n'
                      '};\n'),
          'user.cc': ('#include "shell.h"\n'
                      'int caller() { return Sh::a() + Sh::b(); }  // 可定位的实际调用方（§2.3 收紧）\n')}
LEGAL_23 = {
    'gate.h': ('#include <string_view>\n'
               'struct Impl { static int a() { return 1; } static int b() { return 2; } };\n'
               'void require(std::string_view tok);\n'
               'struct Gate {\n'
               '  static int a(std::string_view tok) { require(tok); return Impl::a(); }  // 权限检查后转发\n'
               '  static int b(std::string_view tok) { require(tok); return Impl::b(); }\n'
               '};\n'
               'int gate_user() { return Gate::a("t") + Gate::b("t"); }\n'),
    'shell_bad.h': BAD_23['shell.h'],
    'user.cc': ('#include "shell_bad.h"\n'
                'int caller() { return Sh::a() + Sh::b(); }  // 可定位的实际调用方（§2.3 收紧）\n'),
}
MISSING_23 = {'macro_shell.h': ('#define FWD(name) static int name() { return Impl::name(); }\n'
                                'struct Msh { FWD(a) FWD(b) };\n')}

MAP_A = ('// Op → 处理器映射（模块 A）\n'
         'const char* handler_a(int op) {\n'
         '  switch (op) {\n'
         '    case 1: return "read";\n'
         '    case 2: return "write";\n'
         '  }\n'
         '  return "?";\n'
         '}\n')
MAP_B = MAP_A.replace('handler_a', 'handler_b').replace('模块 A', '模块 B')
MAP_C = MAP_A.replace('handler_a', 'handler_c').replace('模块 A', '模块 C')
MAP_D = MAP_A.replace('handler_a', 'handler_d').replace('模块 A', '模块 D')
TEST_A = ('// 独立验收：模块 A 映射的独立测试\n'
          'bool test_handler_a_has_close() { return handler_a(3) == std::string_view("close"); }\n')

BAD_25 = {'registry.cc': (
    '#include <memory>\n#include <string>\n'
    'struct Policy { virtual int pick(int) = 0; };\n'
    'struct DefaultPolicy final : Policy { int pick(int x) override { return x; } };\n'
    'struct Registry {\n  void add(std::string name, std::unique_ptr<Policy> p);\n'
    '  Policy* get(std::string name);\n};\n'
    'Registry& registry() { static Registry r; r.add("default", std::make_unique<DefaultPolicy>()); return r; }\n'
    'int use(int x) { return registry().get("default")->pick(x); }  // 无变化需求仍先装配注册表\n')}
LEGAL_25 = {
    'plugin.cc': BAD_25['registry.cc'].replace(
        'struct Policy { virtual int pick(int) = 0; };',
        '// 契约：Policy 为对外插件契约（docs/plugins.md:12），仓外实现经注册接入。\n'
        'struct Policy { virtual int pick(int) = 0; };'),
    'registry_bad.cc': BAD_25['registry.cc'],
}
MISSING_25 = {'dynamic.cc': (
    'struct Registry {\n  void add_from_plugin(const char* env);  // 动态注册，实现集不可见\n};\n'
    'void setup(Registry& r) { r.add_from_plugin(getenv("POLICY_DIR")); }\n')}


class PrivateHeaderBoundary(DesignCase):
    """2.1：可定类——边界声明 + 目标归属齐全才判 violation。"""

    def test_bad_violation_with_contract_ref(self):
        root = self.put_tree(BAD_21)
        cfg = self.put_design_config(rules=('2.1',), extra=CFG_21_FULL, root=root)
        p, rep = self.design_report(ctx='bad/2.1', keys=('2.1',), root=root)
        self.assertEqual(p.returncode, 0, 'violation 不阻断（首版只报告）')
        self.expect_status(rep, '2.1', 'violation', 'bad/2.1')
        row = self.one_finding(rep, '2.1', 'bad/2.1')
        facts = self.expect_facts(row, '2.1', 'bad/2.1')
        self.assertEqual(facts['resolved_header'], 'runtime/internal/poller.h',
                         '解析后的头（§2.1）')
        self.assertEqual(facts['including_target'], 'app', '引用者目标')
        self.assertFalse(facts['exception_match'], '非获准例外')
        expected = expected_contract_ref(cfg, 'private = ', '.config/lint.toml')
        self.assert_contract_ref(row, expected, 'private', 'bad/2.1')

    def test_same_component_and_allowed_header_not_reported(self):
        """§2.1 例外：同组件内部与精确放行的测试支持头不报；哨兵仍 violation。"""
        root = self.put_tree(LEGAL_21)
        self.put_design_config(rules=('2.1',), extra=CFG_21_FULL, root=root)
        p, rep = self.design_report(ctx='legal/2.1', keys=('2.1',), root=root)
        rows = self.findings_for(rep, '2.1')
        self.assertEqual([r['file'] for r in rows], ['app/client_bad.cc'], '只有哨兵被报')
        self.expect_status(rep, '2.1', 'violation', 'legal/2.1')

    def test_no_boundary_decl_uncovered(self):
        root = self.put_tree(BAD_21)
        self.put_design_config(rules=('2.1',), extra=CFG_21_NO_DECL, root=root)
        p, rep = self.design_report(ctx='NO_BOUNDARY_DECL/2.1', keys=('2.1',), root=root)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '2.1', 'uncovered', 'NO_BOUNDARY_DECL/2.1')
        self.expect_missing_code(rep, '2.1', 'NO_BOUNDARY_DECL', 'NO_BOUNDARY_DECL/2.1')

    def test_target_unknown_uncovered(self):
        root = self.put_tree(BAD_21)
        self.put_design_config(rules=('2.1',), extra=CFG_21_NO_TARGETS, root=root)
        p, rep = self.design_report(ctx='TARGET_UNKNOWN/2.1', keys=('2.1',), root=root)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '2.1', 'uncovered', 'TARGET_UNKNOWN/2.1')
        self.expect_missing_code(rep, '2.1', 'TARGET_UNKNOWN', 'TARGET_UNKNOWN/2.1')


class LowerDependsUpper(DesignCase):
    """2.2：可定类——声明禁边后查目标图，不按目录名猜层级。"""

    def test_bad_violation_with_declared_edge(self):
        root = self.put_tree(BAD_22)
        cfg = self.put_design_config(rules=('2.2',), extra=CFG_22_FULL, root=root)
        p, rep = self.design_report(ctx='bad/2.2', keys=('2.2',), root=root)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '2.2', 'violation', 'bad/2.2')
        row = self.one_finding(rep, '2.2', 'bad/2.2')
        facts = self.expect_facts(row, '2.2', 'bad/2.2')
        self.assertTrue(facts['violating_edges'], '违反的边列表非空')
        self.assertFalse(facts['assembly_exception'], '非装配例外')
        expected = expected_contract_ref(cfg, 'forbidden = ', '.config/lint.toml')
        self.assert_contract_ref(row, expected, 'forbidden', 'bad/2.2')

    def test_assembly_target_not_reported(self):
        """§2.2 例外：装配目标从上向下引用二者不报；哨兵仍 violation。"""
        root = self.put_tree(LEGAL_22)
        self.put_design_config(rules=('2.2',), extra=CFG_22_FULL, root=root)
        p, rep = self.design_report(ctx='legal/2.2', keys=('2.2',), root=root)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '2.2')],
                         ['core/impl_bad.cc'], '只有哨兵被报')

    def test_no_target_graph_uncovered(self):
        root = self.put_tree(BAD_22)
        self.put_design_config(rules=('2.2',), extra=CFG_22_NO_GRAPH, root=root)
        p, rep = self.design_report(ctx='NO_TARGET_GRAPH/2.2', keys=('2.2',), root=root)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '2.2', 'uncovered', 'NO_TARGET_GRAPH/2.2')
        self.expect_missing_code(rep, '2.2', 'NO_TARGET_GRAPH', 'NO_TARGET_GRAPH/2.2')

    def test_no_forbidden_decl_uncovered(self):
        """「无禁边声明 → 不能判」定型为 uncovered/NO_CONTRACT（0.5 C 类缺失）。"""
        root = self.put_tree(BAD_22)
        self.put_design_config(rules=('2.2',), extra=CFG_22_NO_FORBIDDEN, root=root)
        p, rep = self.design_report(ctx='NO_CONTRACT/2.2', keys=('2.2',), root=root)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '2.2', 'uncovered', 'NO_CONTRACT/2.2')
        self.expect_missing_code(rep, '2.2', 'NO_CONTRACT', 'NO_CONTRACT/2.2')


class ProfitlessForwarder(DesignCase):
    """2.3：线索类，复用 T401 形状；价值人工判。"""

    def test_bad_candidate_with_chain_facts(self):
        p, rep, _ = self.one('2.3', BAD_23)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '2.3', 'candidate', 'bad/2.3')
        row = self.one_finding(rep, '2.3', 'bad/2.3')
        facts = self.expect_facts(row, '2.3', 'bad/2.3')
        self.assertTrue(facts['t401_candidate'], 'T401 形状事实（§2.3）')
        self.assertTrue(facts['chain'], '转发链事实非空')
        self.assertIsNone(row.get('contract_ref'), '线索项 contract_ref 可为 null')

    def test_permission_changed_forwarder_not_reported(self):
        """§2.3 例外：参数/行为/权限有变化的转发不报；哨兵仍报。"""
        p, rep, _ = self.one('2.3', LEGAL_23)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '2.3')],
                         ['shell_bad.h'], '只有哨兵被报')

    def test_macro_forwarders_chain_unresolved(self):
        """§2.3 缺输入：宏生成转发 → candidate/CHAIN_UNRESOLVED（线索降级不判死）。"""
        p, rep, _ = self.one('2.3', MISSING_23)
        self.assertEqual(p.returncode, 0, '降级候选不强制 exit 2')
        self.expect_status(rep, '2.3', 'candidate', 'CHAIN_UNRESOLVED/2.3')
        self.expect_missing_code(rep, '2.3', 'CHAIN_UNRESOLVED', 'CHAIN_UNRESOLVED/2.3')


class MultiModuleChange(DesignGitCase):
    """2.4：人工类 + 历史项。对照变更历史，单次 diff 不判。"""

    def setUp(self):
        super().setUp()
        self.put_repo_tree({'src/map_a.cc': MAP_A, 'src/map_b.cc': MAP_B})
        self.put_repo_config(manual=('2.4',))
        self.git('add', '.')
        self.git('commit', '-qm', 'base mappings')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()

    def test_bad_manual_pending_with_change_set(self):
        self.put_repo_tree({
            'src/map_a.cc': MAP_A.replace('  }\n  return "?";',
                                          '    case 3: return "close";\n  }\n  return "?";'),
            'src/map_b.cc': MAP_B.replace('  }\n  return "?";',
                                          '    case 3: return "close";\n  }\n  return "?";'),
        })
        self.git('add', '.')
        self.git('commit', '-qm', 'add close op to both maps')
        p, rep = self.design_report(ctx='bad/2.4', keys=('2.4',), baseline=self.base)
        self.assertEqual(p.returncode, 0, 'manual_pending 不强制 exit 2')
        self.expect_status(rep, '2.4', 'manual_pending', 'bad/2.4')
        row = self.one_finding(rep, '2.4', 'bad/2.4')
        facts = self.expect_facts(row, '2.4', 'bad/2.4')
        self.assertTrue(facts['change_set'], '变更集事实（§2.4）')
        self.assertTrue(facts['mapping_duplicates'], '同表双写候选')
        self.expect_manual_pending(rep, '2.4', 'bad/2.4')

    def test_cochange_with_independent_test_not_reported(self):
        """§2.4 例外：实现与独立验收测试随需求同改；同树重复知识哨兵仍出包。"""
        self.put_repo_tree({
            'src/map_a.cc': MAP_A.replace('  }\n  return "?";',
                                          '    case 3: return "close";\n  }\n  return "?";'),
            'src/test_map_a.cc': TEST_A,
            'src/map_c.cc': MAP_C.replace('  }\n  return "?";',
                                          '    case 3: return "close";\n  }\n  return "?";'),
            'src/map_d.cc': MAP_D.replace('  }\n  return "?";',
                                          '    case 3: return "close";\n  }\n  return "?";'),
        })
        self.git('add', '.')
        self.git('commit', '-qm', 'close op: a+test pair, c+d duplicate')
        p, rep = self.design_report(ctx='legal/2.4', keys=('2.4',), baseline=self.base)
        self.expect_status(rep, '2.4', 'manual_pending', 'legal/2.4')
        rows = self.findings_for(rep, '2.4')
        self.assertTrue(rows, '重复知识哨兵仍出包')
        self.assertFalse(any('test_map_a' in r['file'] for r in rows),
                         '实现+独立测试的必要协作不是候选')
        self.assertTrue(any('map_c' in r['file'] or 'map_d' in r['file'] for r in rows),
                         '哨兵重复对仍在候选里')

    def test_no_baseline_uncovered_exit2(self):
        """§4.1：历史项被选中但未给 --baseline → uncovered/NO_BASELINE，exit 2。"""
        p, rep = self.design_report(ctx='NO_BASELINE/2.4', keys=('2.4',))
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '2.4', 'uncovered', 'NO_BASELINE/2.4')
        self.expect_missing_code(rep, '2.4', 'NO_BASELINE', 'NO_BASELINE/2.4')


class SpeculativeExtensionPoint(DesignCase):
    """2.5：人工类——查消费者和承诺，不按实现个数判。"""

    def test_bad_manual_pending(self):
        p, rep, _ = self.one('2.5', BAD_25, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '2.5', 'manual_pending', 'bad/2.5')
        facts = self.expect_facts(self.one_finding(rep, '2.5', 'bad/2.5'), '2.5', 'bad/2.5')
        self.assertIsNotNone(facts['extension_point'], '扩展点事实（§2.5）')
        self.assertTrue(facts['implementations'], '实现集非空')
        self.assertIsNone(facts['promise_ref'], '无承诺文档')
        self.expect_manual_pending(rep, '2.5', 'bad/2.5')
        self.expect_missing_code(rep, '2.5', 'NO_CONTRACT', 'bad/2.5')
        self.expect_missing_code(rep, '2.5', 'EXTERNAL_UNKNOWN', 'bad/2.5')

    def test_declared_plugin_contract_not_reported(self):
        """§2.5 例外：已有对外插件契约不作为候选；哨兵仍出包。"""
        p, rep, _ = self.one('2.5', LEGAL_25, manual=True)
        self.expect_status(rep, '2.5', 'manual_pending', 'legal/2.5')
        rows = self.findings_for(rep, '2.5')
        self.assertTrue(rows, '哨兵仍出包')
        self.assertFalse(any(f['file'] == 'plugin.cc' for f in rows),
                         '有承诺文档的注册表不产生候选')

    def test_registry_partial(self):
        """行内裸码 REGISTRY_PARTIAL 在人工行 → manual_pending（随 2.5/5.3 同码成对）。"""
        p, rep, _ = self.one('2.5', MISSING_25, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '2.5', 'manual_pending', 'REGISTRY/2.5')
        self.expect_missing_code(rep, '2.5', 'REGISTRY_PARTIAL', 'REGISTRY/2.5')


if __name__ == '__main__':
    unittest.main()
