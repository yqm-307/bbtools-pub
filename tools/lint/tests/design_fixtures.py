"""T2 共享夹具与断言助手：28 项设计检查的冻结预期。

预期来源（不从工具输出反推）：
- design-complexity-check-map.md，SHA-256
  fdce6c7e875f04c5ecacb7a9924fbe09d9b44597f747ac89a949f79b44d88f3b（§0/§1/§4）；
- code-smell-catalog-v01.md，SHA-256
  66c8526b6c1da3a2468db03d572fb2607ee12300caed62f6302dc3291f02b035。

T2 声明的按键输入契约（§4.1「新增一项只加配置键」范围内的最小扩展；T3 按此实现，
如需改判先与 QA 一起更新对应断言与注释）：
- ``[design].cdb``   B-类构建输入：相对 root 的 compile_commands.json 路径，缺省
  ``build-vscode/compile_commands.json``（bbtools-infra 实际布局，映射 §3.3-2）；
- ``[design."2.1"]`` ``private``/``allow`` 头边界声明 + ``targets`` 目录→目标映射；
- ``[design."2.2".graph]`` ``targets``/``forbidden``/``assembly`` 目标图与禁边声明；
- ``[design."3.4"]`` ``forbidden`` 禁用拼写契约 + ``test_targets`` + ``targets``；
- ``[design."5.4"]`` ``contract_file`` 迁移契约文件路径；
- ``5.1`` 复用既有 ``[[retired]]``；``5.1/5.2/5.3/2.4`` 为历史项，需 ``--baseline``（§4.1）。

行内未配状态的缺输入码，T2 按以下规则定型（各测试注释注明依据）：
- ``NO_*``、``*_UNRESOLVED``、``*_UNKNOWN``、``*_HIDDEN``、``RACE_UNREPRODUCIBLE``、
  ``ERROR_ERASED``、``IDEMPOTENCY_UNKNOWN``、``STATE_UNOBSERVABLE``、
  ``EFFECT_UNOBSERVABLE``、``INIT_HIDDEN`` → ``uncovered``；
- 成对出现在其他行的码跟随成对状态：``EXTERNAL_UNKNOWN``→manual_pending、
  ``CALLERS_PARTIAL``/``PATHS_PARTIAL``/``EDGE_PARTIAL``→candidate、
  ``CHAIN_PARTIAL``→manual_pending、``TEXT_ONLY``→candidate；
- 6.3 行内 ``candidate/CHAIN_PARTIAL`` 与 §0.3 人工上限、§2 分桶冲突，按上限冻结为
  manual_pending（handoff 记录；改判只需改 test_design_cat6 一处）。

红测口径：T3 未实现 ``--design`` 入口前，本套测试全部失败并在消息前缀
``[DESIGN-ENTRY-MISSING]`` 标明；这是预期中的红，不是夹具缺陷。
"""
import hashlib
import json
from pathlib import Path
import sys

from _support import LintCase, GitCase, lint_entry

CDB_DEFAULT = 'build-vscode/compile_commands.json'

# §1 各行判定类 → §4.3 checks[].class；3.4 按可定路径冻结为 contract。
CLASS = {
    '1.1': 'manual', '1.2': 'behavior', '1.3': 'manual', '1.4': 'behavior',
    '1.5': 'clue', '1.6': 'behavior',
    '2.1': 'contract', '2.2': 'contract', '2.3': 'clue', '2.4': 'manual', '2.5': 'manual',
    '3.1': 'clue', '3.2': 'behavior', '3.3': 'behavior', '3.4': 'contract',
    '4.1': 'behavior', '4.2': 'clue', '4.3': 'manual', '4.4': 'behavior',
    '5.1': 'contract', '5.2': 'clue', '5.3': 'manual', '5.4': 'clue',
    '6.1': 'clue', '6.2': 'manual', '6.3': 'manual', '6.4': 'clue', '6.5': 'behavior',
}

