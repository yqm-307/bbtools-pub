"""5 演进与删除（5.1–5.4）的冻结预期（T2，来源：映射 §1.5 四行 + §4.5）。

5.1 复用既有 ``retired-symbol``（[[retired]] 声明 + --baseline）；5.2/5.3 为历史项，
用自有临时仓构造基线（GitCase，不触碰真实远端）。
"""
import unittest

from design_fixtures import DesignCase, DesignGitCase, expected_contract_ref

RETIRED_CFG = ('[[retired]]\npath = "src/**"\nsymbols = ["old_api"]\n')

BAD_51 = {'src/new.cc': 'int wrap() { return old_api(); }  // 退役拼写重新出现\n'}
LEGAL_51 = {
    'src/doc.cc': '// 迁移说明：old_api 已退役，新代码请走 new_api（注释不判违规）。\n',
    'src/bad.cc': BAD_51['src/new.cc']}

BAD_52 = {
    'src/billing.cc': 'constexpr int kMaxRetry = 3;  // 协议默认：最大重试 3 次\n',
    'src/net.cc': 'constexpr int kMaxRetry = 3;  // 协议默认：最大重试 3 次\n'}
LEGAL_52 = {
    'src/a.cc': 'constexpr int kTimeoutA = 3;  // 独立策略：A 链路超时秒数\n',
    'src/b.cc': 'constexpr int kTimeoutB = 3;  // 独立策略：B 链路超时秒数\n',
    'src/billing_bad.cc': BAD_52['src/billing.cc'],
    'src/net_bad.cc': BAD_52['src/net.cc']}

BAD_53 = {'src/legacy_impl.cc': (
    '#include <string>\n'
    'int old_step(int x) { return x + 1; }  // 仓内零文本引用\n'
    'std::string legacy_name() { return "legacy"; }\n'),
    'src/main.cc': 'int main() { return 0; }  // 与旧实现无引用关系\n'}
LEGAL_53 = {
    'src/exported.cc': (
        '// ABI 导出：外部插件经符号 legacy_entry 动态加载（仓外消费边界声明）。\n'
        'int legacy_entry(int x) { return x; }\n'),
    'src/legacy_bad.cc': BAD_53['src/legacy_impl.cc']}
MISSING_53 = {'src/loader.cc': (
    'void register_via_loader(const char* name);  // 动态注册，仓内不可见\n'
    'void setup() { register_via_loader("legacy_entry"); }\n')}

MIGRATION_DOC = ('# 迁移契约\n\n'
                 'HandlerV2 与 Handler 并行；退出条件：仓内 Handler 调用点清零（2026-Q2 评审）。\n')
CFG_54 = '[design."5.4"]\ncontract_file = "docs/migration.md"\n'
BAD_54 = {
    'src/handler.h': ('struct Handler {}; struct HandlerV2 {};  // 两套入口\n'
                      'int handle_v1();\nint handle_v2();\n'),
    'docs/migration.md': MIGRATION_DOC}
LEGAL_54 = {
    'src/protocol.h': (
        '// 公开协议：v1/v2 并行服务不同客户端版本（明确弃用期与退出条件）。\n'
        'struct HandlerProto {}; struct HandlerProtoV2 {};\n'),
    'docs/migration.md': MIGRATION_DOC,
    'src/handler_bad.h': BAD_54['src/handler.h']}


