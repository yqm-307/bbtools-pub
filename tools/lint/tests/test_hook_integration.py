"""Hook-path integration: cpp rules run through git-hooks against the immutable
index (commit) or pushed objects (push), not the worktree.
Contract: tools/lint/README.md §退出码 and tools/git-hooks/README.md §配置兼容.
"""
import shutil
import unittest

from _support import GitCase, config_text


def lint_config(commit=(), push=(), scan=('T501',), rules_extra=''):
    return config_text(scan=scan, commit=commit, push=push, extra=rules_extra)


class CommitScopeTest(GitCase):
    """README §hook 的 C++ 候选规则: '扫描本次改动文件的完整内容…不读未暂存源码，不扫描无改动文件'."""

    def setUp(self):
        super().setUp()
        self.put('unchanged.h', 'int kRpcV2Old;\n', root=self.repo)
        self.put('changed.h', 'int clean;\n', root=self.repo)
        self.commit_all('baseline')
        self.base_commit = self.git('rev-parse', 'HEAD').stdout.strip()
        self.put('.config/lint.toml', lint_config(commit=('T501',)), root=self.repo)
        self.git('add', '.config/lint.toml')

    def test_only_changed_files_scanned(self):
        self.put('changed.h', 'int kRpcV2New;\n', root=self.repo)
        self.git('add', 'changed.h')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('changed.h', p.stderr)
        self.assertIn('kRpcV2New', p.stderr)
        self.assertNotIn('unchanged.h', p.stderr)
        self.assertNotIn('kRpcV2Old', p.stderr)

    def test_staged_content_not_worktree(self):
        """The hook reads the frozen index, not the unstaged worktree file."""
        self.put('changed.h', 'int kRpcV2New;\n', root=self.repo)
        self.git('add', 'changed.h')
        # Now make the worktree dirty with a second V2 name; only the staged
        # blob may be examined.
        self.put('changed.h', 'int kRpcV2New;\nint kDirtyV2;\n', root=self.repo)
        p = self.commit_hook()
        self.assertEqual(p.returncode, 1)
        self.assertIn('kRpcV2New', p.stderr)
        self.assertNotIn('kDirtyV2', p.stderr)

    def test_clean_staged_content_passes(self):
        self.put('changed.h', 'int still_clean;\n', root=self.repo)
        self.git('add', 'changed.h')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS T501', p.stderr)


class LevelTest(GitCase):
    """README §退出码: 'level=block exit 1、level=warn exit 0 且输出 WARN 不输出 PASS'."""

    def setUp(self):
        super().setUp()
        self.put('a.h', 'int kRpcV2New;\n', root=self.repo)
        self.git('add', 'a.h')

    def test_block_level_exit_1(self):
        self.put('.config/lint.toml',
                 lint_config(commit=('T501',), rules_extra='[rules.T501]\nlevel = "block"\n'),
                 root=self.repo)
        self.git('add', '.config/lint.toml')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL T501', p.stderr)
        self.assertNotIn('WARN T501', p.stderr)
        self.assertNotIn('PASS T501', p.stderr)

    def test_warn_level_exit_0_warns_not_passes(self):
        self.put('.config/lint.toml',
                 lint_config(commit=('T501',), rules_extra='[rules.T501]\nlevel = "warn"\n'),
                 root=self.repo)
        self.git('add', '.config/lint.toml')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('WARN T501', p.stderr)
        self.assertNotIn('PASS T501', p.stderr)
        self.assertNotIn('FAIL T501', p.stderr)


class PushScopeTest(GitCase):
    def setUp(self):
        super().setUp()
        self.put('.config/lint.toml', lint_config(push=('T501',)), root=self.repo)
        self.put('old.h', 'int kRpcV2Old;\n', root=self.repo)
        self.commit_all('baseline')
        self.base_commit = self.git('rev-parse', 'HEAD').stdout.strip()

    def test_push_scans_changed_files(self):
        self.put('new.h', 'int kRpcV2New;\n', root=self.repo)
        self.commit_all('add new')
        tip = self.git('rev-parse', 'HEAD').stdout.strip()
        p = self.push_hook(tip)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('new.h', p.stderr)
        self.assertNotIn('old.h', p.stderr)