# §1 各行「事实」列的必需字段名（逐字取自映射表）。
FIELDS = {
    '1.1': ('state_subject', 'writers', 'readers', 'dual_write_pairs',
            'unique_writer_contract', 'cache_protocol'),
    '1.2': ('params', 'same_type_adjacent_pairs', 'strong_type', 'swap_compiles'),
    '1.3': ('group_fields', 'layers', 'shared_invariant_contract',
            'independent_use_sites'),
    '1.4': ('acquisitions', 'owners', 'exit_paths', 'release_sites',
            'raii_wrapper', 'uncovered_paths'),
    '1.5': ('lock_decl', 'external_access', 'protected_data', 'protocol_ref',
            't102_candidate'),
    '1.6': ('terminal_callback_decl', 'cancel_sites', 'complete_sites', 'once_guard',
            'replay_order', 'notifications_observed', 'contract_max'),
    '2.1': ('include_directive', 'resolved_header', 'including_target',
            'boundary_decl', 'exception_match'),
    '2.2': ('target_nodes', 'target_edges', 'forbidden_edges', 'violating_edges',
            'ref_sites', 'assembly_exception'),
    '2.3': ('chain', 'contract_ref', 'callers', 't401_candidate'),
    '2.4': ('change_set', 'modules', 'mapping_duplicates', 'independent_tests',
            'knowledge_kind'),
    '2.5': ('extension_point', 'implementations', 'consumers', 'promise_ref',
            'variation_demand_ref', 'assembly_cost'),
    '3.1': ('bool_params', 'controlled_branches', 'branch_effects', 'call_sites',
            'attribute_like_name'),
    '3.2': ('phases', 'preconditions', 'normal_ops', 'failure_mode',
            'type_constraint', 'docs_ref', 'call_order_observed'),
    '3.3': ('owner_type', 'field', 'caller_functions', 'access_sequence',
            'owner_operations', 'invariant_ref', 'getter_mediated', 'read_only_use'),
    '3.4': ('symbol', 'decl_scope', 'target', 'production_refs',
            'forbidden_contract', 't601_candidate', 'test_target_match'),
    '4.1': ('failure_sites', 'error_type', 'return_values',
            'contract_empty_semantics', 'caller_checks', 'distinguishability_test',
            'log_only'),
    '4.2': ('catch_sites', 'caught_type', 'actions', 'error_propagation',
            'outer_exit', 'contract_ref', 'caller_observes'),
    '4.3': ('validation_sites', 'data_source', 'trust_boundary',
            'immutable_guarantee', 'external_input', 'duplicate_pairs',
            'removal_risk'),
    '4.4': ('retry_layers', 'operation_side_effect', 'idempotency_key',
            'budget_owner', 'timeout_path', 'duplicate_write_test'),
    '5.1': ('retired_symbol', 'scope_glob', 'new_lines', 'matched_spelling',
            'skipped_contexts', 'compat_exception'),
    '5.2': ('duplicate_pairs', 'knowledge_kind', 'contract_refs', 'change_history'),
    '5.3': ('old_impl', 'refs', 'abi_export', 'dynamic_registration',
            'template_instantiation', 'external_consumers', 'replacement',
            'deletion_risk'),
    '5.4': ('versioned_symbols', 'entry_pairs', 'callers', 'migration_contract',
            'exit_condition', 'public_protocol_parallel', 't501_candidate'),
    '6.1': ('condition_site', 'branch_statements', 'normalized_equal',
            'condition_side_effect', 'empty_branch'),
    '6.2': ('function', 'responsibility_candidates', 'data_flow', 'change_reasons',
            'split_cost'),
    '6.3': ('chain', 'forward_only', 'contract_per_layer', 'entry', 'effect',
            'hop_count', 'real_call_example'),
    '6.4': ('comment', 'target_symbol', 'restates_name', 'extra_info',
            't202_candidate'),
    '6.5': ('operation', 'side_effects', 'contract_ref', 'before_after_assertions',
            'call_sites'),
}

DESIGN_KEYS = {
    source_ref: f'design.{slug}'
    for source_ref, slug in (
        ('1.1', 'co-written-fields'), ('1.2', 'primitive-parameter-pair'),
        ('1.3', 'group-forwarding'), ('1.4', 'resource-release-paths'),
        ('1.5', 'cross-object-lock'), ('1.6', 'callback-multiple-paths'),
        ('2.1', 'private-header-boundary'), ('2.2', 'forbidden-target-edge'),
        ('2.3', 'forwarding-layer'), ('2.4', 'cochanged-mapping'),
        ('2.5', 'interface-consumers'), ('3.1', 'boolean-branch-switch'),
        ('3.2', 'state-gated-operation'), ('3.3', 'caller-maintains-owner-state'),
        ('3.4', 'test-seam-in-production'), ('4.1', 'empty-value-on-failure'),
        ('4.2', 'logging-only-catch'), ('4.3', 'repeated-validation'),
        ('4.4', 'nested-retry-clue'), ('5.1', 'retired-symbol'),
        ('5.2', 'repeated-declaration'), ('5.3', 'legacy-implementation'),
        ('5.4', 'versioned-entry'), ('6.1', 'identical-branch-tokens'),
        ('6.2', 'mixed-operation-body'), ('6.3', 'consecutive-forwarders'),
        ('6.4', 'comment-restates-code'), ('6.5', 'query-shaped-consumption'))
}
SOURCE_REFS = {value: key for key, value in DESIGN_KEYS.items()}


