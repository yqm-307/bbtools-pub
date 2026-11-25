"""3 接口与契约（3.1–3.4）的冻结预期（T2，来源：映射 §1.3 四行 + §4.5 + 目录「首选试验」）。

3.3 是本期「先贯通一项」的验收样板：坏例/假修/真修/合法/缺索引五组全部落夹具。
场景按映射 §3 的真实现场缩样建模：owner 为被动 struct 的裸 std::deque 成员
（对应 bbtools-infra@f6e011a Server.cc:340 的 Session::queue，blob 6efaf60e…），
调用方 front/find/erase/clear 维护序号与移除时机（对应 Server.cc:1205-1298
WriterLoop），契约注释取该现场 336-339 的语义（quote SHA 在断言里按夹具文本现算）。
"""
import unittest

from design_fixtures import DesignCase, expected_contract_ref

CONTRACT_33 = '// 契约：序号升序；front 是 writer 当前负责的序号。记录只在写终态或连接放弃时移除。'

BAD_33 = {'scene.cc': (
    '#include <deque>\n#include <memory>\n#include <algorithm>\n'
    'struct RequestRecord { int seq; int response; };\n'
    'struct Session {\n'
    f'{CONTRACT_33}\n'
    '  std::deque<std::shared_ptr<RequestRecord>> queue;\n'
    '  bool reader_done = false;\n'
    '};\n'
    'void WriterLoop(Session& s) {\n'
    '  while (!s.queue.empty()) {\n'
    '    auto rec = s.queue.front();            // 取队首当前写序号\n'
    '    (void)rec->response;\n'
    '    auto it = std::find(s.queue.begin(), s.queue.end(), rec);\n'
    '    s.queue.erase(it);                     // 结算后移除\n'
    '  }\n'
    '  if (s.reader_done) s.queue.clear();\n'
    '}\n')}

FAKE_33 = {'scene_fake.cc': (
    '#include <deque>\n#include <memory>\n#include <algorithm>\n'
    'struct RequestRecord { int seq; int response; };\n'
    f'{CONTRACT_33}\n'
    'class Session {\n'
    'public:\n'
    '  std::deque<std::shared_ptr<RequestRecord>>& items() { return queue; }  // getter 暴露同一容器\n'
    'private:\n'
    '  std::deque<std::shared_ptr<RequestRecord>> queue;  // 字段已私有，责任未转移\n'
    '  bool reader_done = false;\n'
    '};\n'
    'void WriterLoopFake(Session& s) {\n'
    '  auto& q = s.items();\n'
    '  while (!q.empty()) {\n'
    '    auto rec = q.front();\n'
    '    auto it = std::find(q.begin(), q.end(), rec);\n'
    '    q.erase(it);\n'
    '  }\n'
    '}\n')}

REAL_33 = {'scene_real.cc': (
    '#include <deque>\n#include <memory>\n'
    'struct RequestRecord { int seq; int response; };\n'
    'class Session {\n'
    'public:\n'
    '  std::shared_ptr<RequestRecord> current() {  // owner 提供当前写序号\n'
    '    return queue.empty() ? nullptr : queue.front();\n'
    '  }\n'
    '  void settle(const std::shared_ptr<RequestRecord>& rec) {  // owner 负责移除\n'
    '    if (!queue.empty() && queue.front() == rec) queue.pop_front();\n'
    '  }\n'
    'private:\n'
    '  std::deque<std::shared_ptr<RequestRecord>> queue;\n'
    '};\n'
    'void WriterLoopReal(Session& s) {\n'
    '  while (auto rec = s.current()) { s.settle(rec); }  // 调用方只请求结果\n'
    '}\n')}

LEGAL_33 = {'reader.cc': (
    '#include <memory>\n'
    'void trace(int seq);\n'
    'struct RequestRecord { int seq; int response; };\n'
    'void log_progress(const std::shared_ptr<RequestRecord>& rec) {\n'
    '  trace(rec->seq);  // 只读取普通结果值，不碰容器、不维护游标\n'
    '}\n'),
    'scene_bad.cc': BAD_33['scene.cc']}

MISSING_33_NO_INDEX = {'scene.cc': BAD_33['scene.cc']}  # 不写 CDB → 缺索引
MISSING_33_OWNER = {'fwd.h': 'struct Session;\n',
                    'use.cc': ('#include "fwd.h"\n'
                               'void touch(Session& s) { s.queue.clear(); }  // owner 定义不可见\n')}

BAD_31 = {'task.cc': (
    '#include <utility>\n'
    'struct Task {};\nstruct Result { Task* borrowed; Task owned; };\n'
    'Result run(Task t, bool own_result) {\n'
    '  if (own_result) { Result r; r.owned = std::move(t); return r; }  // 切换结果所有权\n'
    '  Result r; r.borrowed = &t; return r;\n'
    '}\n'
    'void call() { auto r = run(Task{}, true); (void)r; }\n')}
