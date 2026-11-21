"""Real Git regression for the optional directory layout gates.

new-root and third-party-layout are off unless listed in commit.rules or
push.rules; when enabled they compare the base and target trees only. Commit
gates therefore see the frozen index tree and push gates the actually pushed
objects. Every case runs a real git commit or a push to an owned local bare
remote and accepts the outcome by exit code, hook report and remote refs.
Nothing here touches the real checkout's index or a real remote.
"""
import os
import unittest

from _support import GitCase

CONFIG_ROOTS = ('.config', 'src', 'third-party')
CONFIG_GITLINKS = ('third-party/fmt',)
# Opaque gitlink pointers; the referenced commits never exist locally or remotely.
FMT_V1 = '1234567890abcdef1234567890abcdef12345678'
FMT_V2 = 'fedcba0987654321fedcba0987654321fedcba09'


def layout_toml(*, layout=True, commit=(), push=()):
    """schema 2 config with [layout] before the stage tables; layout=False omits [layout]."""
    lines = ['schema_version = 2', 'timeout_seconds = 60']
    if layout:
        lines += [
            '[layout]',
            'allowed_roots = [' + ', '.join(f'"{r}"' for r in CONFIG_ROOTS) + ']',
            'allowed_gitlinks = [' + ', '.join(f'"{g}"' for g in CONFIG_GITLINKS) + ']',
            '',
        ]
    for section, rules in (('scan', ('T501',)), ('commit', commit), ('push', push)):
        lines.append(f'[{section}]')
        lines.append('rules = [' + ', '.join(f'"{r}"' for r in rules) + ']')
        lines.append('')
    return '\n'.join(lines)


class GateCase(GitCase):
    """Owned repo with hooks wired through core.hooksPath (real git commit/push)."""

    def setUp(self):
        super().setUp()
        self.git('config', 'core.hooksPath', str(self.tools / 'git-hooks' / 'hooks'))

    def git(self, *args, ok=True):
        p = self.run_cmd('git', *args, cwd=self.repo)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def commit(self, message='change', ok=True):
        return self.git('commit', '-qm', message, ok=ok)

    def push(self, refspec, remote='origin', ok=True):
        return self.git('push', remote, refspec, ok=ok)

    def add_config(self, text):
        self.put('.config/lint.toml', text, root=self.repo)
        self.git('add', '.config/lint.toml')

    def head(self):
        return self.git('rev-parse', 'HEAD').stdout.strip()

    def remote_ref(self, remote, ref):
        return self.git('--git-dir', str(remote), 'rev-parse',
                        '--verify', '--quiet', ref, ok=False)

    def stage_gitlink(self, path, oid):
        self.git('update-index', '--add', '--cacheinfo', f'160000,{oid},{path}')

    def put_bytes(self, rel, data=b'legacy\n'):
        """Create a repo file by exact byte name; str fixtures cannot carry undecodable names."""
        with open(os.path.join(os.fsencode(self.repo), rel), 'wb') as fh:
            fh.write(data)


