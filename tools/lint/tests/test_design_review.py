"""评审线索三件套（R1 similar-functions / R2 complexity-delta / 2.3 收紧版）的正反例回归。

预期来源：三个检查的 issue 验收契约（不从工具输出反推）：
- R1 跨文件完全相同的长函数体命中 identical，只差少量记号的长函数体命中 near；
  差异记号按原样保留；原始 token 数不足 80 或净行数不足 8 的短样板不报；
  差异合计超过 12 个 token 不报；lizard 1.25.0 后端缺失必须 uncovered/NO_MEASUREMENT_BACKEND。
- R2 无基线时超阈函数标记 inventory 且 before=None；有基线时 new/worsened 才上报并带
  before/after/threshold；未超阈不报；测量范围默认只含 bbt/**/*.hpp 与 bbt/**/*.cc。
- 2.3 只在调用方+包装层+委托目标三者可定位时出候选；类型标记、公开接口、所有权、
  同步语义、附加行为（如先 require 再转发）均排除；没有可定位调用方不报。

每个用例的注释写清它独有的错误检出能力；哨兵用例证明扫描本身没有失效。
R2 复用 tools/complexity 的实现，本文件在 setUp 把它补进临时 tools 副本（既有
_support.py 只复制 lint/git-hooks，不能改），R1 不需要它但同树复制无害。
"""
import importlib.util
import shutil
from pathlib import Path
import sys
import tempfile
import types
import unittest

from design_fixtures import DesignCase, DesignGitCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'core'))

LIZARD_SPEC = importlib.util.find_spec('lizard')
if LIZARD_SPEC is None or not LIZARD_SPEC.origin:
    raise ImportError('the review tests require lizard 1.25.0 in the test environment')
LIZARD_SP = str(Path(LIZARD_SPEC.origin).parent)

CFG_R1 = f'[design."design.similar-functions"]\nlizard_path = "{LIZARD_SP}"\n'
CFG_R2 = f'[design."design.complexity-delta"]\nlizard_path = "{LIZARD_SP}"\n'


def make_copying(cls):
    """DesignCase/DesignGitCase 之上补复制 tools/complexity（R2 的运行时依赖）。"""

    class WithComplexity(cls):
        def setUp(self):
            super().setUp()
            from _support import PUB
            shutil.copytree(PUB / 'complexity', self.tools / 'complexity',
                            ignore=shutil.ignore_patterns('__pycache__', 'tests'))

    return WithComplexity


def review_status(case, rep, key, status, ctx):
    """R1/R2 不在冻结的 DESIGN_KEYS/CLASS 映射里（design_fixtures 不可改），
    本助手按契约直接断言 canonical key、source_ref 与 clue 判定类。"""
    checks = rep.get('checks') or []
    rows = [c for c in checks if c.get('key') == key]
    case.assertEqual(len(rows), 1, f'{ctx}: checks[] 里 {key} 应恰一条，得 {rows}')
    row = rows[0]
    case.assertEqual(row.get('source_ref'), {'design.similar-functions': 'R1',
                                             'design.complexity-delta': 'R2'}[key],
                     f'{ctx}: {key} source_ref（issue 验收摘要 R1/R2）')
    case.assertEqual(row.get('class'), 'clue', f'{ctx}: {key} 判定类应为 clue')
    case.assertIs(row.get('enabled'), True, f'{ctx}: {key} 应为启用')
    case.assertEqual(row.get('status'), status, f'{ctx}: {key} 应 {status}，得 {row}')
    return row


class ReviewAssert:
    def review_status(self, rep, key, status, ctx):
        return review_status(self, rep, key, status, ctx)


class ReviewCase(ReviewAssert, make_copying(DesignCase)):
    pass


class ReviewGitCase(ReviewAssert, make_copying(DesignGitCase)):
    pass


def hot_source(name, branches):
    """顺序 if 链生成高圈复杂度函数：CCN = branches + 1，认知复杂度 = branches。"""
    lines = [f'int {name}(int value, int limit) {{', '  int total = 0;']
    for i in range(branches):
        lines.append(f'  if ((value + {i}) % {i + 3} == 0) {{ total += {i} + 1; }}')
    lines += ['  return total + limit;', '}', '']
    return '\n'.join(lines)


