"""6 可读性与局部实现（6.1–6.5）的冻结预期（T2，来源：映射 §1.6 五行 + §4.5）。

6.3 行内「candidate/CHAIN_PARTIAL」与 §0.3 人工上限、§2 分桶冲突，按上限冻结为
manual_pending（handoff 记录该冲突；改判只改本文件两处断言）。
"""
import unittest

from design_fixtures import DesignCase, DesignGitCase

BAD_61 = {'dup.cc': 'int f(int x) { if (x > 0) { x = 1; } else { x = 1; } return x; }\n'}
LEGAL_61 = {
    'diff.cc': 'int g(int x) { if (x > 0) { x = 1; } else { x = 2; } return x; }\n',
    'dup_bad.cc': BAD_61['dup.cc']}
MISSING_61 = {'macro_branch.cc': (
    '#define ASSIGN(v) { v = 1; }\n'
    'int h(int x) { if (x > 0) ASSIGN(x) else ASSIGN(x) return x; }  // 分支体被宏遮蔽\n')}

BAD_62 = {'big_fn.cc': (
    '#include <string>\n'
    'void db_insert(int code);\n'
    'void render(const std::string& label);\n'
    'int process(const char* raw) {\n'
    '  // 阶段一：解析协议\n'
    '  int code = raw[0] - \'0\';\n'
    '  // 阶段二：写库\n'
    '  db_insert(code);\n'
    '  // 阶段三：拼 UI 文案\n'
    '  std::string label = "code=" + std::to_string(code);\n'
    '  render(label);\n'
    '  return code;\n'
    '}\n')}
LEGAL_62 = {
    'state_table.cc': (
        '// 单一协议状态表：各分支为同一协议的状态迁移，拆开反而要跨文件追踪。\n'
        'int step(int state, int ev) {\n'
        '  switch (state) {\n'
        '    case 0: return ev == 1 ? 1 : 0;\n'
        '    case 1: return ev == 2 ? 2 : 1;\n'
        '    case 2: return ev == 3 ? 0 : 2;\n'
        '    default: return state;\n'
        '  }\n'
        '}\n'),
    'big_fn_bad.cc': BAD_62['big_fn.cc']}

BAD_63 = {'hops.cc': (
    'int step3() { return 42; }\n'
    'int step2() { return step3(); }\n'
    'int step1() { return step2(); }\n'
    'int entry() { return step1(); }  // 连续跳过多个纯转发层\n')}
LEGAL_63 = {
    'unit.cc': 'constexpr int ms_to_s(int ms) { return ms / 1000; }  // 封装单位转换\n',
    'hops_bad.cc': BAD_63['hops.cc']}
MISSING_63_CHAIN = {'broken.cc': (
    'struct Chain {\n  int (*step_)();  // 经函数指针转发，静态调用图不完整\n'
    '  int entry() { return step_(); }\n};\n')}
MISSING_63_DISPATCH = {'tmpl.cc': (
    'template <class S> int forward_all(S s) { return s(); }  // 模板转发\n')}

BAD_64 = {'a.h': '/* 数量。 */\nint limit{0};\n'}          # 6.4：中文释义，非逐字重复
VERBATIM_64 = {'v.h': '/* limit。 */\nint limit{0};\n'}  # 6.4：注释逐字重复标识符
ENGLISH_64 = {'e.h': '/* the count. */\nint limit{0};\n'}  # 6.4：英文释义，非逐字重复
LEGAL_64 = {
    'b.h': '/* 上限单位：秒；0 为哨兵值表示不启用。 */\nint limit2{0};\n',
    'a_bad.h': BAD_64['a.h']}
MISSING_64 = {'orphan.h': '/* 数量。 */\n\nvoid unrelated();\n'}  # 注释归属不可解析

BAD_65 = {'q.cc': (
    '#include <deque>\n#include <utility>\n'
    'struct Rec { int id; };\n'
    'struct Q {\n'
    '  Rec peek() { auto r = std::move(items_.front()); items_.pop_front(); return r; }  // 消费\n'
    '  std::deque<Rec> items_;\n'
    '};\n')}
