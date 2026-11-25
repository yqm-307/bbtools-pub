"""统一设计入口的 CLI 契约（T2 冻结，来源：映射 §4.1–§4.5）。

T3 未实现 ``--design`` 前，本模块除「默认模式不变」外全部红测，
消息前缀 ``[DESIGN-ENTRY-MISSING]``；这是预期红，不是夹具缺陷。
"""
import re
import unittest

from _support import LintCase, config_text
from design_fixtures import DesignCase, DesignGitCase


BAD_64 = {'a.h': '/* 数量。 */\nint limit{0};\n'}          # 6.4 复用既有 T202 形状
BAD_61 = {'dup.cc': 'int f(int x) { if (x > 0) { x = 1; } else { x = 1; } return x; }\n'}
BAD_21_FILES = {'app/client.cc': '#include "runtime/internal/poller.h"\nint main() { return poll(); }\n',
                'runtime/internal/poller.h': 'int poll();\n'}
CFG_21 = ('[design."design.private-header-boundary"]\n'
          'private = ["runtime/internal/*.h"]\n'
          'allow = ["runtime/internal/test_support.h"]\n'
          '[design."design.private-header-boundary".targets]\n'
          '"app/*" = "app"\n'
          '"runtime/*" = "runtime"\n')


class DesignReportShape(DesignCase):
    def test_top_level_contract(self):
        """§4.3：schema/tool/invocation/checks/findings/coverage/counts。"""
        root = self.put_tree(BAD_64)
        cfg = self.put_design_config(rules=('6.4',), root=root)
        p, rep = self.design_report(ctx='shape', keys=('6.4',), root=root)
        self.assertEqual(rep['schema_version'], 2, '设计报告 schema_version 固定 2')
        self.assertEqual(rep['tool']['name'], 'bbtools-lint', '§4.3 tool.name')
        self.assertTrue(rep['tool']['version'], '§4.3 tool.version 非空')
        inv = rep['invocation']
        self.assertEqual(inv['checks'], ['design.comment-restates-code'], '§4.3 invocation.checks')
        self.assertEqual(inv['format'], 'json', '§4.3 invocation.format')
        self.assertIsNone(inv['baseline'], '未传 --baseline 时为 null')
        self.assertEqual(str(root), inv['root'], 'invocation.root 回显输入')
        ck = self.key_check(rep, '6.4', 'shape')
        self.assertEqual(ck['status'], 'candidate', '6.4 坏例 → candidate（§1 线索）')
        self.assertIsNone(ck.get('reason'), 'candidate 非缺输入，reason 为 null')
        row = self.one_finding(rep, '6.4', 'shape')
        self.expect_facts(row, '6.4', 'shape')
        self.assertEqual(row['file'], 'a.h', 'file 相对 --root')
        self.assertIn('design.comment-restates-code', rep['counts']['by_key'], 'counts.by_key 只汇总实际运行键')
        self.assertIn('candidate', rep['counts']['by_status'], 'counts.by_status')
        cov = rep['coverage']
        self.assertEqual(cov['mode'], 'design', '§4.3 coverage.mode')
        for name in ('complete', 'files_scanned', 'missing_inputs',
                     'manual_pending', 'disabled'):
            self.assertIn(name, cov, f'§4.3 coverage.{name}')

    def test_findings_sorted(self):
        """§4.3：findings 按 (file, line, key, symbol, fingerprint) 排序。"""
        files = {'z.cc': BAD_61['dup.cc'], 'a.cc': BAD_61['dup.cc']}
        root = self.put_tree(files)
        self.put_design_config(rules=('6.1',), root=root)
        p, rep = self.design_report(ctx='sorted', keys=('6.1',), root=root)
        rows = self.findings_for(rep, '6.1')
        self.assertEqual(len(rows), 2, '两个坏例各一条')
        self.assertEqual([r['file'] for r in rows], ['a.cc', 'z.cc'],
                         '按 file 升序（§4.3）')

    def test_zero_hit_keys_still_listed(self):
        """§4.5 全局：零命中键必须出现在 checks[]，不能从告警数倒推覆盖。"""
        root = self.put_tree({'clean.cc': 'int ok() { return 1; }\n'})
        self.put_design_config(rules=('6.1', '6.4'), root=root)
        p, rep = self.design_report(ctx='zero-hit', keys=('6.1', '6.4'), root=root)
        self.assertEqual(p.returncode, 0, '§4.4：全部实际运行且无 uncovered → 0')
        self.assertEqual(sorted(c['key'] for c in rep['checks']),
                         ['design.comment-restates-code', 'design.identical-branch-tokens'])
        for key in ('6.1', '6.4'):
            self.expect_status(rep, key, 'not_reported', f'zero-hit/{key}')
        self.assertEqual(self.findings_for(rep, '6.1'), [], '零命中无 finding')
        self.assertTrue(rep['coverage']['complete'],
                        '所选范围干净且无 uncovered/manual/disabled → complete')


