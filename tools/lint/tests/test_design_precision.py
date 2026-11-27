"""编译数据库逐 TU 覆盖契约（来源：design-checks.md §4.3 与 lint-design-corpus
实跑 raw-before.json 的覆盖证据：CMake 命令行被整体拒绝时 281 个文件 0 AST）。

按 §4.3 冻结：语义受控选项逐 TU 接受；未知/不受支持选项与同一文件多配置冲突
只让对应 TU 进 uncovered/partial，不拖垮其他合法 TU；命令行从不执行，诊断/输出
选项不产生文件副作用。6.2/6.4 的语料误报正反例见 test_design_cat6.py。
"""
import json
import unittest

from design_fixtures import DesignCase


# 1.2 依赖 AST，可直观证明逐 TU 覆盖。
CDB_SRC = {
    'good.cc': 'void bump(int count, int limit) { (void)count; (void)limit; }\n',
    'another.cc': 'void pair_tag(long size, long quota) { (void)size; (void)quota; }\n',
    'bad.cc': 'void join_parts(unsigned lhs, unsigned rhs) { (void)lhs; (void)rhs; }\n',
}
CMAKE_TAIL = (' -fPIC -Wall -Werror -O3 -g -fno-rtti'
              ' -DBBT_COROUTINE_STACK_TESTING -DBOOST_CONTEXT_NO_LIB')


def cmake_entry(root, file, tail=CMAKE_TAIL, **kw):
    entry = {'directory': str(root), 'file': file,
             'command': f'/usr/bin/c++ -I{root}{tail} -c -o {file}.o {file}'}
    entry.update(kw)
    return entry


def put_cdb(case, root, entries):
    case.put('build-vscode/compile_commands.json', json.dumps(entries, indent=1), root=root)


