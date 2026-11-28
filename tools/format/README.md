# C/C++ 格式化工具

[format-cpp.py](format-cpp.py) 使用目标 Git 仓库的 `.clang-format` 或 `_clang-format`，统一格式化和只读检查。需要 Python 3.9+、Git 和 clang-format（默认要求 `23.1.3`）。

从消费仓根目录执行：

```sh
# 格式化改动的 C/C++ 文件（含未跟踪文件）
python3 third-party/bbtools-pub/tools/format/format-cpp.py

# 只读检查全部已跟踪的 C/C++ 文件
python3 third-party/bbtools-pub/tools/format/format-cpp.py --check --all

# 只读检查暂存的 C/C++ 内容
python3 third-party/bbtools-pub/tools/format/format-cpp.py --check --staged
```

有参数的长函数签名整行放不下、clang-format 只把 `const` 或 `override` 挤到下一行时，工具对该签名改为左括号后换行、每个参数一行，`) const` 或 `) override` 留在一起。短签名不强制换行；无参函数没有参数可拆，保留 clang-format 的排版。写入、`--check`、`--staged` 与 pub 的 `format` hook 共用此规则；直接运行裸 `clang-format` 不含这一步。

在 pub 自身使用时，脚本路径为 `tools/format/format-cpp.py`。`--check` 不写文件或暂存区，发现格式差异时返回非零。工具跳过 `third-party/`，不覆盖目标仓配置。

协程调用点默认按[协程语法糖的排版约定](../../docs/cpp/coroutine.md#调用点排版)处理，无需配置 lint：启动前缀后按完整 lambda 排版，并给省略参数列表的无参 lambda 补 `()`。这个规则不改普通 lambda。预处理器的 `#` 会把实参拼写变成字符串内容；因此不对宏定义、字面量、注释或 `clang-format off` 区域做协程改写。对包住协程语法、可能是函数式宏的调用，保留其括号内的原文，不根据名字大小写猜测能否字符串化。

工具不展开条件编译。若 `#if` 将前缀、捕获列表和函数体拆到不同分支，不跨指令猜测应在哪里插入 `()`；请在源码中显式写出参数列表。
