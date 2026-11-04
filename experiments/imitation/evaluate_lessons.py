"""Compare a loss-lesson candidate on fixed held-out player games and reviewed corrections."""
import argparse
import gc
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agent.learning import corrected_rows, read_json
from agent.policy import LayaPolicy, load_cards
from agent.evaluation import evaluate_suite, load_final_test
from features import TEST_GROUPS
from retrain import WARRIOR_TEST, decisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--base', type=Path, default=ROOT / '.data/imitation/laya-combo')
    parser.add_argument('--lessons', type=Path, default=ROOT / '.data/learning')
    parser.add_argument('--report', type=Path, default=ROOT / '.data/learning/evaluation.json')
    parser.add_argument('--final-test', type=Path, help='Independent reviewed JSONL; never used for promotion selection.')
    args = parser.parse_args()
    cards = load_cards()
    # Validate the reviewed corrections against their exact case contents first.
    corrected_rows(args.lessons / 'cases.jsonl', args.lessons / 'labels.json', cards)
    cases = {r['id']: r for r in [json.loads(line) for line in
                                 (args.lessons / 'cases.jsonl').read_text(encoding='utf-8').splitlines()]}
    corrections = [(cases[l['id']]['row'], l['corrected']) for l in read_json(args.lessons / 'labels.json')['labels']]
    suites = {'warrior_held_out': [], 'older_held_out': [], 'correction_fit': corrections}
    development = list(decisions())
    for group, _, row, label in development:
        if group in WARRIOR_TEST:
            suites['warrior_held_out'].append((row, label))
        elif group in TEST_GROUPS:
            suites['older_held_out'].append((row, label))
    if args.final_test:
        suites['final_test'] = load_final_test(args.final_test,
            [row for _, _, row, _ in development] + [row for row, _ in corrections],
            {group for group, _, _, _ in development})
    report = {'base': str(args.base.resolve()), 'candidate': str(args.candidate.resolve()),
              'scope': 'Fixed held-out games are validation used for selection, not an untouched test. '
                       'Agreement is not win rate. Correction fit is in-sample. '
                       'Optional final_test is reported separately and requires independently verified provenance.',
              'models': {}}
    for name, path in (('base', args.base), ('candidate', args.candidate)):
        policy = LayaPolicy.load(cards, path)
        metrics = {}
        for suite, rows in suites.items():
            print(f'Evaluating {name} {suite}: {len(rows)} cases', flush=True)
            metrics[suite] = evaluate_suite(policy, rows)
            print(name, suite, metrics[suite]['right'], '/', len(rows), flush=True)
        metrics['policy_config'] = {'orders': policy.orders, 'preference_penalty': policy.preference_penalty}
        metrics['fallbacks'] = policy.fallbacks
        report['models'][name] = metrics
        del policy
        gc.collect()
        import torch
        torch.cuda.empty_cache()
    before, after = report['models']['base'], report['models']['candidate']
    report['eligible_for_promotion'] = (
        all(after[s]['fallbacks'] == 0 for s in ('warrior_held_out', 'older_held_out', 'correction_fit'))
        and all(after[s]['raw_failures'] == 0 for s in ('warrior_held_out', 'older_held_out', 'correction_fit'))
        and all(after[s]['total'] > 0 and after[s]['right'] >= before[s]['right']
                for s in ('warrior_held_out', 'older_held_out'))
        and after['correction_fit']['right'] >= before['correction_fit']['right']
        and after['correction_fit']['raw_right'] > before['correction_fit']['raw_right'])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'models'}), flush=True)


if __name__ == '__main__':
    main()