class CdbCoverageContract(DesignCase):
    """CDB 安全路径：真实 CMake 风格命令行逐 TU 受控接受，坏项不拖垮整批。"""

    def missing_details(self, rep, key='1.2'):
        key = self.canonical_key(key)
        return '; '.join(m.get('detail', '') for m in rep['coverage']['missing_inputs']
                         if m.get('key') == key)

    def test_cmake_style_cdb_accepted_per_tu(self):
        """真实 CMake 命令行（-fPIC/-O3/-g/-Wall/-o，arguments 形式）→ TU 全部解析、
        不判干净：发现与覆盖以 TU 计。"""
        root = self.put_tree(CDB_SRC)
        entries = [cmake_entry(root, 'good.cc'),
                   cmake_entry(root, 'another.cc', tail=' -fPIC -O0 -g -DBOOST_CONTEXT_DYN_LINK',
                               arguments=['/usr/bin/c++', '-I', str(root), '-fPIC', '-O0', '-g',
                                          '-DBOOST_CONTEXT_DYN_LINK', '-c', '-o', 'another.cc.o',
                                          'another.cc'])]
        put_cdb(self, root, entries)
        self.put_design_config(rules=('1.2',), cdb=True, root=root)
        p, rep = self.design_report(ctx='cmake-cdb', keys=('1.2',), root=root)
        self.assertIsNotNone(rep, 'cmake-cdb: 报告必须产出')
        self.assertEqual(p.returncode, 0, '受控选项不构成 uncovered')
        self.assertIn('good.cc', rep['coverage']['tus'], 'command 形式 TU 实际解析')
        self.assertIn('another.cc', rep['coverage']['tus'], 'arguments 形式 TU 实际解析')
        self.assertNotIn('bad.cc', rep['coverage']['tus'], '未进 CDB 的文件不得装作已解析')
        rows = self.findings_for(rep, '1.2')
        self.assertTrue(any(r['file'] == 'good.cc' for r in rows), 'good.cc 相邻同型对仍出候选')
        self.assertTrue(any(r['file'] == 'another.cc' for r in rows), 'another.cc 相邻同型对仍出候选')
        self.assertFalse(any(r['file'] == 'bad.cc' for r in rows), '未覆盖 TU 不产生候选')

    def test_unsupported_option_marks_only_that_tu_uncovered(self):
        """未知/不受支持选项（-march=native）只标对应 TU uncovered；
        合法 TU 的解析与发现不被拖垮。"""
        root = self.put_tree(CDB_SRC)
        entries = [cmake_entry(root, 'good.cc'),
                   cmake_entry(root, 'bad.cc', tail=' -march=native -fPIC')]
        put_cdb(self, root, entries)
        self.put_design_config(rules=('1.2',), cdb=True, root=root)
        p, rep = self.design_report(ctx='unsupported-cdb', keys=('1.2',), root=root)
        self.assertIsNotNone(rep, 'unsupported-cdb: 报告必须产出')
        self.assertEqual(p.returncode, 2, '存在 uncovered → exit 2')
        self.expect_status(rep, '1.2', 'uncovered', 'unsupported-cdb')
        details = self.missing_details(rep)
        self.assertIn('bad.cc', details, 'uncovered 详情点名坏 TU')
        self.assertNotIn('good.cc: ', details, '合法 TU 不得被坏 TU 的覆盖错误拖垮')
        self.assertIn('good.cc', rep['coverage']['tus'], '合法 TU 仍实际解析')
        self.assertIn('bad.cc', rep['coverage']['partial'], '坏 TU 进 partial，不得装作干净')
        rows = self.findings_for(rep, '1.2')
        self.assertTrue(any(r['file'] == 'good.cc' for r in rows), '合法 TU 的发现不受影响')
        self.assertFalse(any(r['file'] == 'bad.cc' for r in rows), '未覆盖 TU 不得产生候选')

    def test_conflicting_configs_mark_only_that_tu_uncovered(self):
        """同一文件多配置冲突（-DA=1 与 -DA=2）只标该 TU uncovered；其他 TU 不受影响。"""
        root = self.put_tree(CDB_SRC)
        entries = [cmake_entry(root, 'good.cc'),
                   cmake_entry(root, 'bad.cc', tail=' -DA=1 -fPIC'),
                   cmake_entry(root, 'bad.cc', tail=' -DA=2 -fPIC')]
        put_cdb(self, root, entries)
        self.put_design_config(rules=('1.2',), cdb=True, root=root)
        p, rep = self.design_report(ctx='conflict-cdb', keys=('1.2',), root=root)
        self.assertIsNotNone(rep, 'conflict-cdb: 报告必须产出')
        self.assertEqual(p.returncode, 2, '存在 uncovered → exit 2')
        self.expect_status(rep, '1.2', 'uncovered', 'conflict-cdb')
        details = self.missing_details(rep)
        self.assertIn('bad.cc', details, 'uncovered 详情点名冲突 TU')
        self.assertNotIn('good.cc: ', details, '合法 TU 不得被冲突拖垮')
        self.assertIn('good.cc', rep['coverage']['tus'], '合法 TU 仍实际解析')
        self.assertIn('bad.cc', rep['coverage']['partial'], '冲突 TU 进 partial，不得装作干净')

    def test_compile_output_option_never_writes(self):
        """诊断/编译输出参数不执行：-o 要么随坏 TU 进 uncovered，要么不改变语义；
        任何情况下不得产生输出文件副作用。"""
        root = self.put_tree(CDB_SRC)
        side_effect = root / 'injected.o'
        entries = [cmake_entry(root, 'good.cc'),
                   cmake_entry(root, 'bad.cc', tail=' -fPIC -o injected.o')]
        put_cdb(self, root, entries)
        self.put_design_config(rules=('1.2',), cdb=True, root=root)
        p, rep = self.design_report(ctx='output-cdb', keys=('1.2',), root=root)
        self.assertIsNotNone(rep, 'output-cdb: 报告必须产出')
        self.assertFalse(side_effect.exists(), 'CDB 是数据不是命令：-o 不得产生输出文件')
        if 'bad.cc' in rep['coverage']['tus']:
            self.assertNotIn('bad.cc', rep['coverage']['partial'], '受控接受的 TU 不得误标 partial')
        else:
            self.assertIn('bad.cc', rep['coverage']['partial'], '不支持的 -o 只让坏 TU 进 partial')
            self.assertIn('bad.cc', self.missing_details(rep), 'uncovered 详情点名坏 TU')
            self.assertEqual(p.returncode, 2, '存在 uncovered → exit 2')
        self.assertIn('good.cc', rep['coverage']['tus'], '合法 TU 仍实际解析')

    def test_preprocessor_forwarding_preserves_macro_semantics(self):
        """-Wp,-D... 被安全还原为宏定义，不能静默分析错误的条件分支。"""
        files = {'conditional.cc': ('#ifdef SELECT\n'
                                    'int selected(int left, int right) { return left + right; }\n'
                                    '#else\n'
                                    'int selected(int left, int right) { return left + ; }\n'
                                    '#endif\n')}
        root = self.put_tree(files)
        entries = [cmake_entry(root, 'conditional.cc', tail=' -Wp,-DSELECT=1 -fPIC')]
        put_cdb(self, root, entries)
        self.put_design_config(rules=('1.2',), cdb=True, root=root)
        p, rep = self.design_report(ctx='preprocessor-forwarding-cdb', keys=('1.2',), root=root)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('conditional.cc', rep['coverage']['tus'], '安全的预处理转发选项保留 TU 覆盖')


if __name__ == '__main__':
    unittest.main()