# ---- R1 夹具：handle_readiness 共 132 个原始 token、净行数 25，远超 80/8 门槛 ----
READY = '''static int handle_readiness(int events, int timeout_ms) {
  int accepted = 0;
  int skipped = 0;
  int budget = timeout_ms;
  for (int round = 0; round < 8 && budget > 0; ++round) {
    if (events & READABLE) {
      accepted += poll_socket(round, budget);
      budget -= 10;
    } else if (events & HANGUP) {
      skipped += 1;
      budget -= 5;
    } else {
      budget -= 1;
    }
    if (accepted > 32) {
      flush_backlog(accepted);
      accepted = 0;
    }
    while (skipped > 4) {
      skipped -= 2;
      budget += 1;
    }
  }
  return accepted + skipped + budget;
}
'''
# 与 READY 只差 2+2 个记号：函数名自身与事件枚举名，差异应保持原样出现在 facts 里。
WRITE = READY.replace('handle_readiness', 'handle_writability').replace('READABLE', 'WRITEABLE')
# 长度相近、骨架相同但大段逻辑不同：38 个差异记号，远超 12 的上限。
DIVERGED = READY.replace('accepted += poll_socket(round, budget);', 'accepted -= drain_socket(budget, round);')
DIVERGED = DIVERGED.replace('budget -= 10;', 'budget += 7;')
DIVERGED = DIVERGED.replace('skipped += 1;', 'skipped ^= 3;')
DIVERGED = DIVERGED.replace('budget -= 5;', 'budget = budget << 1;')
DIVERGED = DIVERGED.replace('budget -= 1;', 'budget = budget >> 1;')
DIVERGED = DIVERGED.replace('accepted > 32', 'accepted >= 64')
DIVERGED = DIVERGED.replace('flush_backlog(accepted);', 'flush_backlog(budget);')
DIVERGED = DIVERGED.replace('skipped -= 2;', 'skipped = 0;')
# 完全相同但只有 ~50 token 的短样板。
SHORTY = '''static int read_header(int fd) {
  int status = wait_socket(fd, 4);
  if (status < 0) {
    return -1;
  }
  int length = status + 2;
  if (length > 64) {
    length = 64;
  }
  return length;
}
'''
SAME_LINE_FUNCTIONS = ' '.join(
    f'static int f{i}() {{ int value = {i}; return value; }}'
    for i in range(12)
) + '\n'
SAME_END_LINE_FUNCTIONS = READY[:-2] + '} static int tail() { return 1; }\n'

# ---- 2.3 夹具 ----
IMPL_AND_SHELL = '''struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
class Sh {
  friend int use_shell();
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
'''
CROSS_TU = {'shell.h': IMPL_AND_SHELL,
            'user.cc': ('#include "shell.h"\n'
                        'int use_shell() {\n'
                        '  int first = Sh::a();\n'
                        '  int second = Sh::b();\n'
                        '  return first + second;\n'
                        '}\n')}
TYPE_MARKER = {'shell_traits.h': ('#include <type_traits>\n'
                                  + '''struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
struct Sh {
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
''' +
                                  'template <typename W>\n'
                                  'int pick() {\n'
                                  '  if constexpr (std::is_base_of<Impl, W>::value) {\n'
                                  '    return W::a();\n'
                                  '  }\n'
                                  '  return W::a() + W::b();\n'
                                  '}\n'),
               'user.cc': ('#include "shell_traits.h"\n'
                           'int run_pick() {\n'
                           '  return pick<Sh>();\n'
                           '}\n')}