class RetiredSymbol(DesignGitCase):
    """5.1：可定类——复用 retired-symbol；判拼写，不承诺符号解析。"""

    def setUp(self):
        super().setUp()
        self.put_repo_tree({'src/keep.cc': 'int fine() { return 1; }\n'})
        self.put_repo_config(rules=('5.1',), extra=RETIRED_CFG)
        self.git('add', '.')
        self.git('commit', '-qm', 'base with retired decl')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()

    def test_bad_violation_with_contract_ref(self):
        self.put_repo_tree(BAD_51)
        self.git('add', '.')
        self.git('commit', '-qm', 'use old_api')
        p, rep = self.design_report(ctx='bad/5.1', keys=('5.1',), baseline=self.base)
        self.assertEqual(p.returncode, 0, '设计模式只报告，violation 不阻断')
        self.expect_status(rep, '5.1', 'violation', 'bad/5.1')
        row = self.one_finding(rep, '5.1', 'bad/5.1')
        facts = self.expect_facts(row, '5.1', 'bad/5.1')
        self.assertEqual(facts['retired_symbol'], 'old_api', '退役拼写')
        self.assertEqual(facts['scope_glob'], 'src/**', '声明的作用域')
        self.assertTrue(facts['new_lines'], '新增行事实')
        expected = expected_contract_ref(self.last_cfg_text, 'symbols = ', '.config/lint.toml')
        self.assert_contract_ref(row, expected, 'symbols', 'bad/5.1')

    def test_comment_migration_note_not_reported(self):
        """§5.1 例外：注释里的迁移说明不报；哨兵代码使用仍 violation。"""
        self.put_repo_tree(LEGAL_51)
        self.git('add', '.')
        self.git('commit', '-qm', 'doc note + sentinel use')
        p, rep = self.design_report(ctx='legal/5.1', keys=('5.1',), baseline=self.base)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '5.1')],
                         ['src/bad.cc'], '只有哨兵被报')

    def test_no_baseline_uncovered(self):
        """§4.1/§5.1 缺输入：Git 基准缺失 → uncovered/NO_BASELINE，exit 2。"""
        p, rep = self.design_report(ctx='NO_BASELINE/5.1', keys=('5.1',))
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '5.1', 'uncovered', 'NO_BASELINE/5.1')
        self.expect_missing_code(rep, '5.1', 'NO_BASELINE', 'NO_BASELINE/5.1')

    def test_no_retired_decl_uncovered(self):
        """§5.1 缺输入：无退役声明 → uncovered/NO_RETIRED_DECL，exit 2。"""
        self.put_repo_config(rules=('5.1',))
        p, rep = self.design_report(ctx='NO_RETIRED_DECL/5.1', keys=('5.1',),
                                    baseline=self.base)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '5.1', 'uncovered', 'NO_RETIRED_DECL/5.1')
        self.expect_missing_code(rep, '5.1', 'NO_RETIRED_DECL', 'NO_RETIRED_DECL/5.1')


class DuplicatedKnowledge(DesignGitCase):
    """5.2：线索类——重复检测找位置；是否共享由契约决定。"""

    def setUp(self):
        super().setUp()
        self.put_repo_tree({'src/base.cc': 'int base() { return 0; }\n'})
        self.put_repo_config(rules=('5.2',))
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()

    def test_bad_candidate_text_only(self):
        """§5.2：无语义重复检测 → 只 TEXT_ONLY（candidate + 缺码）。"""
        self.put_repo_tree(BAD_52)
        self.git('add', '.')
        self.git('commit', '-qm', 'duplicate protocol default')
        p, rep = self.design_report(ctx='bad/5.2', keys=('5.2',), baseline=self.base)
        self.assertEqual(p.returncode, 0, '降级候选不强制 exit 2')
        self.expect_status(rep, '5.2', 'candidate', 'bad/5.2')
        facts = self.expect_facts(self.one_finding(rep, '5.2', 'bad/5.2'), '5.2', 'bad/5.2')
        self.assertTrue(facts['duplicate_pairs'], '重复对位置（§5.2）')
        self.expect_missing_code(rep, '5.2', 'TEXT_ONLY', 'bad/5.2')

    def test_independent_policies_not_reported(self):
        """§5.2 例外：独立策略恰好同值不报；哨兵重复对仍报。"""
        self.put_repo_tree(LEGAL_52)
        self.git('add', '.')
        self.git('commit', '-qm', 'independent policies + sentinel')
        p, rep = self.design_report(ctx='legal/5.2', keys=('5.2',), baseline=self.base)
        rows = self.findings_for(rep, '5.2')
        self.assertTrue(rows, '哨兵重复对仍报')
        self.assertFalse(any('src/a.cc' == r['file'] or 'src/b.cc' == r['file'] for r in rows),
                         '独立策略同值不产生候选')

    def test_no_baseline_uncovered(self):
        p, rep = self.design_report(ctx='NO_BASELINE/5.2', keys=('5.2',))
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '5.2', 'uncovered', 'NO_BASELINE/5.2')
        self.expect_missing_code(rep, '5.2', 'NO_BASELINE', 'NO_BASELINE/5.2')


