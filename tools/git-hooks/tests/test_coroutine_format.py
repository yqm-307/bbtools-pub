"""Coroutine macro + complete-lambda rules: real CLI regression in owned temporary repositories.

The formatter must insert one space between a coroutine macro and the capture that follows it,
complete an omitted empty parameter list with `()`, and let the lambda body keep ordinary lambda
layout — non-empty bodies rejoin the head line like `[x]() {`, empty bodies stay compact
`bbtco [](){};`. Real parameters, `mutable` and trailing return types already count as complete:
nothing is inserted. bbtco_ref/bbtco_defer implicit blocks, macro arguments, macro definitions,
string literals, clang-format-off regions and lookalike identifiers are data and must stay
byte-exact; the preprocessing evidence asserts formatting changed whitespace only.

Integration tests use owned local repositories only; never contact a remote service.
"""
import os
from pathlib import Path
import re
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

COMPILER = shutil.which('gcc') or shutil.which('cc')
if not COMPILER:
    raise unittest.SkipTest('need gcc or cc for the preprocessing evidence')
COMPILER = str(COMPILER)

# Preprocessing defines: object-like macros expand like the real coroutine syntax layer, so
# `gcc -E` both lexes every construct and answers stringification. Whitespace inside a
# stringified argument is significant, so corrupting it shows up as different preprocessed text.
DEFINES = '''\
#define STR(x) #x
#define S(x) STR(x)
#define TEXT(x) #x
#define PICK() TEXT
#define bbtco helper() -
#define bbtco_ref bbtco[&]()
#define bbtco_noexcept(succ) helper(succ) +
#define bbtco_desc(desc) helper(desc) -
#define bbtco_defer defer_helper() - [&]()
#define bbtco_yield yield_stmt()
#define bbtco_sleep(ms) sleep_fn(ms)
#define bbtco_ev_r(fd) event_helper(fd) -
#define bbtco_ev_r_with_copool(fd) event_pool_helper(fd) -
#define bbtco_ev_t(ms) timer_helper(ms) -
#define bbtco_wait_for(fd, event, ms) wait_helper(fd, event, ms)
#define bbt_co_return return ReturnHelper{} =
#define bbt_co_return_void return make_ready_void()
#define bbt_co_return_ref(...) return make_ready_ref((__VA_ARGS__))
#define bbt_co_bind bind_operation
#define bbt_co_await await_helper{}->*
#define bbt_co_fire fire_helper{}->*
'''

# Every input is already in base clang-format's canonical shape, so any byte difference the CLI
# produces comes from the coroutine rules alone. `clang-format` joins `bbtco[x]` and splits the
# brace of these statement-shaped uses as if they were function definitions — the regression
# signal is the corrected spacing and the complete lambda head surviving the CLI.
SPACING_INPUT = '''\
void run()
{
    int x = 0, fd = 1;
    bool ok = false;
    bbtco[x]()
    {
        x++;
    };
    bbtco [x]()
    {
        x++;
    };
    bbtco_noexcept(&ok)[x]()
    {
        x++;
    };
    bbtco_noexcept(&ok) [x]()
    {
        x++;
    };
    bbtco_desc("task")[=]()
    {
        x++;
    };
    bbtco_desc("task") [=]()
    {
        x++;
    };
    bbtco_ev_r(fd)[=](int f, short ev)
    {
        x += f + ev;
    };
    bbtco_ev_r(fd) [=](int f, short ev)
    {
        x += f + ev;
    };
    bbtco_ev_t(50)[]()
    {
        x++;
    };
}
'''

# Non-empty coroutine bodies rejoin the head line like ordinary lambdas: `bbtco [x]() {`.
SPACING_FIXED_LINES = (
    '    bbtco [x]() {',
    '    bbtco_noexcept(&ok) [x]() {',
    '    bbtco_desc("task") [=]() {',
    '    bbtco_ev_r(fd) [=](int f, short ev) {',
    '    bbtco_ev_t(50) []() {',
)
# Each corrected shape must appear exactly twice: once fixed, once already correct.
SPACING_FIXED_COUNTS = {
    '    bbtco [x]() {': 2,
    '    bbtco_noexcept(&ok) [x]() {': 2,
    '    bbtco_desc("task") [=]() {': 2,
    '    bbtco_ev_r(fd) [=](int f, short ev) {': 2,
}

