"""Shared harness: temporary source trees for lint.py and owned Git repos for hooks.

Tests copy the tools tree into each temp dir so extension tests can add rule
directories without touching the real checkout. Nothing here installs hooks,
writes Git config outside the owned repo, or contacts a remote.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]  # tools/lint
WORKTREE = SOURCE.parents[1]                  # repo checkout root
PUB = SOURCE.parent                           # tools/


def lint_entry(tools):
    return tools / 'lint/lint.py'


def config_text(scan=('T501',), commit=(), push=(), extra=''):
    lines = ['schema_version = 2', 'timeout_seconds = 60', '']
    for stage, rules in (('scan', scan), ('commit', commit), ('push', push)):
        lines.append(f'[{stage}]')
        lines.append('rules = [' + ', '.join(f'"{r}"' for r in rules) + ']')
        lines.append('')
    lines.append(extra)
    return '\n'.join(lines)


class LintCase(unittest.TestCase):
    """Temp dir with a copied tools tree and an empty source root."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bbt-lint-')
        self.base = Path(self.temp.name)
        self.tools = self.base / 'tools'
        for name in ('lint', 'git-hooks', 'format'):
            shutil.copytree(PUB / name, self.tools / name,
                            ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        self.root = self.base / 'src'
        self.root.mkdir()
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, text, root=None):
        path = (root or self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def lint_config(self, text):
        return self.put('.config/lint.toml', text)

    def run_cmd(self, *args, cwd=None, input=None, timeout=30):
        return subprocess.run(args, cwd=cwd or self.root, env=self.env, input=input,
                              text=True, capture_output=True, timeout=timeout)

    def scan(self, *args):
        return self.run_cmd(sys.executable, '-I', str(lint_entry(self.tools)),
                            '--root', str(self.root), *args)

    def scan_json(self, *args):
        p = self.scan('--format', 'json', *args)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def findings(self, report, rule=None):
        rows = report['findings']
        if rule:
            rows = [r for r in rows if r['rule'] == rule]
        return rows


class GitCase(LintCase):
    """Owned temporary repo; hooks run as stage scripts, never installed."""

    def setUp(self):
        super().setUp()
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME='lint-qa', GIT_AUTHOR_EMAIL='lint-qa@example.invalid',
                        GIT_COMMITTER_NAME='lint-qa', GIT_COMMITTER_EMAIL='lint-qa@example.invalid')
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):
            self.env.pop(key, None)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'lint-qa')
        self.git('config', 'user.email', 'lint-qa@example.invalid')
        self.put('.clang-format', 'BasedOnStyle: LLVM\n', root=self.repo)
        self.put('seed.txt', 'base\n', root=self.repo)
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base_commit = self.git('rev-parse', 'HEAD').stdout.strip()

    def git(self, *args, **kw):
        p = self.run_cmd('git', *args, cwd=self.repo, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def stage(self, name, input=None):
        return self.run_cmd(sys.executable, '-I',
                            str(self.tools / f'git-hooks/stages/{name}/main.py'),
                            cwd=self.repo, input=input)

    def commit_hook(self):
        return self.stage('commit')

    def push_hook(self, tip, old=None):
        old = old or self.base_commit
        return self.stage('push', input=f'refs/heads/topic {tip} refs/heads/topic {old}\n')

    def commit_all(self, message='change'):
        self.git('add', '.')
        return self.git('commit', '-qm', message)
