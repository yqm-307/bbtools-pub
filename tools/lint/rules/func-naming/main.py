"""Function-naming review candidates: verb-first, simple words, no slang, bounded length."""
import re

# 语义约定（动词含义、结构、审查清单）见 third-party/bbt-agent-toolkit/standards/general/naming.md
# 「函数命名」一节；本文件只持有扫描用机器数据：允许词表、替换表、口语词表、豁免名单。

# 契约核心动词表全部收录（get/query/find/load/calc/check/is/has/can/set/add/del/update/save/
# reset/clear/do/handle/send/recv/notify/init/start/stop/create/destroy/open/close/on）。
# 其余只收简单常见的动词；领域惯用语 acquire/release、verify/encrypt 按契约例外保留。
# 非动词、生僻词不进表，命中照报人工复核。
ALLOWED = frozenset('''
on is has can do
get query find load calc check set add del update save reset clear handle send recv notify
init start stop create destroy open close
try make build parse pack unpack encode decode encrypt decrypt read write push pop insert erase remove
release alloc free allocate deallocate bind connect accept listen run wait lock unlock post dispatch sync apply
enable disable begin end commit cancel merge split sort filter fill copy swap move convert to format dump
print log report verify gen use call emit trigger fire refresh flush reload resolve select pick register unregister
process exec schedule yield resume wake acquire inc dec sub reg unreg should need sum count match wrap attach
detach mark fix scan enter exit pause poll sleep
enqueue defer publish complete finish fail append consume record drain install uninstall forward ping seal revoke
take give submit reserve borrow hold grant prepare probe settle retire admit scale arm await
as from
abandon abort accumulate activate adopt allows arrive authorize block break capture checkout checkpoint claim
classify cleanup compile compose configure confirm delay deliver dequeue deregister dial discard dismiss dispose
drop ensure evict exchange exercise expire feed finalize fits force forget freeze gather include inject interrupt
join keep kick kill leave limit list lookup loop map note occupy override owns peek preload preserve provide pump
put reap reclaim reject replace request requeue require restore restrict retry rollback sample search serialize
serve setup shutdown signal spawn steal store sweep teardown throw track unbind untrack
'''.split())

# 复杂词 → 简单替换（契约「简单词替换」表）；acquire/release、verify/encrypt 属领域惯用语，不进表。
REPLACE = {
    'retrieve': 'get/query', 'obtain': 'get/query', 'fetch': 'get/query',
    'compute': 'calc', 'calculate': 'calc',
    'determine': 'check', 'validate': 'check', 'examine': 'check', 'inspect': 'check',
    'initialize': 'init', 'initialise': 'init',
    'terminate': 'stop',
    'instantiate': 'create', 'construct': 'create',
    'eliminate': 'del', 'delete': 'del',
    'modify': 'set/update', 'alter': 'set/update',
    'utilize': 'use', 'utilise': 'use',
    'invoke': 'call',
    'generate': 'gen/make',
    'persist': 'save',
    'transmit': 'send',
    'receive': 'recv',
    'populate': 'fill',
    'increment': 'inc/add', 'decrement': 'dec/sub',
    'normalize': 'adjust',
}

SLANG = frozenset('grab gimme nuke yank poke bump stuff thing magic hack misc foo bar baz'.split())

# 与标准库兼容的容器/迭代器/锁接口名（契约豁免）。比较不分大小写，
# 按切词后用下划线连接（Size、PushBack、owns_lock 都命中）；与名字长短无关。
STL_EXEMPT = frozenset('''
begin end cbegin cend rbegin rend size empty data front back swap push_back pop_back emplace_back
insert erase clear reserve resize at find count hash owns_lock
'''.split())

# 单词惯用名：只有一个词且是一眼就懂的惯用访问器/状态词时，不报首词（其余检查照常）。
# 多词名不受影响：SizeOfQueue 仍按首词 size 检查。用户在判定轮明确放行 size/count/close 一类。
SINGLE_IDIOMS = frozenset('''
accepting acquired active alive at attached blob bytes cancelled capacity closed completed context deferred
drained empty enabled eof err error failures fnv1a64 generation id key keys kind metadata minute month mutex
name next node password path pending phase pid prefix priority queued raw ready released remaining sealed
segments sequence size started stats tag url valid value view what winner
close count
'''.split())

KEYWORDS = frozenset('if else for while switch catch return sizeof static_assert template requires'.split())