# Blocks after bbtco_ref/bbtco_defer keep the brace on the next line: their implicit blocks are
# not lambda completion and are never rewritten. Statement-shaped and function-shaped macro uses
# keep their ordinary form without spacing fixes. The leading blank line mirrors what
# clang-format inserts after the define block, so the input is canonical.
INVARIANT_INPUT = '''\

void run()
{
    int x = 0;
    auto op = bbt_co_bind(f, 1);
    bbtco_ref
    {
        x++;
    };
    bbtco_defer
    {
        x--;
    };
    bbtco_yield;
    bbtco_sleep(10);
    bbtco_wait_for(fd, ev, 100);
    (void)op;
}
'''

# Expression-feeding macros get one space before the expression; `-1` must stay a unary minus
# hugging its operand, not clang-format's binary-looking ` - 1`. The plain forms have no
# parenthesised-expression rewrite: bbt_co_return_ref/bbt_co_bind are function-shaped and stay.
RETURN_INPUT = '''\
bbt_co_async(int) compute()
{
    auto op = bbt_co_bind(f, 1);
    bbt_co_return-1;
}
bbt_co_async(int) other()
{
    auto op = bbt_co_bind(f, 1);
    int v = 1;
    bbt_co_return v + 1;
    bbt_co_return -1;
    bbt_co_await op;
    bbt_co_await(op);
    bbt_co_fire op;
    bbt_co_fire(op);
    bbt_co_return_ref(v);
    bbt_co_return bbt_co_await(op);
}
bbt_co_async_void() finish()
{
    bbt_co_return_void;
}
'''

RETURN_FIXED_LINES = (
    '    bbt_co_await (op);',
    '    bbt_co_fire (op);',
    '    bbt_co_return bbt_co_await (op);',
)
RETURN_FIXED_COUNTS = {
    '    bbt_co_return -1;': 2,  # once fixed from `bbt_co_return-1`, once already correct
}
RETURN_INVARIANT_LINES = (
    '    bbt_co_return v + 1;',
    '    bbt_co_await op;',
    '    bbt_co_fire op;',
    '    bbt_co_return_ref(v);',
    '    bbt_co_return_void;',
)
RETURN_INVARIANT_COUNTS = {
    '    auto op = bbt_co_bind(f, 1);': 2,
}

# Omitted empty parameter lists are completed with `()` after the capture-close bracket, then
# the non-empty brace rejoins the head line. Capture initializers nest brackets — `[y = arr[0]]`
# indexes, `[z = [x]() { ... }]` embeds a lambda — so the insertion point is only found by
# scanning the whole capture; a depth-1 scan would insert inside the initializer. Real
# parameters, `mutable` and trailing return types already count as complete heads: the
# parameter list is never guessed across them, nor across conditional-compilation breaks
# (directives stay data by design). Empty bodies compact to `bbtco [](){};`.
INSERT_INPUT = '''\
void run()
{
    int x = 0, fd = 1;
    bool ok = false;
    int arr[4] = {0, 1, 2, 3};
    bbtco[x]
    {
        x++;
    };
    bbtco[]()
    {
        x++;
    };
    bbtco[]
    {
    };
    bbtco[x]
    {
    };
    bbtco_noexcept(&ok)[x]
    {
        x++;
    };
    bbtco_noexcept(&ok)[x]()
    {
        x++;
    };
    bbtco_ev_r_with_copool(fd)[=]
    {
        x++;
    };
    bbtco[y = arr[0]]
    {
        x += y;
    };
    bbtco[y = arr[0]]()
    {
        x += y;
    };
    bbtco[z = [x]() {
        return x;
    }]
    {
        x += z();
    };
    bbtco[z = [x]() {
        return x;
    }]()
    {
        x += z();
    };
    bbtco[x] mutable
    {
        x++;
    };
    bbtco[x] mutable->int
    {
        return x;
    };
    bbtco[x]->int
    {
        return x;
    };
    bbtco[x](int a)
    {
        x += a;
    };
}
'''

