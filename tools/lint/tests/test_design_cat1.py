"""1 数据与状态（1.1–1.6）的冻结预期（T2，来源：映射 §1.1 六行 + §4.5）。

夹具为本地临时目录中的非破坏性示例；1.1 的对照现场按映射 §3（
bbtools-infra@f6e011a Server::State::WriterLoop / Session::queue 的真实结构）
缩样建模。行为项无行为 harness 时按 §5.1 只冻结 candidate。
"""
import unittest

from design_fixtures import DesignCase

# 1.1 同一事实有两个可写来源（人工）：connected 与 state 双写。
BAD_11 = {
    'conn.cc': ('struct Conn {\n'
                '  bool connected = false;\n'
                '  int state = 0;  // 0 idle 1 up 2 down；与 connected 描述同一事实\n'
                '};\n'
                'void mark_up(Conn& c) { c.connected = true; c.state = 1; }\n'
                'void mark_down(Conn& c) { c.connected = false; c.state = 2; }\n'),
}
BAD_11_CONTRACT = {
    'conn.cc': ('struct Conn {\n'
                '  // 契约：connected 是唯一写入口；state 只经 set_state 独占维护。\n'
                '  bool connected = false;\n'
                '  int state = 0;\n'
                '};\n'
                'void mark_up(Conn& c) { c.connected = true; c.state = 1; }\n'
                'void mark_down(Conn& c) { c.connected = false; c.state = 2; }\n'),
}
LEGAL_11 = {
    'view.h': ('#include "conn_bad.cc"\n'
               'struct View {\n'
               '  const Conn& c;\n'
               '  bool up() const { return c.connected; }  // 只读投影\n'
               '};\n'),
    'conn_bad.cc': BAD_11['conn.cc'],
}
# 1.2 基本类型掩盖业务约束（行为）：相邻同型不同单位。
BAD_12 = {
    'sched.cc': ('// timeout_ms 为毫秒；timeout_s 为秒；交换实参仍编译。\n'
                 'void schedule(int timeout_ms, int timeout_s);\n'
                 'void schedule_now(int ms, int s) { schedule(s, ms); }\n'),
}
LEGAL_12 = {
    'sched_strong.cc': ('struct Millis { int v; };\n'
                        'struct Secs { int v; };\n'
                        'void schedule_strong(Millis ms, Secs s);\n'),
    'sched_bad.cc': BAD_12['sched.cc'],
}
FAKE_12 = {
    'sched_fake.cc': ('void schedule(int a, int b);  // 改名去单位注释，类型仍为相邻同型 int\n'
                      'void call() { schedule(5, 5000); }\n'),
}
REAL_12 = {
    'sched_real.cc': ('struct Millis { int v; };\nstruct Secs { int v; };\n'
                      'void schedule_typed(Millis ms, Secs s);\n'
                      'void call_typed() { schedule_typed(Millis{5000}, Secs{5}); }\n'),
}
MISSING_12 = {
    'opaque.cc': ('using Timeout = TimeoutImpl;  // 未定义别名，单位/类型不可解析\n'
                  'void schedule_opaque(Timeout a, Timeout b);\n'),
}
# 1.3 数据总成组穿过多层（人工）：Span 三层重复校验。
BAD_13 = {
    'span.cc': ('struct Span { int begin; int end; };\n'
                'bool ordered(Span s) { return s.begin <= s.end; }\n'
                'void layer2(Span s);\nvoid layer3(Span s);\nvoid use(Span s);\n'
                'void layer1(Span s) { if (!ordered(s)) return; layer2(s); }\n'
                'void layer2(Span s) { if (!ordered(s)) return; layer3(s); }\n'
                'void layer3(Span s) { if (!ordered(s)) return; use(s); }\n'),
}
LEGAL_13 = {
    'pass.h': ('struct Span { int begin; int end; };\n'
               'void pass2(Span s);\nvoid pass3(Span s);\nvoid use(Span s);\n'
               'void pass1(Span s) { pass2(s); }\n'
               'void pass2(Span s) { pass3(s); }\n'
               'void pass3(Span s) { use(s); }\n'),
    'span_bad.cc': BAD_13['span.cc'],
}
MISSING_13_CHAIN = {
    'sink.cc': ('struct Span { int begin; int end; };\n'
                'struct Sink { virtual void consume(Span s) = 0; };  // 链止于抽象调用\n'),
}
MISSING_13_DISPATCH = {
    'tmpl.cc': ('struct Span { int begin; int end; };\n'
                'template <class S> void layer3t(Span s, S sink) { sink(s); }\n'),
}
# 1.4 资源释放散落在退出路径（行为）。
BAD_14 = {
    'handle.cc': ('struct Handle { int fd; };\n'
                  'Handle acquire();\nvoid release(Handle h);\nbool valid(const char* p);\n'
                  'int read_all(Handle h, const char* p);\n'
                  'int load(const char* path) {\n'
                  '  Handle h = acquire();\n'
                  '  if (!valid(path)) { return -1; }  // 此退出路径漏 release\n'
                  '  if (read_all(h, path) < 0) { release(h); return -2; }\n'
                  '  release(h);\n'
                  '  return 0;\n'
                  '}\n'),
}
LEGAL_14 = {
    'guard.cc': ('struct Handle { int fd; };\nHandle acquire();\nvoid release(Handle h);\n'
                 'struct HGuard {\n  Handle h;\n  ~HGuard() { release(h); }  // RAII 作用域所有者\n};\n'
                 'int load2(const char* p) { HGuard g{acquire()}; if (!p) return -1; return 0; }\n'),
    'handle_bad.cc': BAD_14['handle.cc'],
}
FAKE_14 = {
    'fake.cc': ('struct Handle { int fd; };\nHandle acquire();\nvoid release(Handle h);\n'
                'struct Closer { Handle h; void close() { release(h); } };  // 无析构，仍靠逐路径手动\n'
                'int load_fake(const char* p) {\n  Closer c{acquire()};\n'
                '  if (!p) { return -1; }  // 依旧漏 release\n  c.close(); return 0;\n}\n'),
}
REAL_14 = {
    'real.cc': ('struct Handle { int fd; };\nHandle acquire();\nvoid release(Handle h);\n'
                'struct Owner {\n  Handle h;\n  ~Owner() { release(h); }\n};\n'
                'int load_real(const char* p) { Owner o{acquire()}; if (!p) return -1; return 0; }\n'),
}
MISSING_14 = {
    'macro.cc': ('#define ACQUIRE() extern_api_acquire()\n'
                 'struct Handle;\n'
                 'int load_macro() { Handle h = ACQUIRE(); use(h); return 0; }  // 所有权不可解析\n'),
}
# 1.5 跨对象直接操作锁（线索，复用 T102）。
BAD_15 = {
    'use_lock.cc': ('#include <mutex>\n'
                    'struct Obj { std::mutex mu_; };\n'
                    'void work(Obj&);\n'
                    'void batch(Obj& o) {\n'
                    '  std::lock_guard<std::mutex> g(o.mu_);  // 外部对象直接锁成员\n'
                    '  work(o);\n'
                    '}\n'),
}
LEGAL_15 = {
    'proto.cc': ('#include <mutex>\n'
                 'struct Obj { std::mutex mu_; };\n'
                 'void work(Obj&);\n'
                 '// 协议：调用方按 docs/lock-protocol.md:3 持 o.mu_ 以保证 begin_batch 原子性。\n'
                 'void batch_proto(Obj& o) { std::lock_guard<std::mutex> g(o.mu_); work(o); }\n'),
    'lock_bad.cc': BAD_15['use_lock.cc'],
}
MISSING_15 = {
    'alias.cc': ('#define LOCK_ALIAS std::mutex\n'
                 'using Mu = LOCK_ALIAS;  // 锁别名经宏，不可解析\n'
                 'void f(Obj& o) { std::lock_guard<Mu> g(o.mu_); }\n'),
}
DUPLICATE_15 = {
    'duplicate.cc': ('#include <mutex>\n'
                     'struct Obj { std::mutex mu_; };\n'
                     'void first(Obj& o) { std::lock_guard<std::mutex> g(o.mu_); }\n'
                     'void second(Obj& o) { std::lock_guard<std::mutex> g(o.mu_); }\n'),
}
SELF_ALIAS_15 = {
    'self.cc': ('#include <memory>\n#include <mutex>\n'
                'struct Obj : std::enable_shared_from_this<Obj> {\n'
                '  std::mutex mu_;\n'
                '  void lock_self() {\n'
                '    auto self = shared_from_this();\n'
                '    std::lock_guard<std::mutex> g(self->mu_);\n'
                '  }\n'
                '};\n'),
}
SELF_ALIAS_REBOUND_15 = {
    'rebound.cc': ('#include <memory>\n#include <mutex>\n'
                   'struct Obj : std::enable_shared_from_this<Obj> {\n'
                   '  std::mutex mu_;\n'
                   '  void lock_other(std::shared_ptr<Obj> other) {\n'
                   '    auto self = shared_from_this();\n'
                   '    self = other;\n'
                   '    std::lock_guard<std::mutex> g(self->mu_);\n'
                   '  }\n'
                   '};\n'),
}
SELF_ALIAS_SAME_LINE_15 = {
    'same_line.cc': ('#include <memory>\n#include <mutex>\n'
                     'struct Obj : std::enable_shared_from_this<Obj> {\n'
                     '  std::mutex mu_;\n'
                     '  void lock_self() { auto self = shared_from_this(); '
                     'std::lock_guard<std::mutex> g(self->mu_); }\n'
                     '};\n'),
}
MULTIPLE_RECEIVERS_15 = {
    'multiple.cc': ('#include <memory>\n#include <mutex>\n'
                    'struct Obj : std::enable_shared_from_this<Obj> {\n'
                    '  int flag_;\n'
                    '  std::mutex mu_;\n'
                    '  void lock_other(std::shared_ptr<Obj> other) {\n'
                    '    auto self = shared_from_this();\n'
                    '    auto value = self->flag_; std::lock_guard<std::mutex> g(other->mu_);\n'
                    '  }\n'
                    '};\n'),
}
SHADOWED_EXTERNAL_15 = {
    'shadowed.cc': ('#include <memory>\n#include <mutex>\n'
                    'struct Obj : std::enable_shared_from_this<Obj> {\n'
                    '  std::mutex mu_;\n'
                    '  void lock_external(std::shared_ptr<Obj> self) {\n'
                    '    { auto self = shared_from_this(); }\n'
                    '    std::lock_guard<std::mutex> g(self->mu_);\n'
                    '  }\n'
                    '};\n'),
}
MIXED_SELF_EXTERNAL_15 = {
    'mixed.cc': ('#include <memory>\n#include <mutex>\n'
                 '\n'
                 'struct Obj : std::enable_shared_from_this<Obj> {\n'
                 '  std::mutex mu_;\n'
                 '};\n'
                 '\n'
                 'struct Peer : std::enable_shared_from_this<Peer> {\n'
                 '  std::mutex mu_;\n'
                 '  std::shared_ptr<Obj> peer_;\n'
                 '  void lock_foreign_via_member() {\n'
                 '    auto peer = this->peer_;  // 成员 shared_ptr 的局部副本\n'
                 '    std::lock_guard<std::mutex> a(this->peer_->mu_);\n'
                 '    std::lock_guard<std::mutex> b(peer->mu_);\n'
                 '  }\n'
                 '  void lock_foreign_via_alien(std::shared_ptr<Obj> other) {\n'
                 '    auto alien = other->shared_from_this();  // other 上的 shared_from_this\n'
                 '    std::lock_guard<std::mutex> c(alien->mu_);\n'
                 '  }\n'
                 '  void lock_own_this() {\n'
                 '    std::lock_guard<std::mutex> s(this->mu_);\n'
                 '  }\n'
                 '  void lock_own_alias() {\n'
                 '    auto self = shared_from_this();\n'
                 '    std::lock_guard<std::mutex> t(self->mu_);\n'
                 '  }\n'
                 '};\n'),
}
# 1.6 取消与完成各自兑现一次回调（行为）。
BAD_16 = {
    'job.cc': ('#include <functional>\n'
               'struct Job {\n'
               '  std::function<void(int)> on_done;  // 终态回调\n'
               '  void cancel() { if (on_done) on_done(-1); }\n'
               '  void complete(int rc) { if (on_done) on_done(rc); }  // 两路都可触发\n'
               '};\n'),
}
LEGAL_16 = {
    'guarded.cc': ('#include <atomic>\n#include <functional>\n'
                   'struct JobG {\n  std::function<void(int)> on_done;\n  std::atomic<bool> settled_{false};\n'
                   '  void cancel() { if (settled_.exchange(true)) return; on_done(-1); }\n'
                   '  void complete(int rc) { if (settled_.exchange(true)) return; on_done(rc); }\n'
                   '};\n'),
    'job_bad.cc': BAD_16['job.cc'],
}
FAKE_16 = {
    'fake.cc': ('#include <functional>\n'
                'struct JobF {\n  std::function<void(int)> handler;  // 只改名\n'
                '  void cancel() { auto fire = [&](int rc) { if (handler) handler(rc); }; fire(-1); }\n'
                '  void complete(int rc) { auto fire = [&](int rc) { if (handler) handler(rc); }; fire(rc); }\n'
                '};\n'),
}
REAL_16 = {
    'real.cc': ('#include <atomic>\n#include <functional>\n'
                'struct JobR {\n  std::function<void(int)> on_done;\n  std::atomic<bool> settled_{false};\n'
                '  bool claim() { return !settled_.exchange(true); }\n'
                '  void cancel() { if (claim()) on_done(-1); }\n'
                '  void complete(int rc) { if (claim()) on_done(rc); }\n'
                '};\n'),
}
MISSING_16 = {
    'detached.cc': ('#include <thread>\n#include <functional>\n'
                    'struct JobD {\n  std::function<void(int)> on_done;\n'
                    '  void arm() { std::thread([this] { if (on_done) on_done(0); }).detach(); }\n'
                    '};  // 线程模型不可控，竞态不可重放\n'),
}