# 词法上取到的这些词必不是函数名：内建类型、说明符、alignas 等（函数指针成员 void (*x)(int)
# 取到 void、alignas(...) 变量声明取到 alignas）。
TYPE_WORDS = frozenset('''
alignas void bool char int short long float double signed unsigned wchar_t char8_t char16_t char32_t
const volatile static extern mutable register auto inline virtual explicit friend constexpr consteval
constinit typename typedef using namespace struct class union enum template export noexcept
'''.split())

WORDS = re.compile(r'[A-Z]+(?![a-z0-9])|[A-Z][a-z0-9]*|[a-z0-9]+')
# 名字本身：可带 ~ 析构与 :: 限定段。
NAME_TOKEN = re.compile(r'(~?\w+(?:::\w+)*)[\\s*&]*$')


def split_words(name):
    words = []
    for part in name.split('_'):
        words.extend(WORDS.findall(part))
    return [w.lower() for w in words if w]


def stl_name(words):
    return '_'.join(words)


def check_name(name, max_words):
    """名字 → (类别, 问题) 列表；纯函数，与提取方式无关，别的语言提取器可直接复用。"""
    words = split_words(name)
    if not words:
        return []
    problems = []
    # STL 兼容豁免只覆盖整个名字（size、push_back、owns_lock），多词名如 SizeOfQueue 照查首词
    if len(words) > 1 or stl_name(words) not in STL_EXEMPT:
        # UnRegister 切成 un/register；读写锁 RLock/WLock 是单字母 r/w 前缀（可叠 un，如 RUnLock），
        # 都按后面的动词判断
        head_index = 0
        while len(words) > head_index + 1 and (words[head_index] == 'un' or words[head_index] in 'rw'):
            head_index += 1
        head = words[head_index]
        # 单词惯用名只在名字只有一个词时生效
        single_idiom = len(words) == 1 and head in SINGLE_IDIOMS
        if head not in ALLOWED and not single_idiom and head not in REPLACE:
            # head 在替换表里的（validate/receive…）complex-word 已报，首词不重复报
            problems.append(('first-word', f'首词 {head} 不在允许动词表，确认是简单行为动词，否则按「动词+对象」改名'))
    replaced = sorted({w for w in words if w in REPLACE})
    if replaced:
        simple = '、'.join(f'{w}→{REPLACE[w]}' for w in replaced)
        problems.append(('complex-word', f'复杂词换简单词：{simple}'))
    slang = sorted({w for w in words if w in SLANG})
    if slang:
        joined = '、'.join(slang)
        problems.append(('slang-word', f'口语/占位词 {joined}，换成达意的简单词'))
    if len(words) > max_words:
        problems.append(('too-many-words',
                         f'{len(words)} 个词超过 max_words={max_words}，拆职责或把条件收进参数/类型'))
    return problems


def strip_type_erasure(text):
    """位置不变地去掉模板实参与 __attribute__/__declspec（替换成等长空白），便于回推行号。"""
    def blanked(match):
        return ''.join('\n' if c == '\n' else ' ' for c in match[0])
    value = re.sub(r'\b__attribute__\s*\(\s*\([^()]*\)\s*\)', blanked, text)
    value = re.sub(r'\b__declspec\s*\([^()]*\)', blanked, value)
    while re.search(r'<[^<>]*>', value):
        value = re.sub(r'<[^<>]*>', blanked, value)
    return value


def cut_initializer_list(text):
    """构造函数初始化列表 `) : m_x(...)` 不是形参表的一部分，从首个深度 0 的 ':' 截掉。"""
    depth = 0
    for i, char in enumerate(text):
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth = max(0, depth - 1)
        elif char == ':' and depth == 0:
            if text[i:i + 2] != '::' and text[i - 1:i + 1] != '::':
                return text[:i]
    return text


