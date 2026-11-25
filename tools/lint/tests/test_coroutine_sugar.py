import unittest

from _support import LintCase, config_text


class CoroutineSugarTest(LintCase):
    def scan_rule(self, text):
        self.put('task.cc', text)
        self.lint_config(config_text(scan=('coroutine-sugar',)))
        return self.scan_json()

    def test_low_level_coroutine_calls_are_reported(self):
        report = self.scan_rule(
            'void task(int fd) {\n'
            '  g_scheduler->RegistCoroutineTask([] {});\n'
            '  detail::Hook_Sleep(1);\n'
            '  co->YieldAndPushGCoQueue();\n'
            '  co->YieldUntilFdReadable(fd);\n'
            '  sync::CoMutex::Create();\n'
            '  pool::CoPool::Create(1);\n'
            '  return detail::MakeAsyncOperation<int>(body);\n'
            '}\n')
        rows = self.findings(report, 'coroutine-sugar')
        self.assertEqual(len(rows), 7, rows)
        self.assertEqual({row['symbol'] for row in rows}, {
            'RegistCoroutineTask', 'Hook_Sleep', 'YieldAndPushGCoQueue',
            'YieldUntilFdReadable', 'CoMutex::Create', 'CoPool::Create',
            'MakeAsyncOperation',
        })

    def test_public_syntax_is_allowed(self):
        report = self.scan_rule(
            'void task() {\n'
            '  bbtco_sleep(1);\n'
            '  bbtco_yield;\n'
            '  auto mutex = bbtco_make_comutex();\n'
            '  bbt_co_await bbt_co_bind(body);\n'
            '  bbt_co_fire bbt_co_bind(body);\n'
            '}\n')
        self.assertEqual(self.findings(report, 'coroutine-sugar'), [])

    def test_same_line_and_next_line_suppression(self):
        report = self.scan_rule(
            'void task(int fd) {\n'
            '  // bbt-lint: ignore-next-line coroutine-sugar -- explicit target Processer\n'
            '  g_scheduler->RegistCoroutineTaskOn(1, [] {});\n'
            '  detail::Hook_Sleep(1); // bbt-lint: ignore coroutine-sugar -- runtime probe\n'
            '  // NOLINTNEXTLINE(coroutine-sugar)\n'
            '  co->YieldUntilFdReadable(fd);\n'
            '}\n')
        self.assertEqual(self.findings(report, 'coroutine-sugar'), [])

    def test_comments_and_strings_are_ignored(self):
        report = self.scan_rule(
            '// g_scheduler->RegistCoroutineTask([] {});\n'
            'const char* text = "Hook_Sleep YieldAndPushGCoQueue";\n')
        self.assertEqual(self.findings(report, 'coroutine-sugar'), [])

    def test_skip_markers_in_literals_do_not_suppress_code(self):
        report = self.scan_rule(
            'const char* text = "NOLINTNEXTLINE(coroutine-sugar)";\n'
            'const char marker = \'N\';\n'
            'const char* raw = R"(bbt-lint: ignore-next-line coroutine-sugar)";\n'
            'detail::Hook_Sleep(1);\n')
        rows = self.findings(report, 'coroutine-sugar')
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]['line'], 4)

    def test_rule_is_opt_in(self):
        self.put('task.cc', 'void task() { detail::Hook_Sleep(1); }\n')
        self.lint_config(config_text(scan=('T501',)))
        report = self.scan_json()
        self.assertEqual(self.findings(report, 'coroutine-sugar'), [])


if __name__ == '__main__':
    unittest.main()