class DualWritableSource(DesignCase):
    """1.1：人工类上限 manual_pending；契约在只改 facts，不升 violation。"""

    def test_bad_manual_pending_with_writer_facts(self):
        # 有效 CDB：1.1 的字段写点分析要求编译输入（缺 CDB 归 test_no_index_uncovered）。
        p, rep, _ = self.one('1.1', BAD_11, manual=True, cdb=True)
        self.assertEqual(p.returncode, 0, 'manual_pending 不强制 exit 2')
        self.assertIn('conn.cc', rep['coverage']['tus'], 'CDB 对应 TU 已实际解析')
        self.expect_status(rep, '1.1', 'manual_pending', 'bad/1.1')
        row = self.one_finding(rep, '1.1', 'bad/1.1')
        facts = self.expect_facts(row, '1.1', 'bad/1.1')
        self.assertTrue(facts['writers'], '写入者集合可机械列（§1.1）')
        self.assertIsNone(facts['unique_writer_contract'], '无契约声明')
        self.expect_manual_pending(rep, '1.1', 'bad/1.1')
        self.expect_missing_code(rep, '1.1', 'NO_CONTRACT', 'bad/1.1')
        self.expect_missing_code(rep, '1.1', 'NO_BEHAVIOR_HARNESS', 'bad/1.1')

    def test_contract_present_still_manual(self):
        """§1.1：双写需契约或行为；只有契约不得判 violation（人工上限）。"""
        p, rep, _ = self.one('1.1', BAD_11_CONTRACT, manual=True, cdb=True)
        self.expect_status(rep, '1.1', 'manual_pending', 'contract/1.1')
        facts = self.expect_facts(self.one_finding(rep, '1.1', 'contract/1.1'), '1.1', 'contract/1.1')
        self.assertIsNotNone(facts['unique_writer_contract'], '契约进入事实')
        self.assertEqual(p.returncode, 0)

    def test_readonly_projection_not_reported(self):
        """§1.1 例外：只读投影不报；哨兵坏例同树仍出包（不是漏扫）。"""
        p, rep, _ = self.one('1.1', LEGAL_11, manual=True, cdb=True)
        self.expect_status(rep, '1.1', 'manual_pending', 'legal/1.1')
        self.assertIn('view.h', rep['coverage']['tus'], '只读投影 TU 已实际解析（不是漏扫）')
        self.assertIn('conn_bad.cc', rep['coverage']['tus'], '哨兵 TU 已实际解析')
        self.assertTrue(self.findings_for(rep, '1.1'), '哨兵坏例仍出证据包')
        self.assertFalse(any(f['file'] == 'view.h' for f in self.findings_for(rep, '1.1')),
                         '只读投影不产生候选')

    def test_no_index_uncovered(self):
        """§1.1 缺输入：索引/构建输入缺失 → uncovered/NO_INDEX。"""
        p, rep, _ = self.one('1.1', BAD_11, manual=True, cdb=False)
        self.assertEqual(p.returncode, 2, 'uncovered → exit 2（§4.4）')
        self.expect_status(rep, '1.1', 'uncovered', 'NO_INDEX/1.1')
        self.expect_missing_code(rep, '1.1', 'NO_INDEX', 'NO_INDEX/1.1')

    def test_partial_cross_tu_writes(self):
        """§1.1 缺输入：跨 TU 写入点不可见 → manual_pending/WRITES_PARTIAL。"""
        files = {**BAD_11, 'extra_writer.cc':
                 ('struct Conn { bool connected = false; int state = 0; };\n'
                  'void remote_reset(Conn& c) { c.connected = false; }  // 另一 TU 的写入点\n')}
        root = self.put_tree(files, cdb=True)
        # 把 extra_writer.cc 排除在 CDB 之外：重写 CDB 只含 conn.cc。
        self.put('build-vscode/compile_commands.json',
                 __import__('json').dumps(
                     [{'directory': str(root), 'command': f'c++ -std=c++17 -I{root} conn.cc',
                       'file': 'conn.cc'}], indent=1), root=root)
        self.put_design_config(manual=('1.1',), cdb=True, root=root)
        p, rep = self.design_report(ctx='partial/1.1', keys=('1.1',), root=root)
        self.assertEqual(p.returncode, 0, '降级候选不强制 exit 2')
        self.expect_status(rep, '1.1', 'manual_pending', 'partial/1.1')
        self.expect_missing_code(rep, '1.1', 'WRITES_PARTIAL', 'partial/1.1')


