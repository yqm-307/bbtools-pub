"""Long-signature const/override wrapping: one shared rule for the CLI and the Git hook stages.

Fixtures mirror tools/git-hooks/tests/test_hooks.py but pin the repository's own .clang-format
instead of a bare LLVM style, so expectations exercise the real acceptance configuration.
Integration tests use owned local repositories only; never contact a remote service.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

GIT_HOOKS = Path(__file__).resolve().parents[1]
PUB = GIT_HOOKS.parents[1]

VERSION = subprocess.run(['clang-format', '--version'], capture_output=True, text=True).stdout
if 'clang-format version 23.1.3' not in VERSION:
    raise unittest.SkipTest(f'need clang-format 23.1.3; got {VERSION.strip() or "missing"}')

# clang-format 23.1.3 fits the parameters on one line and dangles const/override; the shared
# formatter must instead break after '(' with one parameter per line and ') const'/') override'.
ORPHAN_INPUT = '''\
class Client {
    result<PreparedRequest> BuildRequest(std::string_view method, std::string_view url, const RequestOptions& options) const;
    std::error_code AsyncWrite(std::string data) override;
};
'''
FIXED_OUTPUT = '''\
class Client {
    result<PreparedRequest> BuildRequest(
        std::string_view method,
        std::string_view url,
        const RequestOptions& options) const;
    std::error_code AsyncWrite(std::string data) override;
};
'''

ORPHAN_OVERRIDE_INPUT = '''\
class CoTcpConnection {
    std::tuple<std::size_t, std::error_code> Write(std::string data, const bbt::coroutine::WaitOptions& options = {}) override;
    ReadView View() override;
};
'''
FIXED_OVERRIDE_OUTPUT = '''\
class CoTcpConnection {
    std::tuple<std::size_t, std::error_code> Write(
        std::string data,
        const bbt::coroutine::WaitOptions& options = {}) override;
    ReadView View() override;
};
'''

ORPHAN_DEFINITION_INPUT = '''\
std::error_code Engine::ReactorOwnerIds(std::vector<std::uint64_t>& main_owners, std::vector<std::uint64_t>& sub_owners) const
{
    return m_impl->ReactorOwnerIds(main_owners, sub_owners);
}
'''
FIXED_DEFINITION_OUTPUT = '''\
std::error_code Engine::ReactorOwnerIds(
    std::vector<std::uint64_t>& main_owners,
    std::vector<std::uint64_t>& sub_owners) const
{
    return m_impl->ReactorOwnerIds(main_owners, sub_owners);
}
'''

# Orphan-shaped const/override tokens inside a raw string and inside comments must neither be
# rewritten themselves nor corrupt the adjacent short signatures when the long one is rewrapped.
NOISE_INPUT = '''\
const char* sql = R"sql(
    int Fake() const;
)sql";
// int Commented() override;
int Fit();
class Client {
    result<PreparedRequest> BuildRequest(std::string_view method, std::string_view url, const RequestOptions& options) const;
    int Fit() const;
};
// result<PreparedRequest> BuildRequest(std::string_view method, std::string_view url, const RequestOptions& options) const;
'''
NOISE_FIXED_OUTPUT = '''\
const char* sql = R"sql(
    int Fake() const;
)sql";
// int Commented() override;
int Fit();

class Client {
    result<PreparedRequest> BuildRequest(
        std::string_view method,
        std::string_view url,
        const RequestOptions& options) const;
    int Fit() const;
};

// result<PreparedRequest> BuildRequest(std::string_view method, std::string_view url, const RequestOptions& options) const;
'''

INCOMPLETE_INPUT = '''\
class A {
public:
    int foo(
};
'''


class SignatureFormatTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bbt-signature-format-')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.tools = self.root / 'tools/git-hooks'
        shutil.copytree(GIT_HOOKS, self.tools, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        shutil.copytree(PUB / 'tools/lint', self.tools.parent / 'lint', ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        shutil.copytree(PUB / 'tools/format', self.tools.parent / 'format',
                        ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):
            self.env.pop(key, None)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.invalid')
        shutil.copyfile(PUB / '.clang-format', self.repo / '.clang-format')
        self.put('seed.txt', 'base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.git('config', 'core.hooksPath', str(self.tools / 'hooks'))

    def tearDown(self):
        self.temp.cleanup()

    def run_cmd(self, *args, ok=True):
        p = subprocess.run(args, cwd=self.repo, env=self.env, text=True, capture_output=True, timeout=30)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def git(self, *args, **kw):
        return self.run_cmd('git', *args, **kw)

    def put(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def format_cpp(self, *args, ok=True):
        return self.run_cmd(sys.executable, '-I', str(self.tools.parent / 'format/format-cpp.py'), *args, ok=ok)

    def stage(self, name, input=None, ok=True):
        p = subprocess.run([sys.executable, '-I', str(self.tools / f'stages/{name}/main.py')],
                           cwd=self.repo, env=self.env, input=input, text=True, capture_output=True, timeout=30)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def setting(self, text):
        self.put('.config/bbt-git-hooks.toml', text)

    def push_format(self, tip, base):
        data = f'refs/heads/topic {tip} refs/heads/topic {base}\n'
        return self.stage('push', input=data, ok=False)

    def commit(self, text='change', ok=True):
        return self.git('commit', '-qm', text, ok=ok)

    def test_cli_wraps_orphaned_const_and_override(self):
        self.put('sigs.hpp', ORPHAN_INPUT)
        self.put('conn.hpp', ORPHAN_OVERRIDE_INPUT)
        self.put('engine.cc', ORPHAN_DEFINITION_INPUT)
        self.git('add', '.')
        p = self.format_cpp('--check', '--all', ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('sigs.hpp', p.stderr)
        self.format_cpp('--all')
        self.assertEqual((self.repo / 'sigs.hpp').read_text(), FIXED_OUTPUT)
        self.assertEqual((self.repo / 'conn.hpp').read_text(), FIXED_OVERRIDE_OUTPUT)
        self.assertEqual((self.repo / 'engine.cc').read_text(), FIXED_DEFINITION_OUTPUT)
        p = self.format_cpp('--check', '--all')
        self.assertIn('0 updated', p.stdout + p.stderr)

    def test_cli_second_run_is_stable(self):
        self.put('sigs.hpp', ORPHAN_INPUT)
        self.git('add', '.')
        self.format_cpp('--all')
        first = (self.repo / 'sigs.hpp').read_text()
        p = self.format_cpp('--all')
        self.assertEqual((self.repo / 'sigs.hpp').read_text(), first)
        self.assertIn('0 updated', p.stdout + p.stderr)

    def test_cli_noise_lines_do_not_rewrap_or_corrupt_short_signatures(self):
        self.put('noise.hpp', NOISE_INPUT)
        self.git('add', '.')
        self.format_cpp('--all')
        self.assertEqual((self.repo / 'noise.hpp').read_text(), NOISE_FIXED_OUTPUT)

    def test_cli_check_staged_reads_frozen_index_blobs(self):
        self.put('sigs.hpp', ORPHAN_INPUT)
        self.git('add', 'sigs.hpp')
        self.put('sigs.hpp', FIXED_OUTPUT)  # the worktree is clean; the staged blob is not
        p = self.format_cpp('--check', '--staged', ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('sigs.hpp', p.stderr)

    def test_cli_incomplete_input_is_not_clean(self):
        self.put('broken.hpp', INCOMPLETE_INPUT)
        self.git('add', '.')
        p = self.format_cpp('--check', '--all', ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('incomplete', p.stderr)

    def test_commit_hook_accepts_fixed_signatures_from_frozen_blobs(self):
        self.put('sigs.hpp', FIXED_OUTPUT)
        self.put('engine.cc', FIXED_DEFINITION_OUTPUT)
        self.git('add', '.')
        self.put('sigs.hpp', ORPHAN_INPUT)  # unstaged rewrite must not affect the committed snapshot
        p = self.commit('fixed signatures')
        self.assertIn('PASS format', p.stderr)
        self.assertEqual(self.git('show', 'HEAD:sigs.hpp').stdout, FIXED_OUTPUT)

    def test_commit_hook_rejects_orphaned_blob_even_when_worktree_is_fixed(self):
        self.put('sigs.hpp', ORPHAN_INPUT)
        self.git('add', 'sigs.hpp')
        self.put('sigs.hpp', FIXED_OUTPUT)  # the worktree matches the target shape; the blob does not
        p = self.commit('orphan', ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('FAIL format', p.stderr)

    def test_push_hook_rejects_orphaned_committed_blob(self):
        self.put('conn.hpp', ORPHAN_OVERRIDE_INPUT)
        self.git('add', 'conn.hpp')
        self.git('commit', '-qm', 'unformatted\n\n--skip-rules all')
        self.setting('[push]\nrules=["format"]\n')
        self.git('add', '.config')
        self.git('commit', '-qm', 'config\n\n--skip-rules all')
        tip = self.git('rev-parse', 'HEAD').stdout.strip()
        base = self.git('rev-parse', 'HEAD~2').stdout.strip()
        p = self.push_format(tip, base)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('FAIL format', p.stderr)

    def test_push_hook_accepts_fixed_committed_blob(self):
        self.put('conn.hpp', FIXED_OVERRIDE_OUTPUT)
        self.git('add', 'conn.hpp')
        self.commit('fixed')
        self.setting('[push]\nrules=["format"]\n')
        self.git('add', '.config')
        self.commit('config')
        tip = self.git('rev-parse', 'HEAD').stdout.strip()
        base = self.git('rev-parse', 'HEAD~2').stdout.strip()
        p = self.push_format(tip, base)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('PASS format', p.stderr)


if __name__ == '__main__':
    unittest.main()
