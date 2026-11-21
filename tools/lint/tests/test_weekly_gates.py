"""Weekly gate regression for git-change rules.

Covers retired-symbol, header-implementation warn-only, comment-form directive
exemptions, enforce_blocks skip semantics, and real commit/push outcomes against
owned repositories with a local bare remote. The rule implementations are written
by the parent change; this file only adds regression tests and never touches
product code, existing tests, or a real remote.
"""
import unittest

from _support import GitCase

RETIRED = (
    '[[retired]]\n'
    'path = "tests/*"\n'
    'symbols = ["ServerV2LedgerForTest"]\n'
)


def gate_toml(*, enforce_blocks=False, commit=(), push=(), scan=('T501',), extra=''):
    """schema 2 config with top-level keys emitted before tables."""
    lines = ['schema_version = 2', 'timeout_seconds = 60']
    if enforce_blocks:
        lines.append('enforce_blocks = true')
    for section, rules in (('scan', scan), ('commit', commit), ('push', push)):
        lines.append(f'[{section}]')
        lines.append('rules = [' + ', '.join(f'"{r}"' for r in rules) + ']')
        lines.append('')
    lines.append(extra)
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

    def remote_ref_exists(self, remote, ref):
        return self.git(
            '--git-dir', str(remote), 'rev-parse', '--verify', '--quiet', ref, ok=False
        )


class RetiredSchemaScanTest(GateCase):
    def test_retired_schema_is_accepted(self):
        self.add_config(gate_toml(extra=RETIRED))
        self.put('a.h', 'int x;\n')
        p = self.scan('--format', 'json')
        self.assertEqual(p.returncode, 0, p.stderr)