EXTRA_BEHAVIOR = {'gate.h': ('struct Impl {\n'
                             '  static int a() { return 1; }\n'
                             '  static int b() { return 2; }\n'
                             '};\n'
                             'void require(int tok);\n'
                             'struct Gate {\n'
                             '  static int a(int tok) { require(tok); return Impl::a(); }\n'
                             '  static int b(int tok) { require(tok); return Impl::b(); }\n'
                             '};\n'
                             'class Sh {\n'
                             '  friend int run_gate();\n'
                             '  static int a() { return Impl::a(); }\n'
                             '  static int b() { return Impl::b(); }\n'
                             '};\n'),
                  'user.cc': ('#include "gate.h"\n'
                              'int run_gate() {\n'
                              '  int via_gate = Gate::a(1) + Gate::b(1);\n'
                              '  int via_shell = Sh::a() + Sh::b();\n'
                              '  return via_gate + via_shell;\n'
                              '}\n')}


class SimilarFunctions(ReviewCase):
    """R1 design.similar-functions：跨文件长拷贝线索。"""

    def report_for(self, files, rules=('design.similar-functions',), extra=CFG_R1):
        root = self.put_tree(files)
        self.put_design_config(rules=rules, extra=extra, root=root)
        return self.design_report(ctx='R1', keys=rules, root=root)

    def test_identical_copy_across_files_reported(self):
        """契约：跨文件完全相同的 >=80 token 长函数体命中 identical，两侧 path/行号正确。
        独有检出：exact 分组失效（如符号表误把两个相同体当作一个）时本例零命中。"""
        p, rep = self.report_for({'poller_a.cc': READY, 'poller_b.cc': READY})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.similar-functions', 'candidate', 'identical/R1')
        row = self.one_finding(rep, 'design.similar-functions', 'identical/R1')
        facts = row['facts']
        self.assertEqual(facts['match'], 'identical', '完全相同应报 identical')
        self.assertEqual(facts['left']['path'], 'poller_a.cc')
        self.assertEqual(facts['right']['path'], 'poller_b.cc')
        self.assertEqual(facts['left']['line'], 1, '夹具函数从第 1 行开始')
        self.assertGreater(facts['left']['end_line'], facts['left']['line'], 'end_line 覆盖整个函数体')
        self.assertIn('handle_readiness', facts['left']['function'], '两侧函数名原样保留')
        self.assertIn('handle_readiness', facts['right']['function'])
        self.assertEqual(facts['token_counts'][0], facts['token_counts'][1], 'identical 两侧 token 数相同')
        self.assertGreaterEqual(facts['token_counts'][0], 80, '命中对象必须超过短样板门槛')
        self.assertEqual(facts['differences'], {'left_only': [], 'right_only': []}, 'identical 无差异记号')
        self.assertEqual(facts['difference_count'], 0)

    def test_near_copy_differences_keep_verbatim_names(self):
        """契约：只差少量记号的长函数体命中 near，差异里能看到 READABLE/WRITEABLE 与函数名本身。
        独有检出：若差异被归一化（常量/调用名折叠）或按行比对，这两个拼写不会原样出现。"""
        p, rep = self.report_for({'readiness.cc': READY, 'writability.cc': WRITE})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.similar-functions', 'candidate', 'near/R1')
        row = self.one_finding(rep, 'design.similar-functions', 'near/R1')
        facts = row['facts']
        self.assertEqual(facts['match'], 'near', '仅少量记号差异应报 near')
        self.assertEqual(facts['left']['path'], 'readiness.cc')
        self.assertEqual(facts['right']['path'], 'writability.cc')
        self.assertIn('handle_writability', facts['right']['function'], '右侧函数名原样保留')
        self.assertEqual(facts['differences']['left_only'], ['handle_readiness', 'READABLE'],
                         '左侧独有记号应是函数名与事件枚举本身')
        self.assertEqual(facts['differences']['right_only'], ['handle_writability', 'WRITEABLE'],
                         '右侧独有记号应是改名后的拼写本身')
        self.assertEqual(facts['difference_count'], 4, '合计 4 个差异记号，在 12 上限之内')
        self.assertGreaterEqual(min(facts['token_counts']), 80)

    def test_short_identical_bodies_not_reported(self):
        """契约：完全相同但原始 token 数不足 80 的短样板不报。
        独有检出：若短样板门槛失效，本例两个完全相同的 ~50 token 函数会被误报。"""
        p, rep = self.report_for({'head_a.cc': SHORTY, 'head_b.cc': SHORTY})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.similar-functions', 'not_reported', 'short/R1')
        self.assertEqual(self.findings_for(rep, 'design.similar-functions'), [], '短样板零命中')

    def test_divergent_bodies_not_reported(self):
        """契约：长度相近但差异合计超过 12 个 token 的不算近似拷贝，不报。
        独有检出：本例 token 多重集与有序相似度都高于预选中位数，只有差异计数门槛
        能把它挡下；计数失效（如只比 Jaccard）即误报。"""
        p, rep = self.report_for({'readiness.cc': READY, 'diverged.cc': DIVERGED})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.similar-functions', 'not_reported', 'divergent/R1')
        self.assertEqual(self.findings_for(rep, 'design.similar-functions'), [], '大差异对零命中')

    def test_same_line_functions_do_not_share_a_source_window(self):
        """同一行多个函数没有列边界时，不能把整行误当成每个函数的函数体。"""
        p, rep = self.report_for({'one_line_a.cc': SAME_LINE_FUNCTIONS,
                                  'one_line_b.cc': SAME_LINE_FUNCTIONS})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.similar-functions', 'not_reported', 'same-line/R1')
        self.assertEqual(self.findings_for(rep, 'design.similar-functions'), [],
                         '同一行函数不得共享整行 token 窗口')

    def test_function_closing_line_is_not_shared_with_another_function(self):
        """函数闭括号同行追加函数时，两个窗口都应因边界歧义跳过。"""
        p, rep = self.report_for({'same_end_a.cc': SAME_END_LINE_FUNCTIONS,
                                  'same_end_b.cc': SAME_END_LINE_FUNCTIONS})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.similar-functions', 'not_reported', 'same-end-line/R1')
        self.assertEqual(self.findings_for(rep, 'design.similar-functions'), [],
                         '共享闭括号行的函数不得复用整行 token 窗口')

    def test_missing_backend_uncovered_and_sibling_check_unaffected(self):
        """契约：lizard 后端缺失必须 uncovered/NO_MEASUREMENT_BACKEND，退出码 2，
        其余检查结果不受影响（这里用不依赖 lizard 的 6.4 候选作对照）。
        独有检出：把后端缺失装成零命中时，status 会是 not_reported 且退出码是 0。"""
        files = {'note.h': '/* 数量。 */\nint limit{0};\n'}
        root = self.put_tree(files)
        empty = root / 'empty-backend'
        empty.mkdir()  # 存在但不含 lizard.py/lizard 包：配置合法、后端不可用
        extra = f'[design."design.similar-functions"]\nlizard_path = "{empty}"\n'
        self.put_design_config(rules=('design.similar-functions', 'design.comment-restates-code'),
                               extra=extra, root=root)
        keys = ('design.similar-functions', 'design.comment-restates-code')
        p, rep = self.design_report(ctx='backend/R1', keys=keys, root=root)
        self.assertEqual(p.returncode, 2, '覆盖缺口必须体现为退出码 2')
        self.review_status(rep, 'design.similar-functions', 'uncovered', 'backend/R1')
        self.expect_missing_code(rep, 'design.similar-functions', 'NO_MEASUREMENT_BACKEND', 'backend/R1')
        self.assertFalse(rep['coverage']['complete'], 'uncovered 时 complete 必须为 false')
        sib = self.key_check(rep, 'design.comment-restates-code', 'backend/R1')
        self.assertEqual(sib.get('status'), 'candidate', '不依赖 lizard 的检查照常出结果')
        self.assertEqual(len(self.findings_for(rep, 'design.comment-restates-code')), 1,
                         '对照检查的 finding 不因兄弟检查 uncovered 而丢失')