class DesignScoping(DesignCase):
    def test_check_key_only_lists_selected(self):
        """§4.1/§4.3：显式 --check 仅列所选键。"""
        files = {**BAD_64, **BAD_21_FILES}
        root = self.put_tree(files)
        self.put_design_config(rules=('2.1', '6.4'), extra=CFG_21, root=root)
        p, rep = self.design_report(ctx='scoping', keys=('6.4',), root=root)
        self.assertEqual([c['key'] for c in rep['checks']], ['design.comment-restates-code'],
                         '显式 --check 只列所选键')
        self.assertEqual({f['key'] for f in rep['findings']}, {'design.comment-restates-code'},
                         'findings 只含所选键')

    def test_disabling_one_leaves_others_unchanged(self):
        """§4.5 全局 1：从 [design].rules 移除一项，其余键结果不变。

        全组运行（不传 --check）要列出未选键为 disabled；显式 --check 只列所选键。
        """
        files = {**BAD_64, **BAD_61}
        root = self.put_tree(files)
        self.put_design_config(rules=('6.1', '6.4'), root=root)
        p_a, rep_a = self.design_report(ctx='full-both', root=root)
        self.assertEqual(p_a.returncode, 0)
        self.expect_status(rep_a, '6.1', 'candidate', 'full-both/6.1')
        row64_a = self.key_check(rep_a, '6.4', 'full-both/6.4')
        findings_a = self.findings_for(rep_a, '6.4')

        self.put_design_config(rules=('6.4',), root=root)
        p_b, rep_b = self.design_report(ctx='full-one', root=root)
        self.assertEqual(p_b.returncode, 0)
        removed = [c for c in rep_b['checks'] if c['key'] == 'design.identical-branch-tokens']
        self.assertTrue(removed, '全组运行保留未选键（§0.4），不得静默消失')
        self.assertEqual(removed[0]['status'], 'disabled', '未选键显式 disabled（§0.4）')
        self.assertIs(removed[0]['enabled'], False, '未选键 enabled=false')
        self.assertEqual(self.key_check(rep_b, '6.4', 'full-one/6.4'), row64_a,
                         '移除 6.1 后 6.4 checks[] 不变')
        self.assertEqual(self.findings_for(rep_b, '6.4'), findings_a, '移除 6.1 后 6.4 findings 不变')

        p_c, rep_c = self.design_report(ctx='explicit-one', keys=('6.4',), root=root)
        self.assertEqual(p_c.returncode, 0)
        self.assertEqual([c['key'] for c in rep_c['checks']], ['design.comment-restates-code'],
                         '显式 --check 只列所选键，不列未选 disabled')
        self.assertEqual(self.key_check(rep_c, '6.4', 'explicit-one/6.4'), row64_a,
                         '显式选择下 6.4 checks[] 仍不变')
        self.assertEqual(self.findings_for(rep_c, '6.4'), findings_a, '显式选择下 6.4 findings 不变')