INSERT_FIXED_LINES = (
    '    bbtco [x]() {',
    '    bbtco []() {',
    '    bbtco [](){};',
    '    bbtco [x](){};',
    '    bbtco_noexcept(&ok) [x]() {',
    '    bbtco_ev_r_with_copool(fd) [=]() {',
    '    bbtco [y = arr[0]]() {',
    '    bbtco [x] mutable {',
    '    bbtco [x] mutable -> int {',
    '    bbtco [x] -> int {',
    '    bbtco [x](int a) {',
)
INSERT_FIXED_COUNTS = {
    '    bbtco_noexcept(&ok) [x]() {': 2,  # inserted once, already complete once
    '    bbtco [y = arr[0]]() {': 2,
}
# The nested-lambda capture line and its capture-close line each appear twice (inserted once,
# already complete once); `()` belongs after the outer capture-close bracket.
INSERT_NESTED_LAMBDA_COUNTS = {
    '    bbtco [z = [x]() {': 2,
    '    }]() {': 2,
}
INSERT_ABSENT_FRAGMENTS = (
    'bbtco [x]() mutable',  # () must not be inserted before an existing mutable
    'bbtco [x]() -> int',  # nor before a trailing return type, spaced or tight
    'bbtco [x]()->int',
    'arr[0]()',  # completion inside the capture initializer instead of after its close
    'arr[0]]()()',  # a single completion, never doubled
    '[x]()()',  # never inside the nested lambda either
)

# C++17 alternative tokens: `<:` opens the arr subscript inside the capture initializer, so the
# plain `]` closing it must not be mistaken for the capture-close; completion belongs after the
# final `]`. Regression for an insertion that once fired inside this capture.
DIGRAPH_INPUT = '''\
void run()
{
    int x = 0;
    int arr[4] = {0, 1, 2, 3};
    bbtco[x = arr<:0] - 1]
    {
        (void)x;
    };
    bbtco[x = arr<:0] - 1]()
    {
        (void)x;
    };
    bbtco[x = arr[0] - 1]
    {
        (void)x;
    };
}
'''

DIGRAPH_FIXED_COUNTS = {
    '    bbtco [x = arr<:0] - 1]() {': 2,  # inserted once, already complete once
    '    bbtco [x = arr[0] - 1]() {': 1,
}
DIGRAPH_ABSENT_FRAGMENTS = (
    'arr<:0] - 1]()()',  # never doubled
    'arr<:0]() - 1]',  # never inside the capture
)

# The capture may open on the line after the macro: the missing space is one blank regardless of
# which line break held it, then the empty parameter list is completed. Regression for
# `bbtco\n[]{work();};`, which once stayed flush against the macro. The body then lays out like
# any ordinary statement-position lambda: non-empty bodies rejoin the head line and split.
NEWLINE_INPUT = '''\
void work();
void run()
{
    bbtco
    [](){work();};
    bbtco
    []() {
        work();
    };
}
'''

NEWLINE_FIXED_COUNTS = {
    '    bbtco []() {': 2,
    '        work();': 2,
}

# Text inside real macro arguments (the noexcept bool expression, comments), a lookalike
# lowercase identifier, the clang-format-off region, macro definitions and string literals are
# all data: byte-exact after formatting, including their original spacing. A nested coroutine
# statement in the lambda body is ordinary code and gets the standard completion like any other;
# the lookalike bbtco2 must gain neither the space, nor `()`, nor the rejoined brace.
BOUNDARY_INPUT = '''\
const char* msg = "bbtco[x]; bbtco_noexcept(&ok)[=]()";
void run()
{
    int x = 0;
    bool ok = false;
    bbtco_noexcept(&ok /* tagged */)[x]()
    {
        x++;
    };
    bbtco_noexcept(&ok)[x]()
    {
        bbtco[x]()
        {
            x++;
        };
    };
    bbtco2[x]()
    {
        x++;
    };
    // clang-format off
    bbtco[x](){x++;};
    // clang-format on
}
'''

