import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'core'))
from runner import guarded, rule_input, RuleFail
from pushed import candidates, load_ticket, nonempty


def check():
    ctx = rule_input()
    for info in candidates(ctx):
        if not info['code']:
            continue
        path, ticket = load_ticket(info)
        checks = [c for c in ticket.get('checks') or [] if isinstance(c, dict) and c.get('id') == 'llm-review']
        if not checks:
            raise RuleFail('E-LLM-REVIEW-MISSING', [f'{path}: checks 里没有 id 为 llm-review 的检查项'])
        c = checks[0]
        evidence = c.get('evidence')
        evidence = evidence if isinstance(evidence, dict) else {}
        problems = []
        if c.get('kind') != 'attested' or c.get('status') != 'pass':
            problems.append(f'llm-review 需 kind=attested、status=pass，实际 {c.get("kind")!r}/{c.get("status")!r}')
        if not nonempty(c.get('summary')):
            problems.append('llm-review.summary 必须是非空字符串')
        for field in ('reviewer', 'scope'):
            if not nonempty(evidence.get(field)):
                problems.append(f'llm-review.evidence.{field} 必须是非空字符串')
        if problems:
            raise RuleFail('E-LLM-REVIEW-INCOMPLETE', [f'{path}: {x}' for x in problems])
    return 0


if __name__ == '__main__':
    sys.exit(guarded(check))