def locate_name(signature):
    """在屏蔽后的签名里定位函数名，返回 (名字, 名字在 signature 里的偏移)；失败返回 ('', -1)。

    形参表是签名里第一个深度 0 的 '(' 起，名字是其前方最后一个标识符。
    宏当返回类型（`MACRO(args) Name(params)`）时 MACRO 的实参表后面紧跟下一个名字，
    而合法函数声明的形参表后面只跟限定符/初始器/异常规格，据此跳过宏实参重试。
    """
    text = cut_initializer_list(strip_type_erasure(signature))
    search_from = 0
    while True:
        depth = 0
        open_paren = -1
        close_paren = -1
        for i in range(search_from, len(text)):
            char = text[i]
            if char == '(':
                if depth == 0 and open_paren < 0:
                    open_paren = i
                depth += 1
            elif char == ')':
                if depth > 0:
                    depth -= 1
                    if depth == 0 and close_paren < 0:
                        close_paren = i
                        break
        if open_paren < 0:
            return '', -1
        match = NAME_TOKEN.search(text[:open_paren])
        if not match:
            return '', -1
        # 形参表右括号后（可隔空白）紧跟标识符/数字/'~'：不是合法函数声明尾部，
        # 是宏实参（`MACRO(args) Name(params)`，Name 可能换行），跳过这对括号再试。
        # 合法声明右括号后只有限定符/noexcept/初始器/分号/花括号，标识符开头词（const 等）不会紧跟名字。
        rest = text[close_paren + 1:] if close_paren >= 0 else ''
        if close_paren >= 0 and re.match(r'\s*[\w~]', rest) and not re.match(r'\s*(const|noexcept|override|final|requires|and|or|not)\b', rest):
            search_from = close_paren + 1
            continue
        return match[1], match.start(1)


def extract_name(signature):
    """(名字, 名字偏移)；无法识别时名字为空串。偏移用于把行号落在名字而不是声明段起点。"""
    name, pos = locate_name(signature)
    if not name or name.split('::')[-1].lstrip('~') in TYPE_WORDS:
        return '', -1
    return name, pos


def is_macro_name(name):
    """全大写宏调用（如 TEST(...)）；词法上与小写函数声明不可区分，按约定跳过。"""
    return bool(re.fullmatch(r'[A-Z][A-Z0-9_]*', name))


def skip_name(name, segment, class_name):
    """契约豁免与词法误判过滤；返回 True 表示不检查。"""
    if not name:
        return True
    if name.startswith('~'):
        return True
    if re.search(r'\boperator\b', segment):
        # operator==、operator new/delete、operator bool() 等运算符重载与转换运算符整体豁免；
        # 提取只能拿到运算符或类型词，operator 本身在名字之外。
        return True
    parts = name.split('::')
    last = parts[-1]
    if last in KEYWORDS or last == 'main':
        return True
    if last == class_name:
        return True
    if len(parts) >= 2 and parts[-2] == last:
        # 类外构造定义 Cls::Cls(...)；无返回类型但词法不验证返回类型，按两段同名判断。
        return True
    # 构造函数没有返回类型：名字前只剩构造函数限定词（或什么都没有）。
    # 覆盖嵌套类构造定义 struct Client::State { State(...) : ... } ——名字与外类不同名，
    # 仅靠 cls['name'] 判不出来；复制/移动构造写成 `X(const X&) = delete` 同属此类。
    cut = cut_initializer_list(strip_type_erasure(segment))
    depth = 0
    open_paren = -1
    close_paren = -1
    for i, char in enumerate(cut):
        if char == '(':
            if depth == 0 and open_paren < 0:
                open_paren = i
            depth += 1
        elif char == ')':
            if depth > 0:
                depth -= 1
                if depth == 0 and close_paren < 0:
                    close_paren = i
                    break
    if open_paren >= 0 and close_paren >= 0:
        before = re.sub(r'\s+', ' ', cut[:open_paren])
        idx = before.rfind(name)
        if idx >= 0:
            before = before[:idx]
        if before.rstrip().endswith((',', '}', ')')):
            # 构造初始化列表的残片：lambda 等内部花括号不属于定义签名段，iter_scope 从其中的 ';'
            # 之后起段，形如 `}) , m_id(...)` ——这不是函数声明，词法上无法还原，按提取上限跳过
            return True
        tail = re.sub(r'\s+', ' ', cut[close_paren + 1:]).strip()
        if re.fullmatch(r'(?:(?:explicit|inline|constexpr|consteval)\s+)*(?:\w+::)*', before):
            # 普通函数这条不可能成立（前面必有返回类型）；= delete/= default 的构造也是构造
            if not re.search(r'=\s*(?!0\b)\w', tail) or re.fullmatch(r'=\s*(?:delete|default)\s*', tail):
                return True
    if is_macro_name(name):
        return True
    if re.search(r'\b(override|final)\b', segment):
        return True
    return False


