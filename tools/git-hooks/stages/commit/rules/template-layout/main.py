import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import guarded, rule_input, report, git, HookError

import re
from staged import files

def check():
    ctx = rule_input()
    return report('E-TEMPLATE-LAYOUT', [f'{p}: 模板实现应放在 __TXxx.hpp，不用 impl/ 目录或 *Impl.hpp'
                                        for p in files(ctx, 'A') if re.search(r'(^|/)impl/|Impl\.hpp$', p)])

if __name__ == '__main__':
    sys.exit(guarded(check))
