"""4 失败与错误（4.1–4.4）的冻结预期（T2，来源：映射 §1.4 四行 + §4.5）。"""
import unittest

from design_fixtures import DesignCase

BAD_41 = {'store.cc': (
    '#include <cstdio>\n#include <vector>\n'
    'void log(const char* msg);\n'
    'struct Rec { int id; };\n'
    'std::vector<Rec> load_all(const char* path) {\n'
    '  std::FILE* f = std::fopen(path, "r");\n'
    '  if (!f) { log("open failed"); return {}; }  // 读取失败伪装成空集合\n'
    '  std::vector<Rec> out;\n'
    '  out.push_back(Rec{1});\n'
    '  std::fclose(f);\n'
    '  return out;\n'
    '}\n')}
LEGAL_41 = {
    'store_doc.cc': (
        '#include <cstdio>\n#include <cerrno>\n#include <vector>\n'
        'struct Rec { int id; };\n'
        'void set_last_error(int code);\n'
        '// 契约：不存在对应空集合；读取错误经 last_error() 另行报告。\n'
        'std::vector<Rec> load_documented(const char* path) {\n'
        '  std::FILE* f = std::fopen(path, "r");\n'
        '  if (!f) { set_last_error(errno); return {}; }\n'
        '  std::vector<Rec> out; out.push_back(Rec{1}); std::fclose(f); return out;\n'
        '}\n'),
    'store_bad.cc': BAD_41['store.cc']}
FAKE_41 = {'store_fake.cc': (
    '#include <cstdio>\n#include <optional>\n#include <vector>\n'
    'struct Rec { int id; };\n'
    'std::optional<std::vector<Rec>> load_optional(const char* path) {\n'
    '  std::FILE* f = std::fopen(path, "r");\n'
    '  if (!f) { return std::vector<Rec>{}; }  // 换 Optional，错误仍被吞\n'
    '  std::vector<Rec> out; out.push_back(Rec{1}); std::fclose(f);\n'
    '  return out;\n'
    '}\n')}
REAL_41 = {'store_real.cc': (
    '#include <cstdio>\n#include <cerrno>\n#include <variant>\n#include <vector>\n'
    'struct Rec { int id; };\n'
    'struct LoadError { int code; };\n'
    'std::variant<std::vector<Rec>, LoadError> load_strict(const char* path) {\n'
    '  std::FILE* f = std::fopen(path, "r");\n'
    '  if (!f) { return LoadError{errno}; }  // 结果可区分\n'
    '  std::vector<Rec> out; out.push_back(Rec{1}); std::fclose(f);\n'
    '  return out;\n'
    '}\n')}
MISSING_41 = {'erased.cc': (
    'struct Rec { int id; };\n'
    'bool try_load(Rec& out);  // 外层接口只回 bool，错误类型已被抹平\n'
    'bool wrap(Rec& out) { return try_load(out); }\n')}

BAD_42 = {'worker.cc': (
    '#include <stdexcept>\n'
    'void commit(int tx);\n'
    'void log(const char* msg);\n'
    'int tx = 0;\n'
    'int work() {\n'
    '  try {\n'
    '    commit(tx);\n'
    '  } catch (const std::exception& e) {\n'
    '    log(e.what());  // catch 后只有日志\n'
    '  }\n'
    '  return 0;  // 仍向调用方报成功\n'
    '}\n')}
LEGAL_42 = {
    'main_thread.cc': (
        '#include <cstdlib>\n'
        'void serve();\n'
        'void log(const char* msg);\n'
        'int thread_main() {\n'
        '  try {\n'
        '    serve();\n'
        '  } catch (...) {\n'
        '    log("thread exit with error");\n'
        '    return EXIT_FAILURE;  // 线程入口记录后按契约结束任务，不报告成功\n'
        '  }\n'
        '  return EXIT_SUCCESS;\n'
        '}\n'),
    'worker_bad.cc': BAD_42['worker.cc']}