class RetiredSymbolCommitGate(GateCase):
    def setUp(self):
        super().setUp()
        self.add_config(gate_toml(commit=('retired-symbol',), extra=RETIRED))
        self.commit('config')

    def test_added_retired_symbol_rejects_commit(self):
        self.put('tests/ledger.cc', 'ServerV2LedgerForTest x;\n', root=self.repo)
        self.git('add', 'tests/ledger.cc')
        p = self.commit(ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL retired-symbol', p.stderr)
        self.assertIn('E-RETIRED-SYMBOL', p.stderr)
        self.assertIn('tests/ledger.cc', p.stderr)
        self.assertIn('ServerV2LedgerForTest', p.stderr)

    def test_comment_and_string_are_exempt(self):
        text = (
            '// migration note: ServerV2LedgerForTest\n'
            'const char* name = "ServerV2LedgerForTest";\n'
            'int kept = 1;\n'
        )
        self.put('tests/ledger.cc', text, root=self.repo)
        self.git('add', 'tests/ledger.cc')
        p = self.commit()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS retired-symbol', p.stderr)

    def test_untouched_existing_line_is_not_scanned(self):
        # Commit the seam while the rule is enabled but no [[retired]] entry
        # applies yet (commit stage has no rules at all).
        self.add_config(gate_toml(commit=()))
        self.put('tests/ledger.cc', 'ServerV2LedgerForTest base;\n', root=self.repo)
        self.git('add', 'tests/ledger.cc')
        self.commit('base seam')
        # Enable the retired entry; only the newly added line is scanned now.
        self.add_config(gate_toml(commit=('retired-symbol',), extra=RETIRED))
        self.put(
            'tests/ledger.cc',
            'ServerV2LedgerForTest base;\nint kept = 2;\n',
            root=self.repo,
        )
        self.git('add', 'tests/ledger.cc')
        p = self.commit('unrelated change')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS retired-symbol', p.stderr)

    def test_similar_suffixed_names_are_exempt(self):
        self.put(
            'tests/ledger.cc',
            'ServerV2LedgerForTestHelper h;\nServerV2LedgerForTest2 v;\n',
            root=self.repo,
        )
        self.git('add', 'tests/ledger.cc')
        p = self.commit()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS retired-symbol', p.stderr)

    def test_public_k_rpc_v2_constant_is_not_retired(self):
        self.put('tests/rpc.h', 'int kRpcV2X;\n', root=self.repo)
        self.git('add', 'tests/rpc.h')
        p = self.commit()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS retired-symbol', p.stderr)

    def test_explicit_retired_path_overrides_scope_exclude(self):
        """[[retired]] path wins over the generic scope.exclude glob."""
        self.add_config(
            gate_toml(
                commit=('retired-symbol',),
                extra='[scope]\nexclude = ["tests/*", "*/tests/*"]\n' + RETIRED,
            )
        )
        self.put('tests/ledger.cc', 'ServerV2LedgerForTest x;\n', root=self.repo)
        self.git('add', 'tests/ledger.cc')
        p = self.commit(ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL retired-symbol', p.stderr)


class RetiredSymbolPushGate(GateCase):
    """commit stage stays open so a bad object can be produced legally;
    push stage runs retired-symbol and must reject it."""

    def setUp(self):
        super().setUp()
        self.add_config(gate_toml(push=('retired-symbol',), extra=RETIRED))
        self.commit('config')
        self.remote = self.base / 'bare.git'
        self.git('init', '--bare', '-q', str(self.remote))
        self.git('remote', 'add', 'origin', str(self.remote))
        self.push('main:main')  # clean baseline lands on the bare remote

    def test_commit_produces_bad_object_legally(self):
        self.put('tests/bad.cc', 'ServerV2LedgerForTest x;\n', root=self.repo)
        self.git('add', 'tests/bad.cc')
        p = self.commit('bad object')
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_push_of_bad_object_is_rejected_and_not_landed(self):
        self.put('tests/bad.cc', 'ServerV2LedgerForTest x;\n', root=self.repo)
        self.git('add', 'tests/bad.cc')
        self.commit('bad object')
        p = self.push('main:topic', ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('FAIL retired-symbol', p.stderr)
        self.assertIn('E-RETIRED-SYMBOL', p.stderr)
        self.assertIn('tests/bad.cc', p.stderr)
        self.assertEqual(self.remote_ref_exists(self.remote, 'refs/heads/topic').returncode, 1)


class HeaderImplementationWarnGate(GateCase):
    def setUp(self):
        super().setUp()
        self.add_config(
            gate_toml(
                commit=('header-implementation',),
                push=('header-implementation',),
                extra='[rules.header-implementation]\nlevel = "warn"\n',
            )
        )
        self.commit('config')

    def assert_warn_only(self, p):
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('WARN header-implementation', p.stderr)
        self.assertNotIn('FAIL header-implementation', p.stderr)
        self.assertNotIn('PASS header-implementation', p.stderr)

    def test_template_body_warns_but_commit_continues(self):
        self.put(
            'api/cache.hpp',
            'template <typename T>\nT get(T x) { return x; }\n',
            root=self.repo,
        )
        self.git('add', 'api/cache.hpp')
        self.assert_warn_only(self.commit())

    def test_nontrivial_non_template_body_warns(self):
        self.put(
            'api/math.h',
            'int compute(int x) {\n  if (x > 0) { return x; }\n  return 0;\n}\n',
            root=self.repo,
        )
        self.git('add', 'api/math.h')
        self.assert_warn_only(self.commit())

    def test_single_line_getter_passes(self):
        self.put(
            'api/cache.h',
            'struct Cache {\n  int get() const { return 0; }\n};\n',
            root=self.repo,
        )
        self.git('add', 'api/cache.h')
        p = self.commit()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS header-implementation', p.stderr)

    def test_t_header_implementation_passes(self):
        self.put(
            '__Tcache.hpp',
            'template <typename T>\nT get(T x) { return x; }\n',
            root=self.repo,
        )
        self.git('add', '__Tcache.hpp')
        p = self.commit()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS header-implementation', p.stderr)

    def test_warn_push_continues_to_bare(self):
        remote = self.base / 'bare.git'
        self.git('init', '--bare', '-q', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        self.put(
            'api/cache.hpp',
            'template <typename T>\nT get(T x) { return x; }\n',
            root=self.repo,
        )
        self.git('add', 'api/cache.hpp')
        self.commit('template header')
        p = self.push('main:main')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('WARN header-implementation', p.stderr)
        self.assertEqual(
            self.git(
                '--git-dir',
                str(remote),
                'rev-parse',
                '--verify',
                '--quiet',
                'refs/heads/main',
                ok=False,
            ).returncode,
            0,
        )


class CommentFormGate(GateCase):
    def setUp(self):
        super().setUp()
        self.add_config(gate_toml(commit=('comment-form',)))

    def test_clang_format_off_on_are_exempt(self):
        text = (
            '// clang-format off\n'
            'int   x  ;\n'
            '// clang-format on\n'
        )
        self.put('x.cc', text, root=self.repo)
        self.git('add', 'x.cc')
        p = self.commit()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS comment-form', p.stderr)

    def test_nolintnextline_is_exempt(self):
        self.put('x.cc', '// NOLINTNEXTLINE\nint   bad;\n', root=self.repo)
        self.git('add', 'x.cc')
        p = self.commit()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('PASS comment-form', p.stderr)

    def test_non_compliant_comment_is_rejected(self):
        self.put('x.cc', '/**\n bad body\n */\nint X();\n', root=self.repo)
        self.git('add', 'x.cc')
        p = self.commit(ok=False)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn('FAIL comment-form', p.stderr)


class EnforceBlocksGate(GateCase):
    def setUp(self):
        super().setUp()
        self.add_config(
            gate_toml(
                enforce_blocks=True,
                commit=('whitespace', 'retired-symbol'),
                extra=RETIRED,
            )
        )
        self.commit('config')

    def test_mandatory_rule_cannot_be_skipped(self):
        self.put('x.cc', 'int f() { return 0; }  \n', root=self.repo)
        self.git('add', 'x.cc')
        p = self.git(
            'commit', '-qm', 'msg\n\n--skip-rules retired-symbol', ok=False
        )
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('mandatory rules cannot be skipped', p.stderr)

    def test_warn_rule_can_be_skipped(self):
        self.add_config(
            gate_toml(
                enforce_blocks=True,
                commit=('whitespace', 'retired-symbol'),
                extra=(
                    '[rules.retired-symbol]\nlevel = "warn"\n' + RETIRED
                ),
            )
        )
        self.put('x.cc', 'int x;\n', root=self.repo)
        self.git('add', 'x.cc')
        p = self.git('commit', '-qm', 'msg\n\n--skip-rules retired-symbol')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('SKIP retired-symbol', p.stderr)
        self.assertIn('PASS whitespace', p.stderr)


class RetiredConfigValidationTest(GateCase):
    def test_invalid_retired_symbol_is_rejected(self):
        bad = (
            '[[retired]]\n'
            'path = "tests/*"\n'
            'symbols = ["Bad-Name!"]\n'
        )
        self.add_config(gate_toml(commit=('retired-symbol',), extra=bad))
        self.put('x.cc', 'int x;\n', root=self.repo)
        self.git('add', 'x.cc')
        p = self.commit(ok=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('retired.symbols requires exact C++ identifiers', p.stderr)


if __name__ == '__main__':
    unittest.main()