class DesignExitCodes(DesignCase):
    def test_config_error_exit2_no_report(self):
        """§4.2/§4.4：manual 与 rules 重叠 → 配置错误 exit 2，无报告。"""
        root = self.put_tree(BAD_64)
        self.put_design_config(rules=('6.4',), manual=('6.4',), root=root)
        p, rep = self.design_report(ctx='overlap', keys=('6.4',), root=root)
        self.assertIsNone(rep, '配置错误不产出报告')
        self.assertEqual(p.returncode, 2, '§4.4 配置错误 → 2')
        self.assertTrue(p.stderr.strip(), '配置错误须有 stderr 说明')

    def test_unknown_check_key_exit2(self):
        """§4.1/§4.4：未知 --check 键 → exit 2。"""
        root = self.put_tree(BAD_64)
        self.put_design_config(rules=('6.4',), root=root)
        p, rep = self.design_report(ctx='unknown-key', keys=('9.9',), root=root)
        self.assertIsNone(rep, '未知键是配置错误，无报告')
        self.assertEqual(p.returncode, 2, '§4.4 未知 --check → 2')
        self.assertTrue(p.stderr.strip(), 'stderr 说明未知键')

    def test_unknown_design_config_key_exit2(self):
        """§4.2：[design] 段未知键 → exit 2，不做静默合并。"""
        root = self.put_tree(BAD_64)
        self.put_design_config(rules=('6.4',), extra='unknown_extra = "x"\n', root=root)
        p, rep = self.design_report(ctx='unknown-cfg', keys=('6.4',), root=root)
        self.assertIsNone(rep, '未知配置键不产出报告')
        self.assertEqual(p.returncode, 2, '§4.2/§4.4 → 2')

    def test_uncovered_selected_exit2_with_report(self):
        """§4.3/§4.4：被选中的机械检查 uncovered → exit 2 且仍有完整报告。"""
        root = self.put_tree(BAD_21_FILES)
        self.put_design_config(rules=('2.1',), root=root)  # 无 2.1 边界声明输入
        p, rep = self.design_report(ctx='uncovered', keys=('2.1',), root=root)
        self.assertIsNotNone(rep, 'uncovered 仍产出报告（§4.3 示例含 uncovered）')
        self.assertEqual(p.returncode, 2, '§4.4 被选中检查 uncovered → 2')
        self.expect_status(rep, '2.1', 'uncovered', 'uncovered/2.1')
        self.expect_missing_code(rep, '2.1', 'NO_BOUNDARY_DECL', 'uncovered/2.1')
        self.assertFalse(rep['coverage']['complete'], 'uncovered 绝不记干净（§0.4）')

    def test_manual_pending_exit0_incomplete(self):
        """§4.4：manual_pending 不强制 exit 2，但必须 complete=false。"""
        root = self.put_tree({'hops.cc':
                              'int step3() { return 42; }\n'
                              'int step2() { return step3(); }\n'
                              'int step1() { return step2(); }\n'
                              'int entry() { return step1(); }\n'})
        self.put_design_config(manual=('6.3',), root=root)
        p, rep = self.design_report(ctx='manual', keys=('6.3',), root=root)
        self.assertEqual(p.returncode, 0, 'manual_pending 不强制 exit 2（§4.4）')
        self.expect_status(rep, '6.3', 'manual_pending', 'manual/6.3')
        self.expect_manual_pending(rep, '6.3', 'manual/6.3')

    def test_text_format_design_lines(self):
        """§4.1：文本行 file:line key STATUS symbol message。"""
        root = self.put_tree(BAD_64)
        self.put_design_config(rules=('6.4',), root=root)
        _, rep = self.design_report(ctx='text-shape', keys=('6.4',), fmt='json', root=root)
        self.assertIsNotNone(rep, '先确认入口产出 JSON 报告，再冻结文本行形状')
        p = self.design_run(keys=('6.4',), fmt='text', root=root)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = [line for line in p.stdout.splitlines() if line.strip()]
        self.assertTrue(rows, 'text 输出非空')
        match = re.match(r'^(\S+):(\d+) (design\.comment-restates-code) (\w+) (\S+) (.+)$', rows[0])
        self.assertIsNotNone(match, f'§4.1 文本行五段式，得 {rows[0]!r}')
        self.assertEqual(match.group(4).lower(), 'candidate', '状态与 JSON 一致')


class DesignDeterminism(DesignCase):
    def test_repeat_run_bytes_identical(self):
        """§4.5 全局 2：同一输入重复运行，输出字节一致。"""
        root = self.put_tree(BAD_64)
        self.put_design_config(rules=('6.4',), root=root)
        _, rep1 = self.design_report(ctx='determinism-first', keys=('6.4',), root=root)
        self.assertIsNotNone(rep1, '确定性断言只在入口产出报告后才有意义')
        p1 = self.design_run(keys=('6.4',), root=root)
        p2 = self.design_run(keys=('6.4',), root=root)
        self.assertEqual(p1.returncode, p2.returncode)
        self.assertEqual(p1.stdout, p2.stdout, '§4.3 确定性：findings/checks/coverage 字节一致')


class BaselineRequired(DesignGitCase):
    def test_history_key_without_baseline_uncovered(self):
        """§4.1/§4.4：历史项被选中但未给 --baseline → uncovered/NO_BASELINE，exit 2。"""
        self.put_repo_config(rules=('5.1',), extra=(
            '[[retired]]\npath = "src/**"\nsymbols = ["old_api"]\n'))
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        p, rep = self.design_report(ctx='no-baseline', keys=('5.1',))
        self.assertEqual(p.returncode, 2, '§4.4 历史项缺 --baseline → 2')
        self.assertIsNotNone(rep, '§4.1 uncovered/NO_BASELINE 随报告给出')
        self.expect_status(rep, '5.1', 'uncovered', 'no-baseline/5.1')
        self.expect_missing_code(rep, '5.1', 'NO_BASELINE', 'no-baseline/5.1')


class DefaultModeUnchanged(LintCase):
    """§4.1：不加 --design 时现有行为、规则集、输出与退出码不变。"""

    def test_lexical_report_untouched(self):
        self.put('a.h', 'struct Big {\npublic:\n' + '\n'.join(f'  int f{i};' for i in range(11)) + '\n};\n')
        self.lint_config(config_text(scan=('T101',)))
        p = self.run_cmd(__import__('sys').executable, '-I',
                         str(self.tools / 'lint/lint.py'),
                         '--root', str(self.root), '--format', 'json')
        self.assertEqual(p.returncode, 0, p.stderr)
        rep = __import__('json').loads(p.stdout)
        self.assertEqual(rep['schema_version'], 1, '现有词法 schema 不变')
        self.assertIn('lexical_candidates_not_semantic_validation',
                      rep['coverage']['mode'], '词法覆盖说明不变')
        self.assertNotIn('checks', rep, '默认模式不含设计段')
        for row in rep['findings']:
            self.assertIn('rule', row, '词法 finding 用 rule 键')
            self.assertNotIn('key', row, '默认模式不注入 key')


if __name__ == '__main__':
    unittest.main()