class BasicTypeUnits(DesignCase):
    """1.2：行为类；无编译 harness 只 candidate，swap_compiles=null 不判违反。"""

    def test_bad_candidate_with_unit_facts(self):
        p, rep, _ = self.one('1.2', BAD_12)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '1.2', 'candidate', 'bad/1.2')
        row = self.one_finding(rep, '1.2', 'bad/1.2')
        facts = self.expect_facts(row, '1.2', 'bad/1.2')
        self.assertTrue(facts['same_type_adjacent_pairs'], '相邻同型参数对（§1.2）')
        self.assertTrue(facts['params'], 'params 事实非空')
        self.assertIsNone(facts['swap_compiles'], '无编译测试 → null，不判违反')
        self.expect_missing_code(rep, '1.2', 'NO_BEHAVIOR_HARNESS', 'bad/1.2')

    def test_strong_types_not_reported(self):
        p, rep, _ = self.one('1.2', LEGAL_12)
        self.assertTrue(self.findings_for(rep, '1.2'), '哨兵坏例仍报')
        self.assertFalse(any(f['file'] == 'sched_strong.cc' for f in self.findings_for(rep, '1.2')),
                         '强类型不触发该根因')

    def test_rename_without_docs_still_reports(self):
        """假修：去掉单位文档、参数改名，相邻同型仍在 → 仍报同一根因。"""
        p, rep, _ = self.one('1.2', FAKE_12)
        self.expect_status(rep, '1.2', 'candidate', 'fake/1.2')
        facts = self.expect_facts(self.one_finding(rep, '1.2', 'fake/1.2'), '1.2', 'fake/1.2')
        self.assertTrue(facts['same_type_adjacent_pairs'], '相邻同型对仍在（假修后仍报）')

    def test_real_fix_not_reported(self):
        """真修：强类型落地 → not_reported，且检查确实扫描（coverage 有文件）。"""
        p, rep, _ = self.one('1.2', REAL_12)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '1.2', 'not_reported', 'real/1.2')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1, '真修不是漏扫')

    def test_unresolved_alias_uncovered(self):
        p, rep, _ = self.one('1.2', MISSING_12)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '1.2', 'uncovered', 'TYPE_UNRESOLVED/1.2')
        self.expect_missing_code(rep, '1.2', 'TYPE_UNRESOLVED', 'TYPE_UNRESOLVED/1.2')


