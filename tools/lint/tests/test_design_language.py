"""设计模式中英文输出契约（``--design --lang zh|en``）。

契约要点：
- 缺省 ``--lang`` 输出与原英文逐字节一致（不新增参数 = 行为不变）；
- zh 只改 ``findings[].message``，text 保留告警行的机器状态、规则键和计数标签，
  JSON 的其他字段、顺序、证据与退出码不变；zh 消息允许内嵌符号名；
- 普通模式显式 ``--lang`` 拒绝；非法语言拒绝（exit 2）。

断言只锁定 CJK/符号名与逐字段一致，不锁定中文具体措辞。
"""
import json
import re
import sys
import unittest
from pathlib import Path

from _support import lint_entry
from design_fixtures import DesignCase

BAD_64 = {'a.h': '/* 数量。 */\nint limit{0};\n'}          # 6.4 复用既有 T202 形状
KEY64 = 'design.comment-restates-code'
CJK = re.compile(r'[一-鿿]')


LINE = re.compile(r'^(\S+):(\d+) (\S+) (\w+) (\S+) (.+)$')


def match_line(line):
    m = LINE.match(line)
    if m is None:
        raise AssertionError(f'文本行五段式不变，得 {line!r}')
    return m


class DesignLangCase(DesignCase):
    def setUp(self):
        super().setUp()
        self.put_tree(BAD_64)
        self.put_design_config(rules=('6.4',))

    def run_lang(self, lang=None, design=True, fmt='json', extra_keys=()):
        args = [sys.executable, '-I', str(lint_entry(self.tools)),
                '--root', str(self.root),
                '--config', str(self.root / '.config/lint.toml'),
                '--format', fmt]
        if design:
            args.append('--design')
        if lang is not None:
            args += ['--lang', lang]
        for key in extra_keys:
            args += ['--check', key]
        return self.run_cmd(*args)

    def json_finding(self, lang):
        p = self.run_lang(lang)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout), p

    def strip_messages(self, rep):
        """去掉 message 后的报告副本：语言无关部分必须逐字节一致。"""
        copy = json.loads(json.dumps(rep))
        for row in copy['findings']:
            row.pop('message', None)
        return copy


class DesignLangZh(DesignLangCase):
    def test_zh_message_cjk_and_rest_invariant(self):
        """zh：message 含 CJK，报告其余字段/顺序/证据与默认英文一致。"""
        rep_default, _ = self.json_finding(None)
        rep_zh, _ = self.json_finding('zh')
        rows = [f for f in rep_zh['findings'] if f['key'] == KEY64]
        self.assertEqual(len(rows), 1, f'zh 下 6.4 应恰一条 finding: {rows}')
        row = rows[0]
        msg = row.get('message', '')
        self.assertRegex(msg, CJK, f'zh message 应含中文，得 {msg!r}')
        default_row = [f for f in rep_default['findings'] if f['key'] == KEY64][0]
        self.assertNotRegex(default_row.get('message', ''), CJK,
                            '默认（英文）message 不应含 CJK')
        self.assertEqual(self.strip_messages(rep_zh),
                         self.strip_messages(rep_default),
                         '除 findings[].message 外 JSON 逐字段一致（顺序、证据、计数）')
        self.assertEqual(list(rep_zh.keys()), list(rep_default.keys()),
                         '顶层键顺序一致')

    def test_en_explicit_matches_default(self):
        """显式 --lang en 与省略参数逐字节一致。"""
        p_default = self.run_lang(None)
        p_en = self.run_lang('en')
        self.assertEqual(p_default.returncode, p_en.returncode)
        self.assertEqual(p_default.stdout, p_en.stdout,
                         'en 显式 = 缺省英文（字节一致）')

    def test_zh_text_output_language(self):
        """text：zh 告警行 message 段含 CJK，汇总/缺输入标签同语言；英文无 CJK。"""
        p_zh = self.run_lang('zh', fmt='text')
        self.assertEqual(p_zh.returncode, 0, p_zh.stderr)
        self.assertRegex(p_zh.stdout, CJK, 'zh text 输出应含中文')
        p_en = self.run_lang(None, fmt='text')
        self.assertEqual(p_en.returncode, 0, p_en.stderr)
        rows_zh = [l for l in p_zh.stdout.splitlines() if l.strip()]
        rows_en = [l for l in p_en.stdout.splitlines() if l.strip()]
        self.assertTrue(rows_zh and rows_en, '两种语言 text 输出均非空')
        for rows in (rows_zh, rows_en):
            match = match_line(rows[0])
            self.assertEqual(match.group(3), KEY64, 'key 不随语言变化')
            self.assertEqual(match.group(4).lower(), 'candidate', '状态标签不随语言变化')
        self.assertRegex(match_line(rows_zh[0]).group(6), CJK,
                         'zh 告警 message 段含中文')
        self.assertNotRegex(match_line(rows_en[0]).group(6), CJK,
                            '英文告警 message 段无 CJK')


class DesignLangRejected(DesignLangCase):
    def test_lang_rejected_without_design(self):
        """普通模式显式 --lang → 拒绝 exit 2。"""
        p = self.run_lang('zh', design=False)
        self.assertEqual(p.returncode, 2, f'普通模式 --lang 应拒绝，rc={p.returncode}')
        self.assertTrue(p.stderr.strip(), 'stderr 说明 --lang 需要 --design')

    def test_invalid_lang_rejected(self):
        """非法语言值 → 拒绝 exit 2。"""
        for bad in ('fr', 'cn', 'ZH'):
            p = self.run_lang(bad)
            self.assertEqual(p.returncode, 2,
                             f'--lang {bad!r} 应拒绝，rc={p.returncode}')
            self.assertTrue(p.stderr.strip(), f'--lang {bad!r} 须有 stderr 说明')


if __name__ == '__main__':
    unittest.main()
