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

在 pub 自身使用时，脚本路径为 `tools/format/format-cpp.py`。`--check` 不写文件或暂存区，发现格式差异时返回非零。工具跳过 `third-party/`，不覆盖目标仓配置，不额外改写协程宏空格：在宏字符串化时，空格可能是程序数据。