BOUNDARY_PRESERVED_LINES = (
    '#define bbtco helper() -',
    '#define bbtco_noexcept(succ) helper(succ) +',
    'const char* msg = "bbtco[x]; bbtco_noexcept(&ok)[=]()";',
    '    bbtco_noexcept(&ok /* tagged */) [x]() {',
    '        bbtco [x]() {',
    '    bbtco2[x]()',
    '    bbtco[x](){x++;};',
)

# Stringification captures the argument's original whitespace: S(bbtco[&]) stringifies the
# argument before the outer bbtco expands, and PICK()(bbtco[x] {}) stringifies through one
# indirection — the indirect form is where whitespace corruption actually bites, since the
# capture and brace inside the argument are data in both cases. The same shield must stop `()`
# completion inside these arguments: `bbtco[x] {}` and `bbtco[x]() {}` are byte-exact data, and
# inserting `()` there would corrupt the string literal. The preprocessed string literals are
# asserted byte-exact below.
STRINGIFY_INPUT = '''\
int use(const char* s, int v);
void run()
{
    int x = 0;
    use(S(bbtco[&]), 0);
    use(S(bbtco[x] {}), 0);
    use(PICK()(bbtco[x] {}), 0);
    use(PICK()(bbtco[x]() {}), 0);
    bbtco[x]()
    {
        x++;
    };
    bbt_co_return-1;
}
'''

STRINGIFY_PRESERVED_LINES = (
    '    use(S(bbtco[&]), 0);',
    '    use(S(bbtco[x] {}), 0);',
    '    use(PICK()(bbtco[x] {}), 0);',
    '    use(PICK()(bbtco[x]() {}), 0);',
)
STRINGIFY_FIXED_LINES = (
    '    bbtco [x]() {',
    '    bbt_co_return -1;',
)
STRINGIFY_MARKERS = (
    '"helper() -[&]"',
    '"bbtco[x] {}"',
    '"bbtco[x]() {}"',
)


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[A-Za-z_]\w*|\d+(?:\.\d+)?|\S')