LEGAL_31 = {
    'attr.h': 'struct Dev { void set_enabled(bool on); };  // 明确二态属性\n',
    'task_bad.cc': BAD_31['task.cc']}
MISSING_31 = {'decl_only.h': 'struct Task {};\nstruct Result {};\nResult run(Task t, bool own_result);\n'}

BAD_32 = {'chan.cc': (
    'int write(int fd, const char* d);\n'
    'struct Chan {\n'
    '  void init();          // 必须先调用\n'
    '  void bind(int port);  // 再绑定\n'
    '  int send_data(const char* d);  // 未 init/bind 时静默返回 0\n'
    'private:\n'
    '  static int port_;\n'
    '  static bool ready_;\n'
    '};\n'
    'int Chan::send_data(const char* d) { if (!ready_) return 0; return write(port_, d); }\n'
    'int Chan::port_ = 0;\nbool Chan::ready_ = false;\n')}
LEGAL_32 = {
    'chan2.h': ('struct Chan2 {\n'
                '  explicit Chan2(int port);        // 构造即完成初始化\n'
                '  int send_data(const char* d);    // 无独立 init/bind 前置\n'
                '};\n'),
    'chan_bad.cc': BAD_32['chan.cc']}
FAKE_32 = {'chan_fake.cc': (
    'int write(int fd, const char* d);\n'
    'struct ChanF {\n'
    '  void setup();         // 只改名\n'
    '  void attach(int port);\n'
    '  int send_data(const char* d);  // 仍静默返回 0\n'
    'private:\n'
    '  static int port_;\n'
    '  static bool ready_;\n'
    '};\n'
    'int ChanF::send_data(const char* d) { if (!ready_) return 0; return write(port_, d); }\n'
    'int ChanF::port_ = 0;\nbool ChanF::ready_ = false;\n')}
REAL_32 = {'chan_real.cc': (
    'int write(int fd, const char* d);\n'
    'struct ChanR {\n'
    '  explicit ChanR(int port) : port_(port), ready_(true) {}\n'
    '  int send_data(const char* d) { if (!ready_) return -1; return write(port_, d); }  // 失败显式\n'
    '  int port_; bool ready_;\n};\n')}
MISSING_32 = {'hidden.cc': ('#define INIT_VIA_FRAMEWORK() framework_init(this)\n'
                            'struct ChanH { void init() { INIT_VIA_FRAMEWORK(); } };\n')}

CFG_34 = ('[design."3.4"]\n'
          'forbidden = ["ForTest*", "TestAccess*", "for_test*", "test_inject*"]\n'
          'test_targets = ["tests/*"]\n'
          '[design."3.4".targets]\n'
          '"prod/*" = "prod"\n'
          '"tests/*" = "tests"\n')
CFG_34_NO_CONTRACT = ('[design."3.4".targets]\n'
                      '"prod/*" = "prod"\n'
                      '"tests/*" = "tests"\n')
BAD_34 = {'prod/util.h': 'int ForTestOnly();\nint real_fn();\n'}
LEGAL_34 = {
    'tests/helper.cc': 'int ForTestOnly() { return 1; }  // 独立测试目标内的同名辅助\n',
    'prod/util_bad.h': 'int ForTestOnly();\n'}
MISSING_34 = {'misc/x.h': 'int ForTestOnly();\n'}


class BoolFlagSwitching(DesignCase):
    """3.1：线索类——抽样读调用点，不禁 bool。"""

    def test_bad_candidate_with_branch_facts(self):
        p, rep, _ = self.one('3.1', BAD_31)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '3.1', 'candidate', 'bad/3.1')
        facts = self.expect_facts(self.one_finding(rep, '3.1', 'bad/3.1'), '3.1', 'bad/3.1')
        self.assertTrue(facts['bool_params'], 'bool 参数事实（§3.1）')
        self.assertTrue(facts['controlled_branches'], '受控分支非空')
        self.assertFalse(facts['attribute_like_name'], '非 set_enabled 形状')
        self.assertTrue(facts['call_sites'], '调用点抽样非空')

    def test_attribute_like_not_reported(self):
        """§3.1 例外：明确二态属性不报；哨兵仍报。"""
        p, rep, _ = self.one('3.1', LEGAL_31)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '3.1')],
                         ['task_bad.cc'], '只有哨兵被报')

    def test_body_unknown_uncovered(self):
        p, rep, _ = self.one('3.1', MISSING_31)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '3.1', 'uncovered', 'BODY_UNKNOWN/3.1')
        self.expect_missing_code(rep, '3.1', 'BODY_UNKNOWN', 'BODY_UNKNOWN/3.1')


