"""规则骨架：复制到 stages/<commit|push>/rules/<id>/，改 meta.toml，再把 id 加入配置的 rules 数组。

协议：从 stdin 读上下文；通过则退出 0；违规用 report(code, problems, fix?) 或 raise RuleFail 退出 1，
runner 统一渲染（code 形如 E-XXX、problems 每条带位置与原因）；工具或环境错误抛 HookError 退出 2。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import guarded, rule_input, report


def check():
    ctx = rule_input()
    problems = []  # 例如 [f'{path}:{line}: 原因']
    return report('E-EXAMPLE', problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
