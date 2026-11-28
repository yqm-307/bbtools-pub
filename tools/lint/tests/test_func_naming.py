"""func-naming 回归：按契约与 README「C++ 候选规则」设计的行为断言。

契约要点：`动词_对象[_限定]`（by/for/from/to/with/in）、简单词替换、不口语、
一般 2~5 词、超过 6 词报；豁免构造/析构、运算符（含 operator bool 等转换运算符）、
main、全大写测试宏、override 覆写与标准库兼容接口名（比较不分大小写）。
r2 判定补充的放行：单词惯用名（只在单词名生效）、As/From/To 转换、读写锁 r/w 前缀
（按后续动词判断）、表外简单动词；首词在替换表时只报 complex-word 不重复报。
提取侧：行号落在函数名所在行；宏作返回类型、嵌套类构造、初始化列表成员、
函数指针成员、alignas 不是函数名。断言只绑命中函数名、行号与类别关键词，不绑完整消息。
"""
import unittest

from _support import LintCase, config_text


def messages_for(rows, symbol):
    """同一函数名的全部命中消息（一个名字可因多类问题报多行）。"""
    return [row['message'] for row in rows if row['symbol'] == symbol]


class FuncNamingTest(LintCase):
    def scan_rule(self, files, extra=''):
        for name, text in files.items():
            self.put(name, text)
        self.lint_config(config_text(scan=('func-naming',), extra=extra))
        return self.scan_json()

    # —— 合规名不报 ——

    def test_compliant_snake_and_pascal_names_not_reported(self):
        text = (
            'int get_order_info_by_id(int id);\n'             # 契约示例：动词_对象_by_条件
            'int GetOrderInfoById(int id);\n'                 # PascalCase 同构
            'int get_reward_by_rank_idx(int rank);\n'         # 契约示例：中式英语直译
            'void on_update();\n'                             # 回调 on_<事件>
            'void OnUpdate();\n'
            'bool is_valid();\n'
            'bool has_next();\n'
            'bool can_handle(int type);\n'
            'void do_sign_in();\n'
            'void HandleRequest();\n'
            'int calc_reward_by_rank_idx(int rank) { return rank; }\n'  # 带定义体
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual(rows, [])

    # —— 四类检查 ——

    def test_non_verb_first_word_reported(self):
        text = (
            'void OrderInfo();\n'            # 名词开头
            'void ServerClose(int fd);\n'    # 对象开头
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual({row['symbol'] for row in rows}, {'OrderInfo', 'ServerClose'})
        self.assertEqual(len(rows), 2, rows)
        for row in rows:
            self.assertIn('first-word', row['message'])

    def test_complex_word_reports_simple_replacement(self):
        text = (
            'void LoadAndValidateConfig();\n'   # 首词合规，validate 是契约复杂词
            'void SendAndReceive(int fd);\n'    # 首词合规，receive 是契约复杂词
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual(len(rows), 2, rows)
        load = messages_for(rows, 'LoadAndValidateConfig')
        self.assertEqual(len(load), 1, load)
        self.assertIn('complex-word', load[0])
        self.assertIn('check', load[0])    # 契约替换表：validate→check
        send = messages_for(rows, 'SendAndReceive')
        self.assertEqual(len(send), 1, send)
        self.assertIn('complex-word', send[0])
        self.assertIn('recv', send[0])     # 契约替换表：receive→recv

    def test_complex_head_reports_complex_word_only(self):
        """首词本身是契约复杂词时只报 complex-word 一条（complex-dup：首词不重复报）。"""
        text = (
            'void retrieve_user(int uid);\n'   # retrieve→get/query
            'void Validate(int v);\n'          # validate→check
            'void NormalizeU32(int v);\n'      # normalize→adjust
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual({row['symbol'] for row in rows},
                         {'retrieve_user', 'Validate', 'NormalizeU32'}, rows)
        for symbol, replacement in (('retrieve_user', 'get'), ('Validate', 'check'),
                                    ('NormalizeU32', 'adjust')):
            msgs = messages_for(rows, symbol)
            self.assertEqual(len(msgs), 1, msgs)          # 一名只一条，无 first-word 重复
            self.assertIn('complex-word', msgs[0])
            self.assertIn(replacement, msgs[0])           # 契约替换表给出去处
            self.assertNotIn('first-word', msgs[0])

    def test_slang_word_reported(self):
        text = (
            'void grab_item(int id);\n'   # 口语词 grab
            'void load_thing();\n'        # 占位词 thing；首词合规，单独验证 slang 类
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual({row['symbol'] for row in rows}, {'grab_item', 'load_thing'})
        thing = messages_for(rows, 'load_thing')
        self.assertEqual(len(thing), 1, thing)
        self.assertIn('slang-word', thing[0])
        self.assertIn('thing', thing[0])
        self.assertTrue(any('slang-word' in m for m in messages_for(rows, 'grab_item')), rows)

    def test_word_limit_boundary_default(self):
        text = (
            'int get_wx_account_info_by_userid(int uid);\n'        # 契约示例，6 词正好在限
            'int load_user_wx_account_info_by_userid(int uid);\n'  # 7 词超限
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual([row['symbol'] for row in rows],
                         ['load_user_wx_account_info_by_userid'], rows)
        self.assertIn('too-many-words', rows[0]['message'])

    def test_max_words_option_raises_limit(self):
        text = (
            'int load_user_wx_account_info_by_userid(int uid);\n'
            'int load_user_wx_account_info_by_userid_and_ts(int uid);\n'  # 9 词
        )
        extra = '[rules.func-naming]\noptions = { max_words = 8 }\n'
        rows = self.findings(self.scan_rule({'a.cc': text}, extra), 'func-naming')
        self.assertEqual([row['symbol'] for row in rows],
                         ['load_user_wx_account_info_by_userid_and_ts'], rows)
        self.assertIn('too-many-words', rows[0]['message'])

    # —— r2 判定放行：单词惯用名 / 转换 / 读写锁前缀 ——

    def test_single_idiom_names_not_reported(self):
        """单词惯用名（驼峰与小写）不报；单词非惯用名词与多词名照报。

        判定 single-idiom 只在名字只有一个词时生效：Size 放行，SizeOfQueue
        仍按首词 size 检查；Info/Storage 这类不明显的名词判 violation。
        """
        header = (
            'class Queue {\n'
            'public:\n'
            '  int Size() const;\n'
            '  int Count() const;\n'
            '  void Close();\n'
            '  bool Empty() const;\n'
            '  int size() const;\n'
            '  int count() const;\n'
            '  void close();\n'
            '  bool empty() const;\n'
            '  int SizeOfQueue() const;\n'   # 多词名不受单词惯用名豁免
            '};\n'
        )
        impl = (
            'void Info();\n'      # 单词但看不出行为：照报
            'void Storage();\n'
        )
        rows = self.findings(self.scan_rule({'a.h': header, 'a.cc': impl}), 'func-naming')
        self.assertEqual({(row['file'], row['symbol']) for row in rows},
                         {('a.cc', 'Info'), ('a.cc', 'Storage'), ('a.h', 'SizeOfQueue')}, rows)
        for row in rows:
            self.assertIn('first-word', row['message'])

    def test_conversion_prefix_names_not_reported(self):
        """As/From/To 开头的转换函数是惯用法，不报首词。"""
        text = (
            'int AsInt64();\n'
            'Config FromJson(const std::string& s);\n'
            'std::string ToJson(int value);\n'
            'class Message {\npublic:\n  const char* AsString() const;\n};\n'
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual(rows, [])

    def test_rw_lock_prefix_names_not_reported(self):
        """读写锁 r/w 单字母前缀（可叠 un）按后续动词判断：lock 是动词即放行，
        前缀不是万能豁免（RFoo 仍报）。"""
        text = (
            'class Lockable {\n'
            'public:\n'
            '  void RLock();\n'
            '  void WLock();\n'
            '  void RUnLock();\n'
            '  void WUnLock();\n'
            '  void RServer();\n'  # 前缀剥掉后 server 是普通名词，不是动词
            '};\n'
        )
        rows = self.findings(self.scan_rule({'a.h': text}), 'func-naming')
        self.assertEqual([(row['line'], row['symbol']) for row in rows], [(7, 'RServer')], rows)
        self.assertIn('first-word', rows[0]['message'])

    # —— 行号与提取 ——

    def test_line_numbers_land_on_function_name_line(self):
        """报告行号落在函数名所在行，而不是声明段起点（上方有多行注释时）。"""
        impl = (
            '/*\n'
            ' * Rotate the ring buffer\n'
            ' * before overwriting.\n'
            ' */\n'
            'void OrderInfo();\n'            # 自由函数：第 5 行
        )
        header = (
            'class Ring {\n'
            'public:\n'
            '  /* Ring keeps\n'
            '     the last N\n'
            '     entries. */\n'
            '  void ServerClose(int fd);\n'  # 类成员 + 多行块注释：第 6 行
            '\n'
            '  // Plain comment lines\n'
            '  // above the next member.\n'
            '  void MainTaskDone();\n'       # 类成员 + 行注释：第 10 行
            '};\n'
        )
        rows = self.findings(self.scan_rule({'a.cc': impl, 'a.h': header}), 'func-naming')
        self.assertEqual({(row['file'], row['line'], row['symbol']) for row in rows},
                         {('a.cc', 5, 'OrderInfo'),
                          ('a.h', 6, 'ServerClose'),
                          ('a.h', 10, 'MainTaskDone')}, rows)

    def test_macro_return_type_checks_real_name(self):
        """宏当返回类型 `MACRO(args) Name(params)` 检查的是 Name，不是宏名。"""
        text = (
            'bbt_co_async(int) Fetch(int value);\n'                             # 真名是复杂词
            'bbt_co_async_body(result<void>) CoWaitShutdownRequestBody(int w);\n'  # 真名首词违规
            'bbt_co_async(R)\n'
            '    Session::Regist(int id);\n'                                    # 多行形态，取类成员真名
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual({(row['line'], row['symbol']) for row in rows},
                         {(1, 'Fetch'), (2, 'CoWaitShutdownRequestBody'), (4, 'Regist')}, rows)
        self.assertNotIn('bbt_co_async', {row['symbol'] for row in rows}, rows)
        self.assertIn('complex-word', messages_for(rows, 'Fetch')[0])
        self.assertIn('first-word', messages_for(rows, 'Regist')[0])

    def test_operator_overloads_and_conversions_not_reported(self):
        """运算符重载与转换运算符（operator bool 等）整体豁免。"""
        text = (
            'class Lockable {\n'
            'public:\n'
            '  operator bool() const noexcept;\n'                 # 转换运算符
            '  bool operator==(const Lockable& other) const;\n'
            '};\n'
            'void* operator new(unsigned long n);\n'
            'void operator delete(void* p) noexcept;\n'
        )
        rows = self.findings(self.scan_rule({'a.h': text}), 'func-naming')
        self.assertEqual(rows, [])

    def test_extraction_misfires_not_reported(self):
        """提取到的不是函数名的形状不报：嵌套类构造、`= delete` 复制构造、
        初始化列表成员、函数指针成员、alignas 成员。"""
        header = (
            'struct Client::State {\n'
            '  State(int client, int opts)\n'
            '      : http(client)\n'
            '      , options(opts)\n'
            '  {\n'
            '  }\n'
            '};\n'
            'class X {\n'
            'public:\n'
            '  X(const X&) = delete;\n'
            '  X& operator=(const X&) = delete;\n'
            '};\n'
            'class Pipe {\n'
            '  void (*m_old_pipe)(int);\n'      # 函数指针成员，词法取到的是 void
            '};\n'
            'struct V {\n'
            '  static const int kInlineSize = 8;\n'
            '  alignas(int) unsigned char m_buf[kInlineSize];\n'
            '};\n'
        )
        impl = (
            'Coroutine::Coroutine(int stack)\n'
            '    : m_ctx(stack)\n'
            '    , m_id(GenCoroutineId())\n'
            '{\n'
            '}\n'
        )
        rows = self.findings(self.scan_rule({'a.h': header, 'a.cc': impl}), 'func-naming')
        self.assertEqual(rows, [])

    def test_ctor_heuristic_does_not_suppress_real_functions(self):
        """构造判定不误伤：嵌套类里的普通方法照报；带返回类型的函数不被当成构造。"""
        text = (
            'struct Outer::Inner {\n'
            '  void OrderThings();\n'   # 嵌套类普通方法，名词开头照报
            '};\n'
            'int& GetRef();\n'          # 有返回类型（引用），不是构造
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual([(row['line'], row['symbol']) for row in rows], [(2, 'OrderThings')], rows)
        self.assertIn('first-word', rows[0]['message'])

    # —— keep：真违规仍报 ——

    def test_keep_names_still_reported(self):
        """判定为 keep 的典型名仍报：名词开头的多词名、拼错的动词。"""
        text = (
            'void SessionOwnerSeal();\n'   # 名词开头多词名
            'void MainTaskDone();\n'
            'void Regist(int id);\n'       # 拼错（register），不给放行
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual({(row['line'], row['symbol']) for row in rows},
                         {(1, 'SessionOwnerSeal'), (2, 'MainTaskDone'), (3, 'Regist')}, rows)
        for row in rows:
            self.assertIn('first-word', row['message'])

    # —— 豁免 ——

    def test_member_exemptions_not_reported(self):
        text = (
            'class Cache {\n'
            'public:\n'
            '  Cache();\n'
            '  ~Cache();\n'
            '  bool operator==(const Cache& other) const;\n'
            '  void begin();\n'
            '  int size() const;\n'
            '  void debug_dump() override;\n'  # debug 非动词，靠 override 豁免才不报
            '};\n'
        )
        rows = self.findings(self.scan_rule({'a.h': text}), 'func-naming')
        self.assertEqual(rows, [])

    def test_free_function_exemptions_not_reported(self):
        text = (
            'int main(int argc, char** argv) { return 0; }\n'
            'TEST(CacheSuite, HandlesEmpty) { ASSERT_EQ(1, 1); }\n'
        )
        rows = self.findings(self.scan_rule({'a.cc': text}), 'func-naming')
        self.assertEqual(rows, [])

    def test_out_of_class_definition_checked(self):
        header = 'class Parser {\npublic:\n  void Reset();\n};\n'
        impl = 'void Parser::OrderElements() {}\n'
        rows = self.findings(self.scan_rule({'a.h': header, 'a.cc': impl}), 'func-naming')
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]['symbol'], 'OrderElements')
        self.assertIn('first-word', rows[0]['message'])

    # —— 选项与抑制 ——

    def test_exclude_symbol_suppression(self):
        """[[exclude]] 按 symbol 抑制：已发布公开 API 不为风格改名。"""
        text = 'void OrderInfo();\nvoid ServerClose(int fd);\n'
        extra = ('[[exclude]]\nrule = "func-naming"\npath = "*"\nsymbol = "Order*"\n'
                 'reason = "published API"\n')
        report = self.scan_rule({'a.cc': text}, extra)
        rows = self.findings(report, 'func-naming')
        self.assertEqual([row['symbol'] for row in rows], ['ServerClose'], rows)
        self.assertEqual(report['coverage']['suppressed'], {'func-naming': 1})

    def test_exclude_readme_test_dir_example_takes_effect(self):
        """README 的测试目录 [[exclude]] 示例生效：path = "tests/**" + symbol = "*"
        抑制测试目录全部命名命中，同符号在测试目录外照报。"""
        text = 'void OrderInfo();\nvoid ServerClose(int fd);\n'
        extra = ('[[exclude]]\nrule = "func-naming"\npath = "tests/**"\nsymbol = "*"\n'
                 'reason = "测试用例名按场景描述，不按动词+对象约束"\n')
        report = self.scan_rule({'tests/test_cache.cc': text, 'src/a.cc': text}, extra)
        rows = self.findings(report, 'func-naming')
        self.assertEqual({(row['file'], row['symbol']) for row in rows},
                         {('src/a.cc', 'OrderInfo'), ('src/a.cc', 'ServerClose')}, rows)
        self.assertEqual(report['coverage']['suppressed'], {'func-naming': 2})

    def test_rule_is_opt_in(self):
        self.put('a.cc', 'void OrderInfo();\n')
        self.lint_config(config_text(scan=('T501',)))
        report = self.scan_json()
        self.assertEqual(self.findings(report, 'func-naming'), [])


if __name__ == '__main__':
    unittest.main()