LEGAL_65 = {
    'q2.cc': ('#include <deque>\n'
              'struct Rec { int id; };\n'
              'struct Q2 {\n'
              '  size_t size() const { return items_.size(); }  // 非消费式查询\n'
              '  std::deque<Rec> items_;\n'
              '};\n'),
    'q_bad.cc': BAD_65['q.cc']}
FAKE_65 = {'q_fake.cc': (
    '#include <deque>\n#include <utility>\n'
    'struct Rec { int id; };\n'
    'struct QF {\n'
    '  Rec peek_v2() { auto r = std::move(items_.front()); items_.pop_front(); return r; }  // 只改名，仍消费\n'
    '  std::deque<Rec> items_;\n'
    '};\n')}
REAL_65 = {'q_real.cc': (
    '#include <deque>\n'
    'struct Rec { int id; };\n'
    'struct QR {\n'
    '  const Rec& front() const { return items_.front(); }  // 只读\n'
    '  Rec pop() { auto r = std::move(items_.front()); items_.pop_front(); return r; }  // 名副实的消费\n'
    '  std::deque<Rec> items_;\n'
    '};\n')}
MISSING_65 = {'q_decl.h': ('struct Rec;\nstruct QD {\n  Rec peek();  // 实现不可见\n};\n')}


class IdenticalBranches(DesignCase):
    """6.1：线索类——重复分支检查；诊断与自动修复分开。"""

    def test_bad_candidate_normalized_equal(self):
        p, rep, _ = self.one('6.1', BAD_61)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.1', 'candidate', 'bad/6.1')
        facts = self.expect_facts(self.one_finding(rep, '6.1', 'bad/6.1'), '6.1', 'bad/6.1')
        self.assertTrue(facts['normalized_equal'], '两支规范化等价（§6.1）')
        self.assertFalse(facts['condition_side_effect'], '条件无副作用')

    def test_differing_branches_not_reported(self):
        p, rep, _ = self.one('6.1', LEGAL_61)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '6.1')],
                         ['dup_bad.cc'], '只有哨兵被报')

    def test_macro_branch_uncovered(self):
        p, rep, _ = self.one('6.1', MISSING_61)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '6.1', 'uncovered', 'BRANCH_UNRESOLVED/6.1')
        self.expect_missing_code(rep, '6.1', 'BRANCH_UNRESOLVED', 'BRANCH_UNRESOLVED/6.1')