class GroupThroughLayers(DesignCase):
    """1.3：人工类；三层重复校验出包，不判干净。"""

    def test_bad_manual_pending(self):
        p, rep, _ = self.one('1.3', BAD_13, manual=True)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '1.3', 'manual_pending', 'bad/1.3')
        facts = self.expect_facts(self.one_finding(rep, '1.3', 'bad/1.3'), '1.3', 'bad/1.3')
        self.assertTrue(facts['layers'], '跨层事实非空（§1.3）')
        self.assertIsNone(facts['shared_invariant_contract'], '无约束声明 → 不能判')
        self.expect_manual_pending(rep, '1.3', 'bad/1.3')
        self.expect_missing_code(rep, '1.3', 'NO_CONTRACT', 'bad/1.3')

    def test_pass_through_not_reported(self):
        """§1.3 例外：结构体透传但各层不重复校验 → 无候选；哨兵仍出包。"""
        p, rep, _ = self.one('1.3', LEGAL_13, manual=True)
        self.expect_status(rep, '1.3', 'manual_pending', 'legal/1.3')
        self.assertTrue(self.findings_for(rep, '1.3'), '哨兵坏例仍出包')
        self.assertFalse(any(f['file'] == 'pass.h' for f in self.findings_for(rep, '1.3')),
                         '透传不产生候选')

    def test_chain_partial(self):
        p, rep, _ = self.one('1.3', MISSING_13_CHAIN, manual=True)
        self.assertEqual(p.returncode, 0, 'manual 类缺输入随包给出，不强制 2')
        self.expect_status(rep, '1.3', 'manual_pending', 'CHAIN_PARTIAL/1.3')
        self.expect_missing_code(rep, '1.3', 'CHAIN_PARTIAL', 'CHAIN_PARTIAL/1.3')

    def test_template_dispatch_unresolved(self):
        """行内裸码 DISPATCH_UNRESOLVED 定型为 uncovered（见 design_fixtures 规则）。"""
        p, rep, _ = self.one('1.3', MISSING_13_DISPATCH, manual=True)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '1.3', 'uncovered', 'DISPATCH/1.3')
        self.expect_missing_code(rep, '1.3', 'DISPATCH_UNRESOLVED', 'DISPATCH/1.3')