class HiddenCallOrder(DesignCase):
    """3.2：行为类——优先构造约束或状态转换测试；静态只给线索。"""

    def test_bad_candidate_silent_failure(self):
        p, rep, _ = self.one('3.2', BAD_32)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '3.2', 'candidate', 'bad/3.2')
        facts = self.expect_facts(self.one_finding(rep, '3.2', 'bad/3.2'), '3.2', 'bad/3.2')
        self.assertTrue(facts['phases'], '阶段事实（§3.2）')
        self.assertEqual(facts['failure_mode'], 'silent', '普通操作静默失败')
        self.assertIsNone(facts['type_constraint'], '类型未区分阶段')
        self.expect_missing_code(rep, '3.2', 'NO_BEHAVIOR_HARNESS', 'bad/3.2')
        self.expect_missing_code(rep, '3.2', 'NO_CONTRACT', 'bad/3.2')

    def test_constructor_completes_init_not_reported(self):
        """§3.2 例外：构造即完成初始化不报；哨兵仍报。"""
        p, rep, _ = self.one('3.2', LEGAL_32)
        self.assertTrue(self.findings_for(rep, '3.2'), '哨兵仍报')
        self.assertFalse(any(f['file'] == 'chan2.h' for f in self.findings_for(rep, '3.2')),
                         '构造完成初始化不触发')

    def test_renamed_phases_still_reports(self):
        """假修：init/bind 改名 setup/attach，顺序要求仍在 → 仍报。"""
        p, rep, _ = self.one('3.2', FAKE_32)
        self.expect_status(rep, '3.2', 'candidate', 'fake/3.2')
        facts = self.expect_facts(self.one_finding(rep, '3.2', 'fake/3.2'), '3.2', 'fake/3.2')
        self.assertEqual(facts['failure_mode'], 'silent', '假修后失败模式不变')

    def test_real_fix_not_reported(self):
        p, rep, _ = self.one('3.2', REAL_32)
        self.expect_status(rep, '3.2', 'not_reported', 'real/3.2')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1)

    def test_init_hidden_uncovered(self):
        p, rep, _ = self.one('3.2', MISSING_32)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '3.2', 'uncovered', 'INIT_HIDDEN/3.2')
        self.expect_missing_code(rep, '3.2', 'INIT_HIDDEN', 'INIT_HIDDEN/3.2')


class CallerMaintainsOwnerState(DesignCase):
    """3.3 验收样板（目录「首选试验」+ §5.3）：坏例 candidate、假修仍 candidate、
    真修 not_reported、合法读取 not_reported、缺索引 uncovered；五者齐全才算贯通。"""

    def test_bad_candidate_with_access_sequence(self):
        p, rep, _ = self.one('3.3', BAD_33, cdb=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '3.3', 'candidate', 'bad/3.3')
        row = self.one_finding(rep, '3.3', 'bad/3.3')
        facts = self.expect_facts(row, '3.3', 'bad/3.3')
        self.assertEqual(facts['owner_type'], 'Session', 'owner 类型（§3.3）')
        self.assertEqual(facts['field']['name'], 'queue', '被维护字段')
        self.assertIn('std::deque', facts['field']['type'], '裸 deque 表示')
        self.assertEqual(facts['getter_mediated'], False, '直接字段访问')
        self.assertEqual(facts['read_only_use'], False, '非只读')
        self.assertEqual(facts['owner_operations'], [], 'owner 无操作（被动 struct）')
        ops = {step['op'] for step in facts['access_sequence']}
        self.assertTrue({'front', 'erase'} <= ops, f'访问序列含 front/erase，得 {ops}')
        self.assertTrue(all(step['function'] == 'WriterLoop'
                            for step in facts['access_sequence']),
                        '维护责任在调用方 WriterLoop')
        self.assertIsNotNone(facts['invariant_ref'], '契约注释可引用')
        expected = expected_contract_ref(BAD_33['scene.cc'], '契约：序号升序', 'scene.cc')
        self.assert_contract_ref(row, expected, '契约：序号升序', 'bad/3.3')
        self.expect_missing_code(rep, '3.3', 'NO_BEHAVIOR_HARNESS', 'bad/3.3')

    def test_fake_fix_getter_still_reports(self):
        """假修：字段私有化、调用方经 getter 做同一组操作 → 仍报同一根因。"""
        p, rep, _ = self.one('3.3', FAKE_33, cdb=True)
        self.expect_status(rep, '3.3', 'candidate', 'fake/3.3')
        facts = self.expect_facts(self.one_finding(rep, '3.3', 'fake/3.3'), '3.3', 'fake/3.3')
        self.assertEqual(facts['getter_mediated'], True, '识别 getter 中介')
        self.assertEqual(facts['owner_type'], 'Session', '同一 owner 根因')
        ops = {step['op'] for step in facts['access_sequence']}
        self.assertTrue({'front', 'erase'} <= ops, f'同一操作序列仍在，得 {ops}')
        self.assertEqual(facts['owner_operations'], [], 'owner 仍未提供操作')

    def test_real_fix_not_reported(self):
        """真修：owner 完成操作、调用方只请求结果 → not_reported，且同范围确实被扫描。"""
        p, rep, _ = self.one('3.3', REAL_33, cdb=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '3.3', 'not_reported', 'real/3.3')
        self.assertEqual(self.findings_for(rep, '3.3'), [], '真修消警，不是换文件漏扫')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1, '检查确实运行')

    def test_legal_read_only_use_not_reported(self):
        """合法用法：只读普通结果值不报；同树哨兵坏例仍报（证明不是漏扫）。"""
        p, rep, _ = self.one('3.3', LEGAL_33, cdb=True)
        rows = self.findings_for(rep, '3.3')
        self.assertEqual([r['file'] for r in rows], ['scene_bad.cc'], '只有哨兵被报')
        self.expect_status(rep, '3.3', 'candidate', 'legal/3.3')

    def test_missing_index_uncovered(self):
        """缺索引：无 compile_commands.json → uncovered（§5.3 对账项）。"""
        p, rep, _ = self.one('3.3', MISSING_33_NO_INDEX, cdb=False)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '3.3', 'uncovered', 'NO_INDEX/3.3')
        self.expect_missing_code(rep, '3.3', 'NO_INDEX', 'NO_INDEX/3.3')
        self.assertFalse(rep['coverage']['complete'], '绝不记干净')

    def test_owner_unresolved_uncovered(self):
        """§3.3 缺输入：无 owner 定义/AST → uncovered/OWNER_UNRESOLVED。"""
        p, rep, _ = self.one('3.3', MISSING_33_OWNER, cdb=True)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '3.3', 'uncovered', 'OWNER_UNRESOLVED/3.3')
        self.expect_missing_code(rep, '3.3', 'OWNER_UNRESOLVED', 'OWNER_UNRESOLVED/3.3')


