"""Integration tests use owned local repositories only; never contact a remote service."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class HooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bbt-hooks-')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.tools = self.root / 'tools'
        shutil.copytree(SOURCE, self.tools, ignore=shutil.ignore_patterns('__pycache__', 'tests'))
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):
            self.env.pop(key, None)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.put('.clang-format', 'BasedOnStyle: LLVM\n')
        self.put('seed.txt', 'base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()
        self.git('config', 'core.hooksPath', str(self.tools / 'hooks'))

    def tearDown(self):
        self.temp.cleanup()

    def run_cmd(self, *args, ok=True, input=None):
        p = subprocess.run(args, cwd=self.repo, env=self.env, input=input,
                           text=True, capture_output=True, timeout=20)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def git(self, *args, **kw):
        return self.run_cmd('git', *args, **kw)

    def put(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def setting(self, text):
        self.put('.config/bbt-git-hooks.toml', text)

    def commit(self, text='change', ok=True):
        return self.git('commit', '-qm', text, ok=ok)

    def candidate(self):
        self.put('seed.txt', 'changed\n')
        self.git('add', 'seed.txt')
        self.commit()
        return self.git('rev-parse', 'HEAD').stdout.strip()

    def new_ticket(self, sha, base=None, ok=True):
        return self.run_cmd(sys.executable, '-I', str(self.tools / 'stages/push/rules/review-ticket/new.py'),
                            '--commit', sha, '--base', base or self.base, ok=ok)

    def ticket_file(self, sha):
        return next((self.repo / '.config/review-tickets').glob(f'*/{sha}.json'))

    def fill(self, sha, **override):
        """Fill the generated skeleton as a reviewer would, then commit it as a ticket-only commit."""
        path = self.ticket_file(sha)
        ticket = json.loads(path.read_text())
        ticket.update(result='pass', reviewer='tester', summary='reviewed base..commit')
        for check in ticket['checks']:
            check.update(status='pass', summary='ok', evidence={'reviewer': 'tester', 'scope': 'base..commit'})
        ticket.update(override)
        path.write_text(json.dumps(ticket))
        self.git('add', '.config/review-tickets')
        self.commit('ticket')
        return self.git('rev-parse', 'HEAD').stdout.strip()

    def push_check(self, tip, old=None, extra=''):
        data = f'refs/heads/topic {tip} refs/heads/topic {old or self.base}\n' + extra
        return self.run_cmd(sys.executable, '-I', str(self.tools / 'stages/push/main.py'),
                            ok=False, input=data)

    def test_commit_pass_and_index_not_worktree(self):
        self.put('hello.hpp', 'int Hello();\n')
        self.git('add', 'hello.hpp')
        self.put('hello.hpp', '// unstaged invalid comment\n')
        self.commit()
        self.assertEqual(self.git('show', 'HEAD:hello.hpp').stdout, 'int Hello();\n')

    def test_fail_fast_and_message_skip(self):
        self.put('hello.hpp', '// comment\nint Hello();  \n')
        self.git('add', 'hello.hpp')
        p = self.commit(ok=False)
        self.assertIn('FAIL whitespace', p.stderr)
        self.assertNotIn('PASS format', p.stderr)
        self.commit('temporary\n\n--skip-rules whitespace,format,comment-form')

    def test_unknown_skip_even_with_all(self):
        self.git('add', 'seed.txt')
        p = self.git('commit', '--allow-empty', '-qm', 'x\n\n--skip-rules all,typo', ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('unknown skip rules', p.stderr)

    def test_missing_tool_and_config_error(self):
        self.put('hello.hpp', 'int Hello();\n')
        self.git('add', 'hello.hpp')
        self.setting('[format]\nbinary="missing-bbt-formatter"\n')
        p = self.commit(ok=False)
        self.assertIn('ERROR format', p.stderr)
        self.assertNotIn('PASS comment-form', p.stderr)
        self.setting('typo=true\n')
        self.assertIn('unknown key', self.commit(ok=False).stderr)

    def test_deleted_and_unusual_filenames(self):
        for name in ('空 格.hpp', 'line\nbreak.hpp'):
            self.put(name, 'int Hello();\n')
            self.git('add', name)
        self.commit()
        self.git('rm', '空 格.hpp', 'line\nbreak.hpp')
        self.commit('delete')

    def test_comment_strings_and_body_shape(self):
        self.setting('[commit]\nrules=["comment-form"]\n')
        self.put('x.cc', 'const char* s = R"tag(http://hi /* fine */)tag";\n')
        self.git('add', 'x.cc')
        self.commit()
        self.put('x.cc', '/**\n bad body\n */\nint X();\n')
        self.git('add', 'x.cc')
        self.assertNotEqual(self.commit(ok=False).returncode, 0)

    def probe_meta(self, **override):
        meta = dict(id='probe', stage='commit', kind='auto', title='probe title', fix='probe fix', docs='docs/x.md')
        meta.update(override)
        (self.tools / 'stages/commit/rules/probe/meta.toml').write_text(
            ''.join(f'{k} = "{v}"\n' for k, v in meta.items()))

    def test_missing_crashing_timeout_rule_stops(self):
        self.put('seed.txt', 'changed\n')
        self.git('add', 'seed.txt')
        self.setting('[commit]\nrules=["probe","format"]\n')
        p = self.commit(ok=False)
        self.assertIn('missing script', p.stderr)
        rule = self.tools / 'stages/commit/rules/probe/main.py'
        rule.parent.mkdir(parents=True)
        rule.write_text('raise RuntimeError("injected")\n')
        p = self.commit(ok=False)
        self.assertIn('missing meta.toml', p.stderr)
        self.probe_meta()
        p = self.commit(ok=False)
        self.assertIn('without a valid report', p.stderr)
        self.assertIn('RuntimeError: injected', p.stderr)
        self.assertNotIn('PASS format', p.stderr)
        self.setting('timeout_seconds=1\n[commit]\nrules=["probe","format"]\n')
        rule.write_text('import time; time.sleep(10)\n')
        p = self.commit(ok=False)
        self.assertIn('timeout', p.stderr)
        self.assertNotIn('PASS format', p.stderr)

    def test_report_protocol_rendering_and_meta_validation(self):
        self.put('seed.txt', 'changed\n')
        self.git('add', 'seed.txt')
        self.setting('[commit]\nrules=["whitespace","probe","format"]\n')
        rule = self.tools / 'stages/commit/rules/probe/main.py'
        rule.parent.mkdir(parents=True)
        rule.write_text('import json,sys\nprint(json.dumps({"code":"E-PROBE","problems":["a.cc:3: bad"]}))\nsys.exit(1)\n')
        self.probe_meta()
        p = self.commit(ok=False)
        for text in ('FAIL probe  [E-PROBE]', 'probe title (auto)', '问题：a.cc:3: bad', '怎么办：probe fix',
                     '规范（pub 仓库）：docs/x.md', '已通过：whitespace', '未运行：format'):
            self.assertIn(text, p.stderr)
        rule.write_text('import json,sys\nprint(json.dumps({"code":"bad","problems":[]}))\nsys.exit(1)\n')
        self.assertIn('without a valid report', self.commit(ok=False).stderr)
        for bad in (dict(kind='sync'), dict(stage='push'), dict(id='other'), dict(fix=' ')):
            self.probe_meta(**bad)
            self.assertIn('probe:', self.commit(ok=False).stderr, bad)
        meta = self.tools / 'stages/commit/rules/probe/meta.toml'
        meta.write_text(meta.read_text() + 'extra = "x"\n')
        self.assertIn('unknown', self.commit(ok=False).stderr)

    def test_every_shipped_rule_has_valid_meta_and_docs(self):
        sys.path.insert(0, str(SOURCE / 'core'))
        try:
            import runner
        finally:
            sys.path.remove(str(SOURCE / 'core'))
        count = 0
        for stage, folder in runner.FOLDERS.items():
            for rule in (SOURCE / folder / 'rules').iterdir():
                if rule.is_dir():
                    meta = runner.load_meta(stage, rule.name)
                    self.assertTrue((SOURCE.parents[1] / meta['docs']).is_file(), meta['docs'])
                    count += 1
        self.assertEqual(count, 8)
        runner.HOME = SOURCE  # the template must itself be a loadable skeleton
        template = runner.tomllib.loads((SOURCE / 'stages/_template/meta.toml').read_text())
        self.assertEqual(set(template), runner.META_KEYS)

    def test_ticket_flow_missing_pending_pass(self):
        self.setting('[push]\nrules=["review-ticket","llm-review"]\n')
        code = self.candidate()
        p = self.push_check(code)
        self.assertIn('E-TICKET-MISSING', p.stderr)
        self.assertIn('怎么办：', p.stderr)
        self.assertIn('new.py', p.stderr)
        self.assertEqual(self.push_check(self.base).returncode, 0)  # nothing new
        self.new_ticket(code)
        skeleton = json.loads(self.ticket_file(code).read_text())
        self.assertEqual([c['id'] for c in skeleton['checks']], ['llm-review'])
        self.git('add', '.config/review-tickets')
        self.commit('ticket skeleton')
        p = self.push_check(self.git('rev-parse', 'HEAD').stdout.strip())
        self.assertIn('E-TICKET-PENDING', p.stderr)
        self.fill(code)
        tip = self.git('rev-parse', 'HEAD').stdout.strip()
        p = self.push_check(tip)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS review-ticket', p.stderr)
        self.assertIn('PASS llm-review', p.stderr)

    def test_ticket_result_commit_base_and_amend(self):
        self.setting('[push]\nrules=["review-ticket"]\n')
        code = self.candidate()
        self.new_ticket(code)
        tip = self.fill(code, result='fail')
        self.assertIn('E-TICKET-REVIEW-FAILED', self.push_check(tip).stderr)
        self.git('commit', '--amend', '-qm', 'ticket')
        path = self.ticket_file(code)
        for override, text in ((dict(commit=self.base), 'E-TICKET-INVALID'),
                               (dict(base=code), 'E-TICKET-BASE'),
                               (dict(date='2020-01-01'), '不一致'),
                               (dict(checks=[dict(id='llm-review', kind='attested', status='pending')]), '未通过'),
                               (dict(reviewer=''), 'reviewer')):
            ticket = dict(schema_version=1, date=path.parent.name, commit=code, base=self.base, result='pass',
                          reviewer='tester', summary='s', checks=[])
            ticket.update(override)
            path.write_text(json.dumps(ticket))
            self.git('add', '.config/review-tickets')
            self.git('commit', '--amend', '-qm', 'ticket')
            p = self.push_check(self.git('rev-parse', 'HEAD').stdout.strip())
            self.assertIn(text, p.stderr, (override, p.stderr))
        # amending the reviewed code commit makes the old ticket stale: it is looked up by the new hash
        self.git('reset', '-q', '--hard', code)
        self.git('commit', '--amend', '-qm', 'reworded')
        newer = self.git('rev-parse', 'HEAD').stdout.strip()
        self.assertIn('E-TICKET-MISSING', self.push_check(newer).stderr)

    def test_llm_review_evidence_required(self):
        self.setting('[push]\nrules=["llm-review"]\n')
        code = self.candidate()
        self.new_ticket(code)
        tip = self.fill(code, checks=[])
        self.assertIn('E-LLM-REVIEW-MISSING', self.push_check(tip).stderr)
        path = self.ticket_file(code)
        ticket = json.loads(path.read_text())
        ticket['checks'] = [dict(id='llm-review', kind='attested', status='pass', summary='ok')]
        path.write_text(json.dumps(ticket))
        self.git('add', '.config/review-tickets')
        self.git('commit', '--amend', '-qm', 'ticket')
        p = self.push_check(self.git('rev-parse', 'HEAD').stdout.strip())
        self.assertIn('E-LLM-REVIEW-INCOMPLETE', p.stderr)
        self.assertIn('evidence.reviewer', p.stderr)

    def test_ticket_only_push_needs_no_new_ticket(self):
        self.setting('[push]\nrules=["review-ticket"]\n')
        code = self.candidate()
        self.new_ticket(code)
        tip = self.fill(code)
        self.assertEqual(self.push_check(tip, old=code).returncode, 0)

    def test_secrets_and_push_format_run_live(self):
        self.setting('[push]\nrules=["secrets","format"]\n')
        key = 'AKIA' + 'ABCDEFGHIJKLMNOP'
        self.put('conf.txt', f'id = {key}\n')
        self.git('add', 'conf.txt')
        self.commit('with key')
        p = self.push_check(self.git('rev-parse', 'HEAD').stdout.strip())
        self.assertIn('E-SECRETS', p.stderr)
        self.assertIn('conf.txt:1', p.stderr)
        self.assertNotIn(key, p.stderr + p.stdout)
        self.put('conf.txt', f'id = {key}  # bbt-secrets:allow\nuser_name = password_input\nsecret: ${{SECRET_FROM_ENV}}\n')
        self.git('add', 'conf.txt')
        self.commit('allowed')
        self.assertEqual(self.push_check(self.git('rev-parse', 'HEAD').stdout.strip()).returncode, 0)
        self.put('bad.hpp', 'int   Hello( );\n')
        self.git('add', 'bad.hpp')
        self.git('commit', '-qm', 'unformatted\n\n--skip-rules all')
        p = self.push_check(self.git('rev-parse', 'HEAD').stdout.strip())
        self.assertIn('E-FORMAT', p.stderr)
        self.assertIn('PASS secrets', p.stderr)
        self.assertIn('未通过：format', p.stderr)

    def test_real_local_push_uses_pushed_ref_not_head(self):
        remote = self.root / 'remote.git'
        self.git('init', '--bare', '-q', str(remote))
        self.git('remote', 'add', 'origin', str(remote))  # named remote: new-branch range excludes origin/*
        self.setting('[push]\nrules=["review-ticket","llm-review"]\n')
        self.git('add', '.config')
        self.commit('config')
        base = self.git('rev-parse', 'HEAD').stdout.strip()
        self.git('push', '-q', '--no-verify', 'origin', 'main:main')
        self.put('seed.txt', 'changed\n')
        self.git('add', 'seed.txt')
        self.commit('change')
        code = self.git('rev-parse', 'HEAD').stdout.strip()
        p = self.git('push', 'origin', 'main:topic', ok=False)
        self.assertIn('E-TICKET-MISSING', p.stderr)
        self.new_ticket(code, base=base)
        tip = self.fill(code)
        self.git('checkout', '--detach', self.base)
        self.git('push', 'origin', 'main:topic')
        actual = self.git('--git-dir', str(remote), 'rev-parse', 'refs/heads/topic').stdout.strip()
        self.assertEqual(actual, tip)
        self.git('checkout', 'main')
        self.put('seed.txt', 'newer\n')
        self.git('add', 'seed.txt')
        self.git('commit', '-qm', 'new\n\n--skip-rules all')
        p = self.git('push', 'origin', 'main:topic', ok=False)
        self.assertIn('E-TICKET-MISSING', p.stderr)

    def test_deleted_ref_and_new_ticket_guards(self):
        self.setting('[push]\nrules=["review-ticket"]\n')
        self.assertEqual(self.push_check('0' * 40).returncode, 0)
        code = self.candidate()
        self.assertIn('strict ancestor', self.new_ticket(code, base=code, ok=False).stderr)
        self.new_ticket(code)
        self.assertIn('already exists', self.new_ticket(code, ok=False).stderr)


    def test_cli_skip_and_bad_push_input(self):
        self.put('hello.hpp', '// bad\n')
        self.git('add', 'hello.hpp')
        self.run_cmd(sys.executable, '-I', str(self.tools / 'stages/commit/main.py'),
                     '--skip-rules', 'comment-form')
        p = self.run_cmd(sys.executable, '-I', str(self.tools / 'stages/push/main.py'),
                         input='invalid\n', ok=False)
        self.assertEqual(p.returncode, 2)


if __name__ == '__main__':
    unittest.main()