def preprocess(path):
    result = subprocess.run([COMPILER, '-E', '-P', str(path)], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise AssertionError(f'preprocessing failed: {result.stderr}')
    return result.stdout

def lex_tokens(path):
    """Token stream of the preprocessed translation unit, whitespace-normalized but string-exact.

    `gcc -E` emits text, not tokens, and its whitespace is arbitrary: stringification makes
    whitespace inside literals significant in the output itself, so literals are atomic tokens
    compared byte-exact, while other runs only need token identity. A whitespace-only format
    pass must leave the whole stream intact.
    """
    return _TOKEN.findall(preprocess(path))


class CoroutineFormatTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='bbt-coroutine-format-')
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

    def put_and_format(self, name, input_text):
        self.put(name, DEFINES + input_text)
        self.git('add', name)
        self.format_cpp('--all')
        return (self.repo / name).read_text()

    def assert_lines(self, output, lines, counts=None):
        for line in lines:
            occurrences = output.count(line + '\n')
            wanted = (counts or {}).get(line, 1)
            self.assertEqual(occurrences, wanted, f'{line!r}: {occurrences} occurrences, want {wanted}\n{output}')

    def assert_stable(self, name):
        first = (self.repo / name).read_text()
        p = self.format_cpp('--all')
        self.assertEqual((self.repo / name).read_text(), first, 'second run changed the output')
        self.assertIn('0 updated', p.stdout + p.stderr)

    def test_cli_fixes_default_coroutine_spacing_and_is_stable(self):
        output = self.put_and_format('spacing.cc', SPACING_INPUT)
        self.assert_lines(output, SPACING_FIXED_LINES, SPACING_FIXED_COUNTS)
        self.assert_stable('spacing.cc')

    def test_cli_check_accepts_fixed_coroutine_spacing(self):
        output = self.put_and_format('spacing.cc', SPACING_INPUT)
        self.git('add', 'spacing.cc')
        p = self.format_cpp('--check', '--all')
        self.assertIn('Format OK', p.stdout + p.stderr)

    def test_cli_statement_and_block_macros_keep_ordinary_shape(self):
        output = self.put_and_format('invariant.cc', INVARIANT_INPUT)
        self.assertEqual(output, DEFINES + INVARIANT_INPUT,
                         'ordinary coroutine shapes must be byte-exact stable')

    def test_cli_fixes_expression_spacing_and_preserves_unary_minus(self):
        output = self.put_and_format('return.cc', RETURN_INPUT)
        self.assert_lines(output, RETURN_FIXED_LINES + tuple(RETURN_FIXED_COUNTS), RETURN_FIXED_COUNTS)
        self.assert_lines(output, RETURN_INVARIANT_LINES + tuple(RETURN_INVARIANT_COUNTS), RETURN_INVARIANT_COUNTS)
        self.assertNotIn('bbt_co_return - 1', output, 'unary minus must hug its operand')
        self.assert_stable('return.cc')

    def test_cli_completes_omitted_parameter_lists_and_is_stable(self):
        output = self.put_and_format('insert.cc', INSERT_INPUT)
        self.assert_lines(output, INSERT_FIXED_LINES, INSERT_FIXED_COUNTS)
        self.assert_lines(output, tuple(INSERT_NESTED_LAMBDA_COUNTS), INSERT_NESTED_LAMBDA_COUNTS)
        for fragment in INSERT_ABSENT_FRAGMENTS:
            self.assertNotIn(fragment, output, f'unwanted completion artifact {fragment!r}\n{output}')
        self.assert_stable('insert.cc')

    def test_cli_digraph_subscript_inside_capture_does_not_close_it(self):
        output = self.put_and_format('digraph.cc', DIGRAPH_INPUT)
        self.assert_lines(output, tuple(DIGRAPH_FIXED_COUNTS), DIGRAPH_FIXED_COUNTS)
        for fragment in DIGRAPH_ABSENT_FRAGMENTS:
            self.assertNotIn(fragment, output, f'unwanted completion artifact {fragment!r}\n{output}')
        self.assert_stable('digraph.cc')

    def test_cli_capture_on_next_line_still_gets_its_space(self):
        output = self.put_and_format('newline.cc', NEWLINE_INPUT)
        self.assert_lines(output, tuple(NEWLINE_FIXED_COUNTS), NEWLINE_FIXED_COUNTS)
        self.assertNotIn('bbtco\n', output, 'the capture must rejoin the macro line')
        self.assert_stable('newline.cc')

    def test_cli_boundary_data_stays_byte_exact(self):
        output = self.put_and_format('boundary.cc', BOUNDARY_INPUT)
        self.assert_lines(output, BOUNDARY_PRESERVED_LINES)

    def test_cli_stringification_arguments_and_preprocessing_are_preserved(self):
        output = self.put_and_format('stringify.cc', STRINGIFY_INPUT)
        self.assert_lines(output, STRINGIFY_PRESERVED_LINES)
        self.assert_lines(output, STRINGIFY_FIXED_LINES)
        raw = self.repo / 'raw.cc'
        raw.write_text(DEFINES + STRINGIFY_INPUT)
        formatted_text, raw_text = preprocess(self.repo / 'stringify.cc'), preprocess(raw)
        # Stringification answers are data: the indirect PICK()(...) literals must be byte-exact
        # identical before and after formatting, not just token-identical. `()` completion inside
        # a protected argument would rewrite these literals.
        for marker in STRINGIFY_MARKERS:
            self.assertIn(marker, formatted_text, f'stringified {marker} missing or rewritten:\n{formatted_text}')
            self.assertIn(marker, raw_text)
        self.assertEqual(lex_tokens(self.repo / 'stringify.cc'), lex_tokens(raw),
                         'formatting must be whitespace-only: preprocessed token streams differ')


if __name__ == '__main__':
    unittest.main()