MISSING_42 = {'macro_try.cc': (
    '#define TRY_WRAP(body) try { body } catch (...) { log("wrapped"); }\n'
    'void f() { TRY_WRAP(commit(tx);) }  // try/catch 被宏隐藏\n')}

BAD_43 = {'check3.cc': (
    'struct Port { explicit Port(int p) : v(p) {} int v; };\n'
    'void l2(Port p);\nvoid l3(Port p);\nvoid use(Port p);\n'
    'void l1(Port p) { if (p.v <= 0 || p.v >= 65536) return; l2(p); }\n'
    'void l2(Port p) { if (p.v <= 0 || p.v >= 65536) return; l3(p); }\n'
    'void l3(Port p) { if (p.v <= 0 || p.v >= 65536) return; use(p); }  // 三层重复校验\n')}
LEGAL_43 = {
    'ingest.cc': (
        '// 信任边界：以下数值来自外部进程输入，须重新校验（不可信输入边界声明）。\n'
        'struct Port { explicit Port(int p) : v(p) {} int v; };\n'
        'void use(Port p);\n'
        'void ingest(int raw_port) {\n'
        '  if (raw_port <= 0 || raw_port >= 65536) return;\n'
        '  use(Port{raw_port});\n'
        '}\n'),
    'check3_bad.cc': BAD_43['check3.cc']}
MISSING_43 = {'flow.cc': (
    'struct Port { explicit Port(int p) : v(p) {} int v; };\n'
    'struct Sink { virtual void take(Port p) = 0; };  // 数据流止于抽象接口\n')}

BAD_44 = {'retry.cc': (
    '#include <optional>\n#include <string>\n'
    'struct Req { std::string body; };\n'
    'struct Resp { int code; };\n'
    'std::optional<Resp> transport_post(const Req& r);  // 传输层内部亦重试\n'
    'Resp create(const Req& r) {  // 非幂等：服务端每次新建\n'
    '  for (int i = 0; i < 3; ++i) {  // 调用方重试\n'
    '    if (auto resp = transport_post(r)) return *resp;\n'
    '  }\n'
    '  return Resp{};\n'
    '}\n')}
LEGAL_44 = {
    'query.cc': (
        '#include <optional>\n#include <string>\n'
        'struct Req { std::string body; };\n'
        'struct Resp { int code; };\n'
        'std::optional<Resp> transport_get(const Req& r);\n'
        'Resp query(const Req& r) {  // 只读操作重试属合法例外\n'
        '  for (int i = 0; i < 3; ++i) { if (auto resp = transport_get(r)) return *resp; }\n'
        '  return Resp{};\n'
        '}\n'),
    'retry_bad.cc': BAD_44['retry.cc']}
FAKE_44 = {'retry_fake.cc': (
    '#include <optional>\n#include <string>\n'
    'struct Req { std::string body; };\n'
    'struct Resp { int code; };\n'
    'std::optional<Resp> transport_post_v2(const Req& r);  // 传输层重试仍在\n'
    'Resp create_v2(const Req& r) {  // 改名+调参数，两层仍对同一非幂等操作重试\n'
    '  for (int attempt = 0; attempt < 5; ++attempt) {\n'
    '    if (auto resp = transport_post_v2(r)) return *resp;\n'
    '  }\n'
    '  return Resp{};\n'
    '}\n')}
REAL_44 = {'retry_real.cc': (
    '#include <optional>\n#include <string>\n'
    'struct Req { std::string body; std::string idem_key; };  // 幂等键\n'
    'struct Resp { int code; };\n'
    'std::optional<Resp> submit(const Req& r);  // 重试预算归 transport 单一 owner\n'
    'Resp create_real(const Req& r) { auto resp = submit(r); return resp ? *resp : Resp{}; }\n')}
MISSING_44 = {'hidden_retry.cc': (
    '#include <string>\n'
    'struct Req { std::string body; };\n'
    'Resp lib::submit_with_retry(const Req& r);  // 重试在库内不可见\n')}