class DeadOldImplementation(DesignGitCase):
    """5.3：人工类——核对消费边界；零文本引用不等于能删。"""

    def setUp(self):
        super().setUp()
        self.put_repo_tree({'src/seed.cc': 'int seed() { return 0; }\n'})
        self.put_repo_config(manual=('5.3',))
        self.git('add', '.')
        self.git('commit', '-qm', 'seed')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()
        self.put_repo_tree(BAD_53)
        self.git('add', '.')
        self.git('commit', '-qm', 'add legacy impl')

    def test_bad_manual_pending(self):
        p, rep = self.design_report(ctx='bad/5.3', keys=('5.3',), baseline=self.base)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '5.3', 'manual_pending', 'bad/5.3')
        facts = self.expect_facts(self.one_finding(rep, '5.3', 'bad/5.3'), '5.3', 'bad/5.3')
        self.assertIsNotNone(facts['old_impl'], '旧实现事实（§5.3）')
        self.assertEqual(facts['refs'], [], '仓内零文本引用')
        self.assertIsNone(facts['external_consumers'], '仓外消费者未知 → 不判干净')
        self.expect_manual_pending(rep, '5.3', 'bad/5.3')
        self.expect_missing_code(rep, '5.3', 'EXTERNAL_UNKNOWN', 'bad/5.3')

    def test_declared_abi_export_not_reported(self):
        """§5.3 例外：声明 ABI 导出/动态加载边界不产生删除候选；哨兵仍出包。"""
        p, rep = self.design_report(ctx='legal/5.3', keys=('5.3',), baseline=self.base)
        rows = self.findings_for(rep, '5.3')
        self.assertTrue(rows, '哨兵仍出包')
        self.assertFalse(any(f['file'] == 'src/exported.cc' for f in rows),
                         '有消费边界声明不产生候选')

    def test_dynamic_unknown(self):
        """行内裸码 DYNAMIC_UNKNOWN 在人工行 → manual_pending。"""
        root = self.put_repo_tree(MISSING_53)
        p, rep = self.design_report(ctx='DYNAMIC/5.3', keys=('5.3',), baseline=self.base)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '5.3', 'manual_pending', 'DYNAMIC/5.3')
        self.expect_missing_code(rep, '5.3', 'DYNAMIC_UNKNOWN', 'DYNAMIC/5.3')

    def test_no_baseline_uncovered(self):
        p, rep = self.design_report(ctx='NO_BASELINE/5.3', keys=('5.3',))
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '5.3', 'uncovered', 'NO_BASELINE/5.3')
        self.expect_missing_code(rep, '5.3', 'NO_BASELINE', 'NO_BASELINE/5.3')


class VersionInsteadOfContract(DesignCase):
    """5.4：线索类——复用 T501；行内「无迁移契约 → uncovered」按字面冻结。"""

    def test_no_migration_contract_uncovered(self):
        """§5.4 缺输入：无迁移契约 → uncovered/NO_MIGRATION_CONTRACT（行内字面）。"""
        p, rep, _ = self.one('5.4', {'src/handler.h': BAD_54['src/handler.h']})
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '5.4', 'uncovered', 'NO_MIGRATION_CONTRACT/5.4')
        self.expect_missing_code(rep, '5.4', 'NO_MIGRATION_CONTRACT',
                                 'NO_MIGRATION_CONTRACT/5.4')

    def test_with_contract_candidate(self):
        """有迁移契约但退出条件未满足的版本对 → candidate（t501 事实）。"""
        p, rep, _ = self.one('5.4', BAD_54, extra=CFG_54)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '5.4', 'candidate', 'bad/5.4')
        facts = self.expect_facts(self.one_finding(rep, '5.4', 'bad/5.4'), '5.4', 'bad/5.4')
        self.assertTrue(facts['entry_pairs'], '版本化入口对（§5.4）')
        self.assertTrue(facts['t501_candidate'], 'T501 形状事实')
        self.assertIsNotNone(facts['migration_contract'], '迁移契约已声明')

    def test_public_protocol_parallel_not_reported(self):
        """§5.4 例外：公开协议需要并行版本不报；哨兵仍报。"""
        p, rep, _ = self.one('5.4', LEGAL_54, extra=CFG_54)
        rows = self.findings_for(rep, '5.4')
        self.assertTrue(rows, '哨兵仍报')
        self.assertFalse(any(f['file'] == 'src/protocol.h' for f in rows),
                         '公开协议并行版本不产生候选')


if __name__ == '__main__':
    unittest.main()