class ReleaseScatteredExits(DesignCase):
    """1.4：行为类；静态只给线索 candidate。"""

    def test_bad_candidate_with_exit_path_facts(self):
        p, rep, _ = self.one('1.4', BAD_14)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '1.4', 'candidate', 'bad/1.4')
        facts = self.expect_facts(self.one_finding(rep, '1.4', 'bad/1.4'), '1.4', 'bad/1.4')
        self.assertTrue(facts['exit_paths'], '退出路径事实（§1.4）')
        self.assertFalse(facts['raii_wrapper'], '无 RAII 包装')
        self.assertTrue(facts['uncovered_paths'], '漏释放路径非空')
        self.expect_missing_code(rep, '1.4', 'NO_BEHAVIOR_HARNESS', 'bad/1.4')

    def test_raii_not_reported_sentinel_kept(self):
        p, rep, _ = self.one('1.4', LEGAL_14)
        self.assertTrue(self.findings_for(rep, '1.4'), '哨兵坏例仍报')
        self.assertFalse(any(f['file'] == 'guard.cc' for f in self.findings_for(rep, '1.4')),
                         'RAII 覆盖的路径不触发')

    def test_manual_close_helper_still_reports(self):
        """假修：释放收进 close() 但仍逐路径手动 → 同一根因仍报。"""
        p, rep, _ = self.one('1.4', FAKE_14)
        self.expect_status(rep, '1.4', 'candidate', 'fake/1.4')
        facts = self.expect_facts(self.one_finding(rep, '1.4', 'fake/1.4'), '1.4', 'fake/1.4')
        self.assertFalse(facts['raii_wrapper'], 'close() 帮手不是 RAII')
        self.assertTrue(facts['uncovered_paths'], '假修后仍有漏释放路径')

    def test_real_fix_not_reported(self):
        p, rep, _ = self.one('1.4', REAL_14)
        self.expect_status(rep, '1.4', 'not_reported', 'real/1.4')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1)

    def test_ownership_unknown_uncovered(self):
        p, rep, _ = self.one('1.4', MISSING_14)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '1.4', 'uncovered', 'OWNERSHIP/1.4')
        self.expect_missing_code(rep, '1.4', 'OWNERSHIP_UNKNOWN', 'OWNERSHIP/1.4')