class ComplexityDelta(ReviewCase):
    """R2 design.complexity-delta：复用 tools/complexity 的测量与差量。"""

    def report_for(self, files, **kw):
        root = self.put_tree(files)
        self.put_design_config(rules=('design.complexity-delta',), extra=CFG_R2, root=root)
        return self.design_report(ctx='R2', keys=('design.complexity-delta',), root=root, **kw)

    def test_inventory_without_baseline(self):
        """契约：无基线时超阈函数标记 inventory、before=None，after/threshold 正确，
        metric 为超出的那一个；CCN 16+1=17 > 15，认知 16 <= 25、参数 2、nloc 远小于 100，
        因此恰好只有一条 cyclomatic_complexity finding。
        独有检出：inventory 被错标成 new/worsened 或 before 被编造时断言失败。"""
        p, rep = self.report_for({'bbt/hot.cc': hot_source('hot_loop', 16)})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.complexity-delta', 'candidate', 'inventory/R2')
        row = self.one_finding(rep, 'design.complexity-delta', 'inventory/R2')
        facts = row['facts']
        self.assertEqual(facts['metric'], 'cyclomatic_complexity')
        self.assertEqual(facts['comparison'], 'inventory', '无基线必须是存量而非新增/恶化')
        self.assertIsNone(facts['before'], '存量没有基线值')
        self.assertEqual(facts['after'], 17, '16 个顺序 if：CCN = 16 + 1')
        self.assertEqual(facts['threshold'], 15, '默认圈复杂度阈值 15')
        self.assertIsNone(facts['baseline'], '未传 --baseline 时事实保持 None')
        self.assertEqual(facts['measurement'], {'backend': 'lizard', 'version': '1.25.0'})
        self.assertEqual(row['file'], 'bbt/hot.cc')

    def test_calm_function_not_reported(self):
        """契约：未超阈函数不报，状态是 not_reported 而不是 uncovered。
        独有检出：把低复杂度误报（阈值错用 >= 或指标串行）时本例出现 finding；
        把正常测量误判成缺输入时 status 变 uncovered。"""
        calm = 'int calm(int value, int limit) {\n  int total = 0;\n' \
               '  if (value > limit) { total = value - limit; } else { total = limit - value; }\n' \
               '  return total;\n}\n'
        p, rep = self.report_for({'bbt/calm.cc': calm})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.complexity-delta', 'not_reported', 'calm/R2')
        self.assertEqual(self.findings_for(rep, 'design.complexity-delta'), [], '低复杂度零命中')
        self.assertFalse(rep['coverage']['missing_inputs'], '正常测量不产生缺输入')

    def test_r2_uses_its_own_backend_path(self):
        root = self.put_tree({'bbt/hot.cc': hot_source('hot_loop', 16)})
        empty = root / 'empty-backend'
        empty.mkdir()
        extra = (f'[design."design.similar-functions"]\nlizard_path = "{empty}"\n'
                 f'[design."design.complexity-delta"]\nlizard_path = "{LIZARD_SP}"\n')
        self.put_design_config(rules=('design.similar-functions', 'design.complexity-delta'),
                               extra=extra, root=root)
        p, rep = self.design_report(ctx='independent-backends/R2',
                                    keys=('design.similar-functions', 'design.complexity-delta'),
                                    root=root)
        self.assertEqual(p.returncode, 2, 'R1 的后端缺口应保留')
        self.review_status(rep, 'design.complexity-delta', 'candidate', 'independent-backends/R2')
        self.assertTrue(self.findings_for(rep, 'design.complexity-delta'),
                        'R2 应使用自己的可用后端继续测量')