class LegacyConfigTest(GitCase):
    """tools/git-hooks/README §配置兼容: schema 1 config runs unchanged with
    the original default rule order."""

    def test_schema1_default_commit_rules(self):
        self.put('x.cc', 'int x() { return 0; }  \n', root=self.repo)  # trailing ws
        self.git('add', 'x.cc')
        # No config file at all: legacy defaults apply.
        p = self.commit_hook()
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL whitespace', p.stderr)

    def test_schema1_file_unmodified_still_works(self):
        legacy = ('schema_version = 1\n'
                  '[commit]\nrules = ["whitespace"]\n'
                  '[format]\nbinary = "clang-format"\n')
        self.put('.config/bbt-git-hooks.toml', legacy, root=self.repo)
        self.git('add', '.config/bbt-git-hooks.toml')
        self.put('x.cc', 'int x() { return 0; }\n', root=self.repo)
        self.git('add', 'x.cc')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS whitespace', p.stderr)
        self.assertEqual((self.repo / '.config/bbt-git-hooks.toml').read_text(), legacy)

    def test_both_config_files_error(self):
        self.put('.config/lint.toml', lint_config(), root=self.repo)
        self.put('.config/bbt-git-hooks.toml', 'schema_version = 1\n', root=self.repo)
        self.commit_all('configs')
        self.put('x.cc', 'int x;\n', root=self.repo)
        self.git('add', 'x.cc')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn('keep one configuration', p.stderr)


class CppRuleInHookContextTest(GitCase):
    """A cpp rule finding renders through the standard report contract."""

    def test_report_shape_on_block(self):
        self.put('.config/lint.toml', lint_config(commit=('T501',)), root=self.repo)
        self.git('add', '.config/lint.toml')
        self.put('a.h', 'int kRpcV2Timeout;\n', root=self.repo)
        self.git('add', 'a.h')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 1)
        self.assertIn('FAIL T501', p.stderr)
        self.assertIn('E-T501', p.stderr)
        self.assertIn('a.h:1', p.stderr)
        self.assertIn('kRpcV2Timeout', p.stderr)


class ExtensionTest(GitCase):
    """README §规则协议与扩展: copying _template + adding one config line is
    enough for both scan and hook — done entirely inside the copied tools tree."""

    def make_rule(self, name='demo'):
        rule = self.tools / 'lint/rules' / name
        shutil.copytree(self.tools / 'lint/rules/_template', rule)
        meta = (rule / 'meta.toml').read_text().replace('id = "example"', f'id = "{name}"')
        (rule / 'meta.toml').write_text(meta)
        (rule / 'main.py').write_text(
            'def check(source, options):\n'
            '    for i, line in enumerate(source.code.splitlines(), 1):\n'
            '        if "DEMO_MARKER" in line:\n'
            '            yield i, "demo marker candidate", "DEMO_MARKER"\n')

    def test_template_rule_runs_in_scan(self):
        self.make_rule()
        self.put('x.h', 'int DEMO_MARKER;\n')
        self.lint_config(config_text(scan=('demo',)))
        p = self.scan('--format', 'json')
        self.assertEqual(p.returncode, 0, p.stderr)
        import json
        report = json.loads(p.stdout)
        self.assertEqual(report['counts'], {'demo': 1})

    def test_template_rule_runs_in_commit_hook(self):
        self.make_rule()
        self.put('.config/lint.toml',
                 lint_config(commit=('demo',), scan=('demo',)), root=self.repo)
        self.git('add', '.config/lint.toml')
        self.put('x.h', 'int DEMO_MARKER;\n', root=self.repo)
        self.git('add', 'x.h')
        p = self.commit_hook()
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL demo', p.stderr)
        self.assertIn('demo marker candidate', p.stderr)


if __name__ == '__main__':
    unittest.main()