def design_config(*, rules=(), manual=(), cdb=False, extra=''):
    """§4.2 配置契约：schema 2 + [design] 段；per-key 输入由 extra 追加。"""
    lines = ['schema_version = 2', 'timeout_seconds = 60', '',
             '[scan]', 'rules = []', '',
             '[commit]', 'rules = []', '',
             '[push]', 'rules = []', '',
             '[design]',
             'rules = [' + ', '.join(f'"{k}"' for k in rules) + ']',
             'manual = [' + ', '.join(f'"{k}"' for k in manual) + ']']
    if cdb:
        lines.append(f'cdb = "{CDB_DEFAULT}"')
    if extra:
        lines.append(extra)
    return '\n'.join(lines) + '\n'


def cdb_text(root, files):
    """最小 compile_commands.json：只声明存在性，语义后端如何使用由 T3 决定。"""
    entries = [{'directory': str(root), 'command': f'c++ -std=c++17 -I{root} {f}',
                'file': f} for f in files]
    return json.dumps(entries, indent=1)


def quote_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def expected_contract_ref(text, marker, relpath):
    """按 §4.3 contract_ref 结构从夹具文本推导期望值（输入推导，非输出反推）。"""
    lines = text.splitlines()
    idx = next(i for i, line in enumerate(lines) if marker in line)
    quote = lines[idx].strip()
    return {'path': relpath, 'line': idx + 1, 'quote': quote,
            'sha256': quote_sha(quote)}