class FailureAsSuccess(DesignCase):
    """4.1：行为类——注入失败查可区分性；静态只给线索。"""

    def test_bad_candidate_with_log_only(self):
        p, rep, _ = self.one('4.1', BAD_41)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '4.1', 'candidate', 'bad/4.1')
        facts = self.expect_facts(self.one_finding(rep, '4.1', 'bad/4.1'), '4.1', 'bad/4.1')
        self.assertTrue(facts['failure_sites'], '失败点事实（§4.1）')
        self.assertTrue(facts['log_only'], '只记日志不另报')
        self.assertIsNone(facts['contract_empty_semantics'], '无空集合语义契约')
        self.expect_missing_code(rep, '4.1', 'NO_BEHAVIOR_HARNESS', 'bad/4.1')
        self.expect_missing_code(rep, '4.1', 'NO_CONTRACT', 'bad/4.1')

    def test_contracted_empty_not_reported(self):
        """§4.1 例外：契约明确「不存在⇒空集合，错误另行报告」不报；哨兵仍报。"""
        p, rep, _ = self.one('4.1', LEGAL_41)
        rows = self.findings_for(rep, '4.1')
        self.assertTrue(rows, '哨兵仍报')
        self.assertFalse(any(f['file'] == 'store_doc.cc' for f in rows),
                         '契约明确的空集合语义不触发')

    def test_optional_wrapper_still_reports(self):
        """假修：换 Optional 但错误仍被吞 → 仍报同一根因。"""
        p, rep, _ = self.one('4.1', FAKE_41)
        self.expect_status(rep, '4.1', 'candidate', 'fake/4.1')
        facts = self.expect_facts(self.one_finding(rep, '4.1', 'fake/4.1'), '4.1', 'fake/4.1')
        self.assertIsNone(facts['contract_empty_semantics'], '假修没有引入契约')

    def test_real_fix_not_reported(self):
        p, rep, _ = self.one('4.1', REAL_41)
        self.expect_status(rep, '4.1', 'not_reported', 'real/4.1')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1)

    def test_error_erased_uncovered(self):
        """行内裸码 ERROR_ERASED 定型为 uncovered（见 design_fixtures 规则）。"""
        p, rep, _ = self.one('4.1', MISSING_41)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '4.1', 'uncovered', 'ERROR_ERASED/4.1')
        self.expect_missing_code(rep, '4.1', 'ERROR_ERASED', 'ERROR_ERASED/4.1')


class CatchThenLogOnly(DesignCase):
    """4.2：线索类——结合外层错误出口；不禁顶层捕获。"""

    def test_bad_candidate_log_only(self):
        p, rep, _ = self.one('4.2', BAD_42)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '4.2', 'candidate', 'bad/4.2')
        facts = self.expect_facts(self.one_finding(rep, '4.2', 'bad/4.2'), '4.2', 'bad/4.2')
        self.assertTrue(facts['catch_sites'], 'catch 点事实（§4.2）')
        self.assertFalse(facts['caller_observes'], '调用方观察到成功')
        self.assertFalse(facts['error_propagation'], '错误未传播')

    def test_thread_entry_contract_not_reported(self):
        """§4.2 例外：线程入口记录后按契约结束，不报；哨兵仍报。"""
        p, rep, _ = self.one('4.2', LEGAL_42)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '4.2')],
                         ['worker_bad.cc'], '只有哨兵被报')

    def test_macro_wrapped_catch_uncovered(self):
        p, rep, _ = self.one('4.2', MISSING_42)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '4.2', 'uncovered', 'CATCH_UNRESOLVED/4.2')
        self.expect_missing_code(rep, '4.2', 'CATCH_UNRESOLVED', 'CATCH_UNRESOLVED/4.2')