class LongFunctionMixedReasons(DesignGitCase):
    """6.2：人工类——行数仅定位，不按固定阈值拆函数。"""

    BIG_V1 = ('int process(const char* raw) {\n'
              '  int code = raw[0] - \'0\';\n'
              '  return code;\n'
              '}\n')

    def test_bad_manual_pending_intent_unknown(self):
        """无历史/契约锚点 → manual_pending/INTENT_UNKNOWN（§6.2）。"""
        p, rep, _ = self.one('6.2', BAD_62, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.2', 'manual_pending', 'bad/6.2')
        facts = self.expect_facts(self.one_finding(rep, '6.2', 'bad/6.2'), '6.2', 'bad/6.2')
        self.assertTrue(facts['responsibility_candidates'], '职责候选事实（§6.2）')
        self.expect_manual_pending(rep, '6.2', 'bad/6.2')
        self.expect_missing_code(rep, '6.2', 'INTENT_UNKNOWN', 'bad/6.2')

    def test_anchored_by_history_still_manual(self):
        """有变更历史锚点（同一函数两轮不同原因修改）→ change_reasons 非空，
        判定仍为 manual_pending（人工上限，不因有历史而升级）。"""
        self.put_repo_tree({'src/big.cc': self.BIG_V1})
        self.put_repo_config(manual=('6.2',))
        self.git('add', '.')
        self.git('commit', '-qm', 'parse only')
        base = self.git('rev-parse', 'HEAD').stdout.strip()
        self.put_repo_tree({'src/big.cc': BAD_62['big_fn.cc']})
        self.git('add', '.')
        self.git('commit', '-qm', 'add db write and ui label')
        p, rep = self.design_report(ctx='anchored/6.2', keys=('6.2',), baseline=base)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.2', 'manual_pending', 'anchored/6.2')
        facts = self.expect_facts(self.one_finding(rep, '6.2', 'anchored/6.2'), '6.2',
                                  'anchored/6.2')
        self.assertTrue(facts['change_reasons'], '历史锚点给出变化原因事实')

    def test_single_protocol_table_not_reported(self):
        """§6.2 例外：单一协议长状态表无职责候选；哨兵仍出包。"""
        p, rep, _ = self.one('6.2', LEGAL_62, manual=True)
        self.expect_status(rep, '6.2', 'manual_pending', 'legal/6.2')
        rows = self.findings_for(rep, '6.2')
        self.assertTrue(rows, '哨兵仍出包')
        self.assertFalse(any(f['file'] == 'state_table.cc' for f in rows),
                         '状态表不产生职责候选')


class OverFragmentedReading(DesignCase):
    """6.3：人工类——按 §0.3 上限冻结 manual_pending（行内冲突见文件头）。"""

    def test_bad_manual_pending_chain_facts(self):
        p, rep, _ = self.one('6.3', BAD_63, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.3', 'manual_pending', 'bad/6.3')
        facts = self.expect_facts(self.one_finding(rep, '6.3', 'bad/6.3'), '6.3', 'bad/6.3')
        self.assertGreaterEqual(facts['hop_count'], 3, '往返跳数（§6.3）')
        self.assertTrue(facts['forward_only'], '纯转发层列表')
        self.assertIsNone(facts['real_call_example'], '无真实调用样例')
        self.expect_manual_pending(rep, '6.3', 'bad/6.3')

    def test_unit_conversion_helper_not_reported(self):
        """§6.3 例外：封装单位转换的辅助不报；哨兵仍出包。"""
        p, rep, _ = self.one('6.3', LEGAL_63, manual=True)
        self.expect_status(rep, '6.3', 'manual_pending', 'legal/6.3')
        rows = self.findings_for(rep, '6.3')
        self.assertTrue(rows, '哨兵仍出包')
        self.assertFalse(any(f['file'] == 'unit.cc' for f in rows),
                         '单位转换辅助不产生候选')

    def test_chain_partial_manual_pending(self):
        """行内 candidate/CHAIN_PARTIAL 按人工上限冻结为 manual_pending。"""
        p, rep, _ = self.one('6.3', MISSING_63_CHAIN, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.3', 'manual_pending', 'CHAIN_PARTIAL/6.3')
        self.expect_missing_code(rep, '6.3', 'CHAIN_PARTIAL', 'CHAIN_PARTIAL/6.3')

    def test_template_dispatch_uncovered(self):
        """裸码 DISPATCH_UNRESOLVED 定型为 uncovered（同 1.3，见 design_fixtures 规则）。"""
        p, rep, _ = self.one('6.3', MISSING_63_DISPATCH, manual=True)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '6.3', 'uncovered', 'DISPATCH/6.3')
        self.expect_missing_code(rep, '6.3', 'DISPATCH_UNRESOLVED', 'DISPATCH/6.3')


class CommentRestatesCode(DesignCase):
    """6.4：线索类——T202 只判逐字重复，不猜中英文释义。"""

    def test_paraphrase_comment_keeps_restates_unknown(self):
        """中文释义（非逐字）不产生 restates_name 判决（§6.4 词法线索）。"""
        p, rep, _ = self.one('6.4', BAD_64)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.4', 'candidate', 'bad/6.4')
        facts = self.expect_facts(self.one_finding(rep, '6.4', 'bad/6.4'), '6.4', 'bad/6.4')
        self.assertTrue(facts['t202_candidate'], 'T202 形状事实（§6.4）')
        self.assertIsNone(facts['restates_name'], '无逐字重复 → 释义未知，不伪造语义')
        self.assertEqual(facts['extra_info'], [], '无单位/生命周期/哨兵信息')

    def test_verbatim_comment_restates_name(self):
        """逐字重复标识符是可机读词法线索 → restates_name=true。"""
        p, rep, _ = self.one('6.4', VERBATIM_64)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.4', 'candidate', 'verbatim/6.4')
        facts = self.expect_facts(self.one_finding(rep, '6.4', 'verbatim/6.4'), '6.4', 'verbatim/6.4')
        self.assertTrue(facts['t202_candidate'], 'T202 形状事实（§6.4）')
        self.assertTrue(facts['restates_name'], '注释逐字重复变量名')
        self.assertEqual(facts['extra_info'], [], '无单位/生命周期/哨兵信息')

    def test_english_paraphrase_keeps_restates_unknown(self):
        """英文释义同样不猜词义 → restates_name=null（与中文口径一致）。"""
        p, rep, _ = self.one('6.4', ENGLISH_64)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.4', 'candidate', 'english/6.4')
        facts = self.expect_facts(self.one_finding(rep, '6.4', 'english/6.4'), '6.4', 'english/6.4')
        self.assertTrue(facts['t202_candidate'], 'T202 形状事实（§6.4）')
        self.assertIsNone(facts['restates_name'], '无逐字重复 → 释义未知，不伪造语义')
        self.assertEqual(facts['extra_info'], [], '无单位/生命周期/哨兵信息')

    def test_meaningful_short_comment_not_reported(self):
        """§6.4 例外：解释单位/哨兵值的短注释不报；哨兵仍报。"""
        p, rep, _ = self.one('6.4', LEGAL_64)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '6.4')],
                         ['a_bad.h'], '只有哨兵被报')

    def test_orphan_comment_uncovered(self):
        p, rep, _ = self.one('6.4', MISSING_64)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '6.4', 'uncovered', 'COMMENT_UNRESOLVED/6.4')
        self.expect_missing_code(rep, '6.4', 'COMMENT_UNRESOLVED', 'COMMENT_UNRESOLVED/6.4')