class ComplexityDeltaBaseline(ReviewGitCase):
    """R2 带 --baseline：自有临时仓两提交，验证 new/worsened 与 before/after。"""

    def test_new_and_worsened_with_before_after(self):
        """契约：有基线时只有 new/worsened 上报并带 before/after/threshold。
        夹具：基线提交里 grown 已经超阈（CCN 20 > 15，避免越过阈值边界的语义歧义），
        当前提交恶化到 24 → worsened，before=20/after=24；fresh 是基线不存在的
        新函数（CCN 17 > 15）→ new，before=None。
        独有检出：before 丢失、worsened/new 互换、或未超阈函数混入都会破坏精确断言。"""
        put = lambda rel, text: self.put(rel, text, root=self.repo)
        put('bbt/grown.cc', hot_source('grown', 19))
        self.put_design_config(rules=('design.complexity-delta',), extra=CFG_R2, root=self.repo)
        self.git('add', '.')
        self.git('commit', '-qm', 'already hot baseline')
        put('bbt/grown.cc', hot_source('grown', 23))
        put('bbt/fresh.cc', hot_source('fresh_hot', 16))
        self.git('add', '.')
        self.git('commit', '-qm', 'grow and add')
        p, rep = self.design_report(ctx='baseline/R2', keys=('design.complexity-delta',),
                                    baseline='HEAD^')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.review_status(rep, 'design.complexity-delta', 'candidate', 'baseline/R2')
        rows = self.findings_for(rep, 'design.complexity-delta')
        by_unit = {r['facts']['unit'].split('(')[0]: r['facts'] for r in rows}
        self.assertEqual(set(by_unit), {'grown', 'fresh_hot'},
                         '两个超阈函数各只报超出的那一项指标')
        grown, fresh = by_unit['grown'], by_unit['fresh_hot']
        self.assertEqual(grown['comparison'], 'worsened', '基线已超阈后继续增长')
        self.assertEqual(grown['before'], 20)
        self.assertEqual(grown['after'], 24)
        self.assertEqual(grown['metric'], 'cyclomatic_complexity')
        self.assertEqual(grown['threshold'], 15)
        self.assertEqual(grown['baseline'], 'HEAD^')
        self.assertEqual(fresh['comparison'], 'new', '基线不存在的超阈函数')
        self.assertIsNone(fresh['before'])
        self.assertEqual(fresh['after'], 17)
        for facts in by_unit.values():
            self.assertEqual(facts['metric'], 'cyclomatic_complexity',
                             '认知复杂度保持不超阈：CCN 是唯一超出的指标')

    def test_renamed_function_matches_the_baseline(self):
        put = lambda rel, text: self.put(rel, text, root=self.repo)
        put('bbt/old.cc', hot_source('moved', 16))
        self.put_design_config(rules=('design.complexity-delta',), extra=CFG_R2, root=self.repo)
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline before move')
        self.git('mv', 'bbt/old.cc', 'bbt/new.cc')
        put('bbt/new.cc', hot_source('moved', 17))
        self.git('add', '.')
        self.git('commit', '-qm', 'move and grow')
        p, rep = self.design_report(ctx='renamed/R2', keys=('design.complexity-delta',),
                                    baseline='HEAD^')
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = self.findings_for(rep, 'design.complexity-delta')
        self.assertEqual(len(rows), 1, '移动并恶化的函数只报一条')
        facts = rows[0]['facts']
        self.assertEqual(rows[0]['file'], 'bbt/new.cc')
        self.assertEqual(facts['comparison'], 'worsened')
        self.assertEqual(facts['before'], 17)
        self.assertEqual(facts['after'], 18)