class CrossObjectLock(DesignCase):
    """1.5：线索类，复用 T102 形状；协议明确不报。"""

    def test_bad_candidate_with_t102_fact(self):
        p, rep, _ = self.one('1.5', BAD_15)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '1.5', 'candidate', 'bad/1.5')
        facts = self.expect_facts(self.one_finding(rep, '1.5', 'bad/1.5'), '1.5', 'bad/1.5')
        self.assertTrue(facts['t102_candidate'], 'T102 形状事实（§1.5）')
        self.assertIsNotNone(facts['lock_decl'], '锁声明事实')
        self.assertIsNone(facts['protocol_ref'], '无协议文档 → 只 candidate')

    def test_documented_protocol_not_reported(self):
        """§1.5 例外：按协议持锁且有协议位置 → 不报；哨兵仍报。"""
        p, rep, _ = self.one('1.5', LEGAL_15)
        self.assertTrue(self.findings_for(rep, '1.5'), '哨兵坏例仍报')
        self.assertFalse(any(f['file'] == 'proto.cc' for f in self.findings_for(rep, '1.5')),
                         '协议持锁不产生候选')

    def test_lock_alias_unresolved(self):
        p, rep, _ = self.one('1.5', MISSING_15)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '1.5', 'uncovered', 'LOCK/1.5')
        self.expect_missing_code(rep, '1.5', 'LOCK_UNRESOLVED', 'LOCK/1.5')

    def test_same_lock_is_aggregated(self):
        p, rep, _ = self.one('1.5', DUPLICATE_15)
        rows = self.findings_for(rep, '1.5')
        self.assertEqual(p.returncode, 0)
        self.assertEqual(len(rows), 1, '同一锁声明只保留一个候选')
        self.assertEqual(len(rows[0]['facts']['external_access']), 2, '保留全部访问点')

    def test_shared_from_this_alias_is_not_external(self):
        p, rep, _ = self.one('1.5', SELF_ALIAS_15)
        self.assertEqual(p.returncode, 0)
        self.assertFalse(self.findings_for(rep, '1.5'), 'owner 自身别名持有的锁不算跨对象锁')

    def test_shared_from_this_alias_rebound_to_external_is_reported(self):
        p, rep, _ = self.one('1.5', SELF_ALIAS_REBOUND_15)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(self.findings_for(rep, '1.5'), '自身别名重绑定到外部对象后应保留候选')

    def test_shared_from_this_alias_on_same_line_is_not_external(self):
        p, rep, _ = self.one('1.5', SELF_ALIAS_SAME_LINE_15)
        self.assertEqual(p.returncode, 0)
        self.assertFalse(self.findings_for(rep, '1.5'), '同行建立的自身别名持锁不算跨对象锁')

    def test_lock_receiver_comes_from_matching_ast_member(self):
        p, rep, _ = self.one('1.5', MULTIPLE_RECEIVERS_15)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(self.findings_for(rep, '1.5'), '同一行多个 -> 时应按锁成员节点取 receiver')

    def test_inner_self_alias_does_not_hide_outer_external_lock(self):
        p, rep, _ = self.one('1.5', SHADOWED_EXTERNAL_15)
        self.assertEqual(p.returncode, 0)
        self.assertTrue(self.findings_for(rep, '1.5'), '内层同名自身别名不能隐藏外层外部锁')

    def test_mixed_tu_aggregates_only_external_sites_per_lock_decl(self):
        """同一 TU：真正自身（this / shared_from_this）不产生访问点；成员
        shared_ptr 的局部副本、this->peer_->mu_、other 上 shared_from_this
        得到的对象都报，并按锁声明聚合进同一 finding 的 external_access。"""
        p, rep, _ = self.one('1.5', MIXED_SELF_EXTERNAL_15)
        self.assertEqual(p.returncode, 0)
        text = MIXED_SELF_EXTERNAL_15['mixed.cc'].splitlines()

        def site(fragment):
            return next(i for i, value in enumerate(text, 1) if fragment in value)

        external = [site('a(this->peer_->mu_)'), site('b(peer->mu_)'), site('c(alien->mu_)')]
        own = [site('s(this->mu_)'), site('t(self->mu_)')]
        self.expect_status(rep, '1.5', 'candidate', 'mixed/1.5')
        row = self.one_finding(rep, '1.5', 'mixed/1.5')
        self.assertEqual(row['file'], 'mixed.cc', 'finding 相对 --root（§4.3）')
        facts = self.expect_facts(row, '1.5', 'mixed/1.5')
        self.assertEqual(facts['lock_decl']['owner'], 'Obj',
                         '只聚合外部锁声明 Obj::mu_；Peer::mu_ 全为自身访问不设候选')
        access = facts['external_access']
        self.assertEqual([a['line'] for a in access], external,
                         f'external_access 逐点保留三种外部形态（行 {external}），'
                         f'自身两处（行 {own}）不得进入访问点')
        self.assertIn('this->peer_->mu_', access[0]['expression'], '成员链直达锁的表达式入访问点')
        self.assertIn('peer->mu_', access[1]['expression'], '成员 shared_ptr 局部副本的访问点保留')
        self.assertIn('alien->mu_', access[2]['expression'], 'other 上的 shared_from_this 得到的对象仍报')
        self.assertIn('lock_foreign_via_member', access[0]['enclosing'], '访问点归属实际所在函数')
        self.assertIn('lock_foreign_via_member', access[1]['enclosing'], '访问点归属实际所在函数')
        self.assertIn('lock_foreign_via_alien', access[2]['enclosing'], '访问点归属实际所在函数')