class DesignCase(LintCase):
    """单键场景：写源码树 + [design] 配置，跑统一入口并冻结断言。"""

    def put_tree(self, files, root=None, cdb=False):
        r = Path(root or self.root)
        for name, text in files.items():
            self.put(name, text, root=r)
        if cdb:
            self.put(CDB_DEFAULT, cdb_text(r, tuple(files)), root=r)
        return r

    def put_design_config(self, *, rules=(), manual=(), cdb=False, extra='',
                          root=None):
        text = design_config(rules=rules, manual=manual, cdb=cdb, extra=extra)
        self.put('.config/lint.toml', text, root=root or self.root)
        self.last_cfg_text = text
        return text

    def design_run(self, *, keys=(), baseline=None, fmt='json', design=True,
                   root=None):
        args = [sys.executable, '-I', str(lint_entry(self.tools)),
                '--root', str(root or self.root),
                '--config', str(Path(root or self.root) / '.config/lint.toml'),
                '--format', fmt]
        if design:
            args.append('--design')
        for key in keys:
            args += ['--check', key]
        if baseline:
            args += ['--baseline', baseline]
        return self.run_cmd(*args)

    def design_report(self, ctx='', **kw):
        """跑入口并解析报告；入口未实现时抛 [DESIGN-ENTRY-MISSING]。"""
        p = self.design_run(**kw)
        if p.stdout.strip():
            try:
                return p, json.loads(p.stdout)
            except json.JSONDecodeError:
                raise AssertionError(
                    f'[DESIGN-REPORT-INVALID] {ctx}: rc={p.returncode} '
                    f'stderr={p.stderr.strip()[:300]}')
        err = p.stderr or ''
        if '--design' in err and ('unrecognized' in err or 'invalid choice' in err):
            raise AssertionError(
                f'[DESIGN-ENTRY-MISSING] {ctx}: 统一设计入口未实现（T3 待做）；'
                f'rc={p.returncode} stderr={err.strip()[:300]}')
        return p, None

    def one(self, key, files, *, manual=False, cdb=False, extra='', baseline=None,
            fmt='json'):
        """写单键场景并只跑该键；返回 (proc, report, root)。"""
        root = self.put_tree(files, cdb=cdb)
        self.put_design_config(rules=() if manual else (key,),
                               manual=(key,) if manual else (), cdb=cdb,
                               extra=extra, root=root)
        self.last_root = root
        p, rep = self.design_report(ctx=f'{key}/{fmt}', keys=(key,),
                                    baseline=baseline, root=root, fmt=fmt)
        return p, rep, root

    # ---- 断言助手（期望全部来自映射 §1/§4，不从输出反推） ----

    def canonical_key(self, key):
        return DESIGN_KEYS.get(key, key)

    def key_check(self, rep, key, ctx):
        key = self.canonical_key(key)
        source_ref = SOURCE_REFS.get(key, key)
        self.assertIsNotNone(rep, f'{ctx}: 期望设计报告，得 None（rc 见 design_report）')
        checks = rep.get('checks')
        self.assertIsInstance(checks, list, f'{ctx}: §4.3 checks[] 缺失')
        rows = [c for c in checks if c.get('key') == key]
        self.assertEqual(len(rows), 1, f'{ctx}: checks[] 里 {key} 应恰一条，得 {rows}')
        row = rows[0]
        self.assertEqual(row.get('source_ref'), source_ref,
                         f'{ctx}: {key} source_ref 应为 {source_ref}')
        self.assertEqual(row.get('class'), CLASS[source_ref],
                         f'{ctx}: {key} class 应为 {CLASS[source_ref]}（§1 判定类）')
        self.assertTrue(row.get('slug'), f'{ctx}: {key} slug 非空（§0.2 可读名）')
        self.assertIs(row.get('enabled'), True, f'{ctx}: {key} 应为启用')
        return row

    def expect_status(self, rep, key, status, ctx):
        row = self.key_check(rep, key, ctx)
        self.assertEqual(row.get('status'), status,
                         f'{ctx}: {key} 应 {status}（§1/§4.5），得 {row}')
        return row

    def findings_for(self, rep, key):
        key = self.canonical_key(key)
        return [f for f in rep.get('findings', []) if f.get('key') == key]

    def one_finding(self, rep, key, ctx):
        rows = self.findings_for(rep, key)
        self.assertEqual(len(rows), 1,
                         f'{ctx}: {key} 应恰一条 finding，得 {len(rows)}: {rows}')
        row = rows[0]
        self.assertEqual(row.get('severity'), 'warn',
                         f'{ctx}: 首版只报告，severity=warn（§4.3）')
        self.assertFalse(row.get('file', '').startswith('/'),
                         f'{ctx}: file 应相对 --root（§4.3）')
        return row

    def expect_facts(self, row, key, ctx):
        facts = row.get('facts')
        self.assertIsInstance(facts, dict, f'{ctx}: facts 缺失（§4.3）')
        for name in FIELDS[key]:
            self.assertIn(name, facts,
                          f'{ctx}: §1 事实字段 {name} 缺失（键集得 {sorted(facts)}）')
        return facts

    def expect_missing_code(self, rep, key, code, ctx):
        key = self.canonical_key(key)
        self.assertIsNotNone(rep, f'{ctx}: 期望设计报告，得 None')
        missing = rep.get('coverage', {}).get('missing_inputs', [])
        self.assertTrue(any(m.get('key') == key and m.get('code') == code
                            for m in missing),
                        f'{ctx}: coverage.missing_inputs 应含 {key}/{code}，得 {missing}')

    def expect_manual_pending(self, rep, key, ctx):
        key = self.canonical_key(key)
        self.assertIsNotNone(rep, f'{ctx}: 期望设计报告，得 None')
        pending = rep.get('coverage', {}).get('manual_pending', [])
        self.assertIn(key, pending, f'{ctx}: coverage.manual_pending 应含 {key}，得 {pending}')
        self.assertFalse(rep.get('coverage', {}).get('complete', True),
                         f'{ctx}: manual_pending 必须 complete=false（§4.3）')

    def assert_contract_ref(self, row, expected, marker, ctx):
        ref = row.get('contract_ref')
        self.assertIsInstance(ref, dict, f'{ctx}: contract_ref 应非空（§4.3 可定/需契约项）')
        self.assertEqual(ref.get('path'), expected['path'], f'{ctx}: contract_ref.path')
        self.assertEqual(ref.get('line'), expected['line'], f'{ctx}: contract_ref.line')
        self.assertEqual(ref.get('sha256'), expected['sha256'],
                         f'{ctx}: contract_ref.sha256 应为 quote 的 SHA-256')
        self.assertIn(marker, ref.get('quote', ''), f'{ctx}: contract_ref.quote')
        self.assertEqual(ref['sha256'], quote_sha(ref['quote']),
                         f'{ctx}: sha256 与 quote 一致（0.5 C 类）')


class DesignGitCase(DesignCase, GitCase):
    """历史项（5.1/5.2/5.3/2.4）：自有临时仓 + --baseline。"""

    def put_repo_tree(self, files, cdb=False):
        return self.put_tree(files, root=self.repo, cdb=cdb)

    def put_repo_config(self, **kw):
        return self.put_design_config(root=self.repo, **kw)

    def design_report(self, ctx='', **kw):
        kw.setdefault('root', self.repo)
        return super().design_report(ctx=ctx, **kw)