def looks_like_call_not_declaration(segment):
    """`T x = f(...)` / `T x(f(...))` 里的圆括号是调用或构造，不是函数声明的形参表。"""
    head = segment.split('(', 1)[0]
    return '=' in head


def iter_scope(code, pairs, begin, end):
    """枚举命名空间作用域的分号声明段与定义签名段，产出 (offset, segment)。

    递归进入 namespace 与 extern 块；跳过类型定义、函数体和初始化器。
    """
    i = begin
    while i < end:
        char = code[i]
        if char in '([' and i in pairs:
            i = pairs[i] + 1
            continue
        if char == '{' and i in pairs:
            close = pairs[i]
            cut = code.rfind(';', begin, i) + 1
            start = max(begin, cut)
            signature = code[start:i]
            squashed = re.sub(r'\s+', ' ', signature.strip())
            if re.fullmatch(r'(?:inline\s+)?(?:namespace\s+\w*(?:::\w+)*)+', squashed):
                yield from iter_scope(code, pairs, i + 1, close)
            elif re.fullmatch(r'extern\s*', squashed):
                yield from iter_scope(code, pairs, i + 1, close)
            elif squashed and not re.search(r'\b(class|struct|union|enum)\b', squashed):
                if locate_name(signature)[0]:
                    # 产出原始片段（空白未压缩），否则名字偏移映射不回原始换行，行号会漂移
                    yield start, signature
            i = close + 1
            if i > begin:
                begin = i
            continue
        if char == ';':
            segment = code[begin:i]
            if segment.strip():
                yield begin, segment
            begin = i + 1
        i += 1


DEFINE = re.compile(r'^[ \t]*#[ \t]*define\b[^\n]*\\\n(?:[^\n]*\\\n)*[^\n]*\n?', re.M)


def define_spans(text):
    """原文里带反斜杠续行的 #define 区域；core 只屏蔽首行，续行里的残片不能当作声明。"""
    return [(m.start(), m.end()) for m in DEFINE.finditer(text)]


def in_spans(offset, spans):
    return any(start <= offset < end for start, end in spans)


def iter_free_functions(source):
    # ponytail: 词法提取不展开宏、不做语义解析；函数式宏生成的声明、复杂声明符会漏报或误报，
    # 需要高保真时换编译器 AST（如 clangd 后端）。
    yield from iter_scope(source.code, source.pairs, 0, len(source.code))


def extract_candidates(source):
    """(offset, name)；offset 落在函数名上，同一文件同名只保留首个位置。"""
    spans = define_spans(source.text)
    raw = []
    for cls in source.classes:
        for op in cls['operations']:
            if in_spans(op.offset, spans):
                continue
            squashed = re.sub(r'\s+', ' ', op.signature.strip())
            name, pos = extract_name(op.signature)
            if not skip_name(name, squashed, cls['name']):
                # Member.offset 是声明片段起点（含上方被屏蔽的注释/预处理行），而 signature 是
                # 去掉首尾空白后的文本；片段起点对齐首部空白后才与 signature 同一坐标系，
                # pos 映射回原文件才落在函数名上，而不是注释起点
                rest = source.code[op.offset:]
                base = op.offset + len(rest) - len(rest.lstrip())
                raw.append((base + pos, name))
    if not spans:
        # 续行 #define 的宏体不被 core 屏蔽，残片无法按位置归属声明；这类文件已由 T000 标记解析不完整，
        # 自由函数整体跳过（漏报），类成员提取不受影响。
        for offset, segment in iter_free_functions(source):
            squashed = re.sub(r'\s+', ' ', segment.strip())
            name, pos = extract_name(segment)
            if not name or looks_like_call_not_declaration(squashed):
                continue
            if not skip_name(name, squashed, ''):
                raw.append((offset + pos, name))
    seen = set()
    for offset, name in sorted(raw):
        short = name.rsplit('::', 1)[-1]
        if short in seen:
            continue
        seen.add(short)
        yield offset, name


def check(source, options):
    max_words = options.get('max_words', 6)
    for offset, name in extract_candidates(source):
        short = name.rsplit('::', 1)[-1]
        for kind, detail in check_name(short, max_words):
            yield (source.line(offset),
                   f'candidate {short}: [{kind}] {detail}；语义约定见 naming.md「函数命名」，误报用 [[exclude]] 按符号抑制',
                   short)