class UnboundedRepeatedValidation(DesignCase):
    """4.3：人工类——信任边界人工确认，不为去冗余删外部校验。"""

    def test_bad_manual_pending(self):
        p, rep, _ = self.one('4.3', BAD_43, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '4.3', 'manual_pending', 'bad/4.3')
        facts = self.expect_facts(self.one_finding(rep, '4.3', 'bad/4.3'), '4.3', 'bad/4.3')
        self.assertTrue(facts['validation_sites'], '校验点事实（§4.3）')
        self.assertTrue(facts['duplicate_pairs'], '重复校验对非空')
        self.assertIsNone(facts['trust_boundary'], '信任边界未声明')
        self.expect_manual_pending(rep, '4.3', 'bad/4.3')
        self.expect_missing_code(rep, '4.3', 'BOUNDARY_UNKNOWN', 'bad/4.3')

    def test_declared_trust_boundary_not_reported(self):
        """§4.3 例外：不可信输入边界的再校验合法；哨兵仍出包。"""
        p, rep, _ = self.one('4.3', LEGAL_43, manual=True)
        self.expect_status(rep, '4.3', 'manual_pending', 'legal/4.3')
        rows = self.findings_for(rep, '4.3')
        self.assertTrue(rows, '哨兵仍出包')
        self.assertFalse(any(f['file'] == 'ingest.cc' for f in rows),
                         '信任边界内的校验不产生候选')

    def test_flow_partial(self):
        """PARTIAL 族码在人工行 → manual_pending（随 1.3 成对）。"""
        p, rep, _ = self.one('4.3', MISSING_43, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '4.3', 'manual_pending', 'FLOW_PARTIAL/4.3')
        self.expect_missing_code(rep, '4.3', 'FLOW_PARTIAL', 'FLOW_PARTIAL/4.3')


class LayeredRetryAmplification(DesignCase):
    """4.4：行为类——在已写入但应答丢失场景验证；静态只给线索。"""

    def test_bad_candidate_two_layers(self):
        p, rep, _ = self.one('4.4', BAD_44)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '4.4', 'candidate', 'bad/4.4')
        facts = self.expect_facts(self.one_finding(rep, '4.4', 'bad/4.4'), '4.4', 'bad/4.4')
        self.assertGreaterEqual(len(facts['retry_layers']), 2, '调用方+传输层两层重试')
        self.assertIsNone(facts['idempotency_key'], '无幂等键')
        self.assertIsNone(facts['budget_owner'], '预算无单一 owner')
        self.expect_missing_code(rep, '4.4', 'NO_BEHAVIOR_HARNESS', 'bad/4.4')
        self.expect_missing_code(rep, '4.4', 'IDEMPOTENCY_UNKNOWN', 'bad/4.4')

    def test_readonly_retry_not_reported(self):
        """§4.4 例外：只读操作重试不报；哨兵仍报。"""
        p, rep, _ = self.one('4.4', LEGAL_44)
        self.assertEqual([r['file'] for r in self.findings_for(rep, '4.4')],
                         ['retry_bad.cc'], '只有哨兵被报')

    def test_rename_and_rebudget_still_reports(self):
        """假修：改名+调次数，两层仍重试同一非幂等操作 → 仍报。"""
        p, rep, _ = self.one('4.4', FAKE_44)
        self.expect_status(rep, '4.4', 'candidate', 'fake/4.4')
        facts = self.expect_facts(self.one_finding(rep, '4.4', 'fake/4.4'), '4.4', 'fake/4.4')
        self.assertGreaterEqual(len(facts['retry_layers']), 2, '两层重试结构未变')
        self.assertIsNone(facts['idempotency_key'], '假修未引入幂等键')

    def test_real_fix_not_reported(self):
        p, rep, _ = self.one('4.4', REAL_44)
        self.expect_status(rep, '4.4', 'not_reported', 'real/4.4')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1)

    def test_retry_hidden_uncovered(self):
        p, rep, _ = self.one('4.4', MISSING_44)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '4.4', 'uncovered', 'RETRY_HIDDEN/4.4')
        self.expect_missing_code(rep, '4.4', 'RETRY_HIDDEN', 'RETRY_HIDDEN/4.4')


if __name__ == '__main__':
    unittest.main()