class NameHidesSideEffect(DesignCase):
    """6.5：行为类——按 API 契约写调用前后断言，不靠动词表。"""

    def test_bad_candidate_consume_under_peek(self):
        p, rep, _ = self.one('6.5', BAD_65)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '6.5', 'candidate', 'bad/6.5')
        facts = self.expect_facts(self.one_finding(rep, '6.5', 'bad/6.5'), '6.5', 'bad/6.5')
        self.assertTrue(facts['side_effects'], '副作用事实（§6.5）')
        self.assertIsNone(facts['contract_ref'], '无 API 契约声明')
        self.expect_missing_code(rep, '6.5', 'NO_BEHAVIOR_HARNESS', 'bad/6.5')
        self.expect_missing_code(rep, '6.5', 'NO_CONTRACT', 'bad/6.5')

    def test_nonconsuming_query_not_reported(self):
        """§6.5 例外：非消费式查询不报；哨兵仍报。"""
        p, rep, _ = self.one('6.5', LEGAL_65)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '6.5')],
                         ['q_bad.cc'], '只有哨兵被报')

    def test_rename_still_consumes_still_reports(self):
        """假修：peek 改名 peek_v2 仍消费 → 仍报同一根因（名字不是证据）。"""
        p, rep, _ = self.one('6.5', FAKE_65)
        self.expect_status(rep, '6.5', 'candidate', 'fake/6.5')
        facts = self.expect_facts(self.one_finding(rep, '6.5', 'fake/6.5'), '6.5', 'fake/6.5')
        self.assertTrue(facts['side_effects'], '消费副作用仍在')

    def test_real_fix_not_reported(self):
        p, rep, _ = self.one('6.5', REAL_65)
        self.expect_status(rep, '6.5', 'not_reported', 'real/6.5')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1)

    def test_body_unknown_uncovered(self):
        p, rep, _ = self.one('6.5', MISSING_65)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '6.5', 'uncovered', 'BODY_UNKNOWN/6.5')
        self.expect_missing_code(rep, '6.5', 'BODY_UNKNOWN', 'BODY_UNKNOWN/6.5')


if __name__ == '__main__':
    unittest.main()
