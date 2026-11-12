import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
import re
from runner import guarded, rule_input, report, git
from pushed import candidates

# ponytail: 正则只覆盖常见格式，会漏报也会误报；升级路径是接入 gitleaks。行内写 bbt-secrets:allow 可放行该行。
PATTERNS = [
    ('私钥块', re.compile('-----BEGIN ' + r'(?:[A-Z]+ )?PRIVATE KEY')),  # bbt-secrets:allow
    ('AWS access key', re.compile(r'\bAKIA[0-9A-Z]{16}\b')),
    ('GitHub token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b')),
]
ASSIGN = re.compile(r'''(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?key|token)[A-Za-z0-9_-]*["']?\s*[:=]\s*["']?([^\s"'`,;]{8,})''')
PLACEHOLDER = re.compile(r'(?i)^[$<{%\[]|example|changeme|placeholder|your|xxx|redacted|\*\*\*')
ALLOW = 'bbt-secrets:allow'


def suspicious(line):
    for name, pattern in PATTERNS:
        if pattern.search(line):
            return name
    for m in ASSIGN.finditer(line):
        value = m[1]
        if (re.search(r'\d', value) and re.search(r'[A-Za-z]', value) and not re.search(r'[()]', value)
                and not PLACEHOLDER.search(value)):
            return '疑似凭据赋值'
    return None


def added(base, tip):
    diff = git('diff', '-U0', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames', base, tip, '--').stdout
    path = line_no = None
    for line in diff.splitlines():
        if line.startswith('+++ '):
            path = None if line == '+++ /dev/null' else line[6:].split('\t')[0]
        elif line.startswith('@@'):
            line_no = int(re.match(r'@@ -\S+ \+(\d+)', line)[1])
        elif line.startswith('+') and path:
            yield path, line_no, line[1:]
            line_no += 1


def check():
    ctx = rule_input()
    problems = []
    for info in candidates(ctx):
        for path, line_no, line in added(info['base'], info['tip']):
            kind = None if ALLOW in line else suspicious(line)
            if kind:
                problems.append(f'{path}:{line_no}: 新增行疑似{kind}（不回显内容）')
    return report('E-SECRETS', problems)


if __name__ == '__main__':
    sys.exit(guarded(check))