class TestSeamLeak(DesignCase):
    """3.4：可定（有禁用契约时），否则 T601 仅为线索。"""

    def test_no_contract_candidate_via_t601(self):
        root = self.put_tree(BAD_34)
        self.put_design_config(rules=('3.4',), extra=CFG_34_NO_CONTRACT, root=root)
        p, rep = self.design_report(ctx='clue/3.4', keys=('3.4',), root=root)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '3.4', 'candidate', 'clue/3.4')
        facts = self.expect_facts(self.one_finding(rep, '3.4', 'clue/3.4'), '3.4', 'clue/3.4')
        self.assertTrue(facts['t601_candidate'], 'T601 形状事实（§3.4）')
        self.assertIsNone(facts['forbidden_contract'], '无禁用契约 → 不升级')

    def test_with_contract_violation(self):
        root = self.put_tree(BAD_34)
        cfg = self.put_design_config(rules=('3.4',), extra=CFG_34, root=root)
        p, rep = self.design_report(ctx='bad/3.4', keys=('3.4',), root=root)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '3.4', 'violation', 'bad/3.4')
        row = self.one_finding(rep, '3.4', 'bad/3.4')
        facts = self.expect_facts(row, '3.4', 'bad/3.4')
        self.assertEqual(facts['target'], 'prod', '生产目标')
        self.assertFalse(facts['test_target_match'], '非测试目标')
        expected = expected_contract_ref(cfg, 'forbidden = ', '.config/lint.toml')
        self.assert_contract_ref(row, expected, 'forbidden', 'bad/3.4')

    def test_test_target_same_name_not_reported(self):
        """§3.4 例外：独立测试目标内同名辅助不报；生产哨兵仍 violation。"""
        root = self.put_tree(LEGAL_34)
        self.put_design_config(rules=('3.4',), extra=CFG_34, root=root)
        p, rep = self.design_report(ctx='legal/3.4', keys=('3.4',), root=root)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '3.4')],
                         ['prod/util_bad.h'], '只有生产哨兵被报')

    def test_target_unknown_uncovered(self):
        root = self.put_tree(MISSING_34)
        self.put_design_config(rules=('3.4',), extra=CFG_34, root=root)
        p, rep = self.design_report(ctx='TARGET_UNKNOWN/3.4', keys=('3.4',), root=root)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '3.4', 'uncovered', 'TARGET_UNKNOWN/3.4')
        self.expect_missing_code(rep, '3.4', 'TARGET_UNKNOWN', 'TARGET_UNKNOWN/3.4')


if __name__ == '__main__':
    unittest.main()