class ForwardingLayerTightened(ReviewCase):
    """2.3 收紧版：三方可定位才出候选，排除语义各自独立。"""

    def test_cross_tu_caller_delegate_target_in_facts(self):
        """契约：调用方+包装层+委托目标三者可定位时出候选；facts.callers 含 user.cc 的
        实际调用位置与调用方函数名，delegate_target 为 Impl，chain 逐方法给出 decl/impl。
        独有检出：跨 TU 键匹配（qualified record + 签名）失效时 callers 为空、候选消失。"""
        p, rep, _ = self.one('design.forwarding-layer', CROSS_TU)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.expect_status(rep, 'design.forwarding-layer', 'candidate', 'cross-tu/2.3')
        row = self.one_finding(rep, 'design.forwarding-layer', 'cross-tu/2.3')
        facts = row['facts']
        self.assertEqual(facts['delegate_target'], 'Impl', '委托目标应解析为 Impl')
        callers = facts['callers']
        self.assertTrue(callers, '必须存在可定位的实际调用方')
        for site in callers:
            self.assertEqual(site['path'], 'user.cc', '调用位置来自另一个编译单元')
            self.assertEqual(site['caller'], 'use_shell')
        self.assertIn(3, [site['line'] for site in callers], 'Sh::a() 的调用行')
        self.assertIn(4, [site['line'] for site in callers], 'Sh::b() 的调用行')
        self.assertEqual(len(facts['chain']), 2, 'a/b 两个转发方法都进链')
        for entry in facts['chain']:
            self.assertEqual(entry['impl'], entry['decl'], '同名直通')
            self.assertEqual(entry['delegate_target'], 'Impl')
            self.assertEqual(entry['delegate_location']['path'], 'shell.h')
            self.assertFalse(entry['params_changed'], '参数按序原样传递')
        self.assertEqual(facts['exclusions_checked'],
                         ['type_marker', 'public_interface', 'ownership', 'synchronization'],
                         '排除语义按固定四项声明')
        self.assertTrue(facts['t401_candidate'])

    def test_type_marker_dispatch_excluded(self):
        """契约：包装类被 std::is_base_of 等 type traits 用于分派选择时携带类型标记语义，不报。
        独有检出：type_marker 排除失效时 pick<Sh>() 成为调用方并产生候选。"""
        p, rep, _ = self.one('design.forwarding-layer', TYPE_MARKER)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '类型标记语义下的壳不报候选')

    def test_extra_behavior_before_forwarding_excluded(self):
        """契约：转发前先 require(tok) 之类附加行为不是单一调用直通，不报；
        同文件纯转发哨兵 Sh 仍报，证明扫描本身没有失效。
        独有检出：把多语句/附加调用误认为直通时 Gate 出现在命中里。"""
        p, rep, _ = self.one('design.forwarding-layer', EXTRA_BEHAVIOR)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = self.findings_for(rep, 'design.forwarding-layer')
        self.assertEqual([r['symbol'] for r in rows], ['Sh'], '只有纯直通哨兵被报')
        self.assertFalse(any(r['symbol'] == 'Gate' for r in rows), '带附加行为的转发不报')

    def test_shell_without_callers_not_reported(self):
        """契约：只有实现、没有可定位调用方的纯转发壳不报（不凭单个实现定罪）。
        独有检出：漏掉 callers 为空的前置条件时本例出候选。"""
        p, rep, _ = self.one('design.forwarding-layer', {'shell.h': IMPL_AND_SHELL})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '无调用方的壳零命中')

    def test_public_static_shell_not_reported(self):
        """契约：public/protected 方法默认属于公开接口，不能只凭转发形状定罪。
        独有检出：若访问级别没有进入排除证据，本例会把公共门面报成无收益层。"""
        files = {'public.h': '''struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
struct PublicShell {
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
''',
                 'user.cc': '#include "public.h"\nint use_public() { return PublicShell::a() + PublicShell::b(); }\n'}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '公共 static 接口默认不报')

    def test_return_type_adaptation_not_reported(self):
        """契约：包装返回类型与委托返回类型不同，隐式转换就是职责证据，不报。
        独有检出：只比较调用名称或剥掉隐式转换时会误报该私有壳。"""
        files = {'adapt.h': '''struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
class Adapted {
  friend int use_adapted();
  static long a() { return Impl::a(); }
  static long b() { return Impl::b(); }
};
''',
                 'user.cc': '#include "adapt.h"\nint use_adapted() { return static_cast<int>(Adapted::a() + Adapted::b()); }\n'}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '返回类型适配不报')

    def test_function_pointer_target_not_reported(self):
        files = {'pointer.h': '''struct Impl {
  static int (*a)();
  static int (*b)();
};
class Shell {
  friend int use_pointer();
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
''',
                 'user.cc': '#include "pointer.h"\nint use_pointer() { return Shell::a() + Shell::b(); }\n'}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '函数指针目标不可定位时不报')

    def test_added_arguments_not_reported(self):
        files = {'arguments.h': '''struct Impl {
  static int a(int value) { return value; }
  static int b(int value) { return value; }
};
class Shell {
  friend int use_arguments();
  static int a() { return Impl::a(4); }
  static int b() { return Impl::b(5); }
};
''',
                 'user.cc': '#include "arguments.h"\nint use_arguments() { return Shell::a() + Shell::b(); }\n'}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '无参包装层补入参数时不报')

    def test_default_arguments_are_not_treated_as_passthrough(self):
        files = {'default_args.h': '''struct Impl {
  static int a(int value = 4) { return value; }
  static int b(int value = 5) { return value; }
};
class Shell {
  friend int use_default_args();
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
''',
                 'user.cc': '#include "default_args.h"\nint use_default_args() { return Shell::a() + Shell::b(); }\n'}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '委托默认参数也属于适配行为')

    def test_trailing_return_adaptation_not_reported(self):
        files = {'trailing.h': '''struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
class Shell {
  friend int use_trailing();
  static auto a() -> long { return Impl::a(); }
  static auto b() -> long { return Impl::b(); }
};
''',
                 'user.cc': '#include "trailing.h"\nint use_trailing() { return static_cast<int>(Shell::a() + Shell::b()); }\n'}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '尾置返回类型适配不报')

    def test_access_comment_does_not_change_public_interface(self):
        files = {'comment_access.h': '''struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
class Shell {
public: // private: implementation note
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
''',
                 'user.cc': '#include "comment_access.h"\nint use_comment_access() { return Shell::a() + Shell::b(); }\n'}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '访问说明注释不应覆盖 AST 的 public')

    def test_namespace_callers_match_the_wrapper_declaration(self):
        files = {'namespace.h': '''namespace X {
struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
class Shell {
  friend int use_namespace();
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
}
''',
                 'user.cc': ('#include "namespace.h"\nnamespace X {\n'
                             'int use_namespace() { return Shell::a() + Shell::b(); }\n}\n')}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        row = self.one_finding(rep, 'design.forwarding-layer', 'namespace/2.3')
        self.assertTrue(any(site['path'] == 'user.cc' for site in row['facts']['callers']),
                        '命名空间内的调用方应与包装声明匹配')

    def test_custom_template_dispatch_excluded(self):
        files = {'domain.h': '''template <typename T> struct Domain {
  static constexpr bool value = false;
};
struct Impl {
  static int a() { return 1; }
  static int b() { return 2; }
};
class Shell {
  friend int use_domain();
  static int a() { return Impl::a(); }
  static int b() { return Impl::b(); }
};
template <> struct Domain<Shell> {
  static constexpr bool value = true;
};
''',
                 'user.cc': ('#include "domain.h"\nint use_domain() {\n'
                             '  return Domain<Shell>::value ? Shell::a() : Shell::b();\n}\n')}
        p, rep, _ = self.one('design.forwarding-layer', files)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.findings_for(rep, 'design.forwarding-layer'), [],
                         '自定义模板分派语义应排除转发层候选')