class CallbackOnce(DesignCase):
    """1.6：行为类；无 harness 只 candidate。"""

    def test_bad_candidate_with_sites(self):
        p, rep, _ = self.one('1.6', BAD_16)
        self.assertEqual(p.returncode, 0)
        self.expect_status(rep, '1.6', 'candidate', 'bad/1.6')
        facts = self.expect_facts(self.one_finding(rep, '1.6', 'bad/1.6'), '1.6', 'bad/1.6')
        self.assertTrue(facts['cancel_sites'] and facts['complete_sites'], '两路触发点（§1.6）')
        self.assertFalse(facts['once_guard'], '无 once 保护')
        self.assertIsNone(facts['notifications_observed'], '未重放，不冒称观察值')
        self.expect_missing_code(rep, '1.6', 'NO_BEHAVIOR_HARNESS', 'bad/1.6')
        self.expect_missing_code(rep, '1.6', 'NO_CONTRACT', 'bad/1.6')

    def test_once_guard_not_reported(self):
        p, rep, _ = self.one('1.6', LEGAL_16)
        self.assertTrue(self.findings_for(rep, '1.6'), '哨兵坏例仍报')
        self.assertFalse(any(f['file'] == 'guarded.cc' for f in self.findings_for(rep, '1.6')),
                         '共享 once 保护不触发')

    def test_rename_and_lambda_still_reports(self):
        """假修：改名 + lambda 包装，两路仍各自触发 → 仍报。"""
        p, rep, _ = self.one('1.6', FAKE_16)
        self.expect_status(rep, '1.6', 'candidate', 'fake/1.6')
        facts = self.expect_facts(self.one_finding(rep, '1.6', 'fake/1.6'), '1.6', 'fake/1.6')
        self.assertFalse(facts['once_guard'], '假修没有引入共享保护')

    def test_real_fix_not_reported(self):
        p, rep, _ = self.one('1.6', REAL_16)
        self.expect_status(rep, '1.6', 'not_reported', 'real/1.6')
        self.assertGreaterEqual(rep['coverage']['files_scanned'], 1)

    def test_race_unreproducible_uncovered(self):
        """行内裸码 RACE_UNREPRODUCIBLE 定型为 uncovered（见 design_fixtures 规则）。"""
        p, rep, _ = self.one('1.6', MISSING_16)
        self.assertEqual(p.returncode, 2)
        self.expect_status(rep, '1.6', 'uncovered', 'RACE/1.6')
        self.expect_missing_code(rep, '1.6', 'RACE_UNREPRODUCIBLE', 'RACE/1.6')


if __name__ == '__main__':
    unittest.main()