class LayoutCommitGate(GateCase):
    """Commit stage with both rules selected; two cases re-select one rule at a time.

    An existing src/ root is seeded before the layout config lands, so the
    seed commit runs with no layout rule selected.
    """

    def setUp(self):
        super().setUp()
        self.put('src/existing.h', 'int kept;\n', root=self.repo)
        self.git('add', 'src/existing.h')
        self.git('commit', '-qm', 'seed src')  # still unhooked: core.hooksPath comes next
        self.add_config(layout_toml(commit=('new-root', 'third-party-layout')))
        self.commit('config')
        self.head_before = self.head()

    def test_unknown_new_root_blocks_commit(self):
        self.put('vendor/x.txt', 'x\n', root=self.repo)
        self.git('add', 'vendor/x.txt')
        p = self.commit(ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL new-root', p.stderr)
        self.assertIn('E-NEW-ROOT', p.stderr)
        self.assertIn('vendor/', p.stderr)
        self.assertEqual(self.head(), self.head_before)  # nothing landed

    def test_first_creation_of_allowed_root_passes(self):
        self.put('src/new.h', 'int fresh;\n', root=self.repo)
        self.git('add', 'src/new.h')
        p = self.commit('allowed root')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS new-root', p.stderr)

    def test_existing_root_changes_pass(self):
        self.put('src/existing.h', 'int kept = 2;\n', root=self.repo)
        self.git('add', 'src/existing.h')
        p = self.commit('grow existing root')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS new-root', p.stderr)

    def test_root_deletion_passes(self):
        self.git('rm', '-q', 'src/existing.h')
        p = self.commit('drop root')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS new-root', p.stderr)

    def test_unlisted_gitlink_blocks_commit(self):
        self.stage_gitlink('third-party/other', FMT_V1)
        p = self.commit(ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL third-party-layout', p.stderr)
        self.assertIn('E-THIRD-PARTY-LAYOUT', p.stderr)
        self.assertIn('third-party/other', p.stderr)
        self.assertEqual(self.head(), self.head_before)

    def test_plain_file_under_gitlink_path_blocks_commit(self):
        self.put('third-party/fmt/README', 'vendored\n', root=self.repo)
        self.git('add', 'third-party/fmt/README')
        p = self.commit(ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL third-party-layout', p.stderr)
        self.assertIn('E-THIRD-PARTY-LAYOUT', p.stderr)
        self.assertIn('third-party/fmt/README', p.stderr)
        self.assertEqual(self.head(), self.head_before)

    def test_plain_file_at_registered_gitlink_path_blocks_commit(self):
        self.put('third-party/fmt', 'not a submodule\n', root=self.repo)
        self.git('add', 'third-party/fmt')
        p = self.commit(ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL third-party-layout', p.stderr)
        self.assertIn('E-THIRD-PARTY-LAYOUT', p.stderr)
        self.assertIn('100644', p.stderr)
        self.assertIn('third-party/fmt', p.stderr)
        self.assertEqual(self.head(), self.head_before)

    def test_listed_gitlink_first_creation_passes(self):
        self.stage_gitlink('third-party/fmt', FMT_V1)
        p = self.commit('vendor fmt')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS third-party-layout', p.stderr)

    def test_gitlink_pointer_update_passes(self):
        self.stage_gitlink('third-party/fmt', FMT_V1)
        self.commit('vendor fmt')
        self.stage_gitlink('third-party/fmt', FMT_V2)
        p = self.commit('bump fmt')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS third-party-layout', p.stderr)

    def test_gitlink_deletion_passes(self):
        self.stage_gitlink('third-party/fmt', FMT_V1)
        self.commit('vendor fmt')
        self.git('rm', '--cached', '-q', 'third-party/fmt')
        p = self.commit('drop fmt')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS third-party-layout', p.stderr)

    def test_new_root_selected_alone_passes_unchecked_third_party(self):
        """Only new-root in commit.rules: third-party-layout stays out of the commit."""
        self.add_config(layout_toml(commit=('new-root',)))
        self.commit('select new-root only')
        self.stage_gitlink('third-party/other', FMT_V1)
        p = self.commit('gitlink outside allowed_gitlinks')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS new-root', p.stderr)
        self.assertNotIn('third-party-layout', p.stderr)

    def test_third_party_layout_selected_alone_passes_unchecked_new_root(self):
        """Only third-party-layout in commit.rules: new-root stays out of the commit."""
        self.add_config(layout_toml(commit=('third-party-layout',)))
        self.commit('select third-party-layout only')
        self.put('vendor/x.txt', 'x\n', root=self.repo)
        self.git('add', 'vendor/x.txt')
        p = self.commit('unregistered top-level root')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS third-party-layout', p.stderr)
        self.assertNotIn('new-root', p.stderr)

    def test_undecodable_old_name_keeps_existing_root_commits_working(self):
        """Names are raw bytes: a legal src/ change commits beside an undecodable old name (POSIX)."""
        name = b'src/\xfflegacy.dat'
        self.put_bytes(name)
        self.git('add', name)
        self.commit('seed undecodable name')
        self.put('src/existing.h', 'int kept = 3;\n', root=self.repo)
        self.git('add', 'src/existing.h')
        p = self.commit('legal change beside the undecodable name')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS new-root', p.stderr)


class LayoutPushGate(GateCase):
    """Commit stage stays open so bad objects can be produced legally; push reads them."""

    def setUp(self):
        super().setUp()
        self.put('src/existing.h', 'int kept;\n', root=self.repo)
        self.git('add', 'src/existing.h')
        self.git('commit', '-qm', 'seed src')
        self.add_config(layout_toml(push=('new-root', 'third-party-layout')))
        self.commit('config')
        self.remote = self.base / 'bare.git'
        self.git('init', '--bare', '-q', str(self.remote))
        self.git('remote', 'add', 'origin', str(self.remote))
        self.push('main:main')  # clean baseline lands on the bare remote

    def test_push_unknown_new_root_is_rejected_and_not_landed(self):
        self.put('vendor/x.txt', 'x\n', root=self.repo)
        self.git('add', 'vendor/x.txt')
        self.commit('vendor root')  # commit stage has no layout rules
        p = self.push('main:topic', ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('FAIL new-root', p.stderr)
        self.assertIn('E-NEW-ROOT', p.stderr)
        self.assertEqual(self.remote_ref(self.remote, 'refs/heads/topic').returncode, 1)

    def test_push_plain_file_under_third_party_is_rejected_and_not_landed(self):
        self.put('third-party/fmt/README', 'vendored\n', root=self.repo)
        self.git('add', 'third-party/fmt/README')
        self.commit('plain vendored file')
        p = self.push('main:topic', ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('FAIL third-party-layout', p.stderr)
        self.assertIn('E-THIRD-PARTY-LAYOUT', p.stderr)
        self.assertEqual(self.remote_ref(self.remote, 'refs/heads/topic').returncode, 1)

    def test_push_allowed_gitlink_flow_lands(self):
        self.put('src/existing.h', 'int kept = 2;\n', root=self.repo)
        self.stage_gitlink('third-party/fmt', FMT_V1)
        self.git('add', 'src/existing.h')
        self.commit('vendor fmt and grow src')
        p = self.push('main:main')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS new-root', p.stderr)
        self.assertIn('PASS third-party-layout', p.stderr)
        self.stage_gitlink('third-party/fmt', FMT_V2)
        self.commit('bump fmt pointer')
        self.push('main:main')
        self.assertEqual(
            self.git('--git-dir', str(self.remote),
                     'rev-parse', 'refs/heads/main').stdout.strip(),
            self.head(),
        )

    def test_push_legal_change_with_undecodable_old_name_lands(self):
        """The undecodable name rides both trees; a legal src/ change still lands on the bare remote."""
        name = b'src/\xfflegacy.dat'
        self.put_bytes(name)
        self.git('add', name)
        self.commit('seed undecodable name')  # commit stage has no layout rules
        self.put('src/existing.h', 'int kept = 3;\n', root=self.repo)
        self.git('add', 'src/existing.h')
        self.commit('legal change beside the undecodable name')
        p = self.push('main:main')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS new-root', p.stderr)
        self.assertEqual(
            self.git('--git-dir', str(self.remote),
                     'rev-parse', 'refs/heads/main').stdout.strip(),
            self.head(),
        )


class LayoutRulesDefaultOff(GateCase):
    """The default config writes no [layout] section and selects no layout rule IDs."""

    def setUp(self):
        super().setUp()
        self.add_config(layout_toml(layout=False))
        self.commit('config')

    def test_unknown_root_commits_without_layout_config(self):
        self.put('vendor/x.txt', 'x\n', root=self.repo)
        self.git('add', 'vendor/x.txt')
        p = self.commit('no layout config, no layout rule selected')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('FAIL new-root', p.stderr)
        self.assertNotIn('FAIL third-party-layout', p.stderr)


if __name__ == '__main__':
    unittest.main()