class MeasurementLoader(unittest.TestCase):
    """显式 lizard 环境不污染导入路径或沿用旧模块缓存。"""

    def test_explicit_backend_replaces_cache_and_restores_path(self):
        from design_measure import backend_context

        path = LIZARD_SP
        original_path = list(sys.path)
        cached = types.ModuleType('lizard')
        sys.modules['lizard'] = cached
        with backend_context(path) as backend:
            self.assertTrue(str(backend.__file__).startswith(path))
            self.assertIsNot(sys.modules['lizard'], cached, '显式后端加载期间应替换旧缓存')
        self.assertEqual(sys.path, original_path, '显式后端不得永久污染 sys.path')
        self.assertIs(sys.modules['lizard'], cached, '检查完成后应恢复旧 lizard 缓存')

    def test_repository_backend_path_is_not_executed(self):
        from design_measure import BackendMissing, load_backend

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            marker = path / 'imported'
            (path / 'lizard.py').write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
                encoding='utf-8')
            metadata = path / 'lizard-1.25.0.dist-info'
            metadata.mkdir()
            (metadata / 'METADATA').write_text('Version: 1.25.0\n', encoding='utf-8')
            with self.assertRaises(BackendMissing):
                load_backend(str(path))
            self.assertFalse(marker.exists(), '消费仓配置不得执行任意 Python 后端')

    def test_pythonpath_repository_root_is_not_a_trusted_backend(self):
        from design_measure import trusted_backend_path

        root = str(Path(__file__).resolve().parents[3])
        sys.path.insert(0, root)
        try:
            self.assertFalse(trusted_backend_path(root), 'PYTHONPATH 中的消费仓目录不得成为后端')
        finally:
            sys.path.remove(root)


if __name__ == '__main__':
    unittest.main()
