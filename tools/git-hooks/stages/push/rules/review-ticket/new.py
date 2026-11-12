"""Write a ticket skeleton for a reviewed commit. The reviewer fills it in; nothing here reviews anything."""
import argparse
import datetime
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import HookError, config, guarded, load_meta
from pushed import TICKETS, ancestor, resolve


def make():
    parser = argparse.ArgumentParser(description='Create .config/review-tickets/<date>/<commit>.json skeleton')
    parser.add_argument('--commit', default='HEAD', help='reviewed code commit (default HEAD)')
    parser.add_argument('--base', required=True, help='review covered base..commit; base is a strict ancestor')
    args = parser.parse_args()
    cfg = config()
    tip, base = resolve(args.commit), resolve(args.base)
    if tip == base or not ancestor(base, tip):
        raise HookError('base must be a strict ancestor of commit')
    checks = [{'id': rule, 'kind': 'attested', 'status': 'pending', 'summary': '',
               'evidence': {'reviewer': '', 'scope': ''}}
              for rule in cfg['push']['rules'] if load_meta('push', rule)['kind'] == 'attested']
    today = datetime.date.today().isoformat()
    ticket = {'schema_version': 1, 'date': today, 'commit': tip, 'base': base, 'result': 'pending',
              'reviewer': '', 'summary': '', 'checks': checks}
    path = Path(TICKETS) / today / f'{tip}.json'
    if path.exists():
        raise HookError(f'{path} already exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ticket, ensure_ascii=False, indent=2) + '\n')
    print(f'{path}\n填写 result/reviewer/summary 与各 check 后，把它单独提交为紧随 {tip[:12]} 的 commit（只含 {TICKETS}）')
    return 0


if __name__ == '__main__':
    sys.exit(guarded(make))
