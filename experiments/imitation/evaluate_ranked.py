"""Compare Standard adaptation with deployed tactics, held-out boards and Wild retention."""
import argparse
import gc
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent.deck_profile import STANDARD_WARRIOR, load_profile
from agent.evaluation import case_fingerprint, evaluate_suite
from agent.learning import corrected_rows, read_json
from agent.policy import LayaPolicy, load_cards
from features import TEST_GROUPS, render_state, render_candidate, question
from retrain import WARRIOR_TEST, decisions


def reviewed(folder, cards):
    corrected_rows(folder / 'cases.jsonl', folder / 'labels.json', cards)
    cases = {c['id']: c for c in map(json.loads, (folder / 'cases.jsonl').read_text(encoding='utf-8').splitlines())}
    labels = read_json(folder / 'labels.json')['labels']
    return [(cases[l['id']]['row'], l['corrected']) for l in labels], {cases[l['id']]['source'] for l in labels}


def validate_holdout(items, training, train_groups, replay, cards):
    seen = {case_fingerprint(row) for row, _ in training}
    rendered = {(r['state'], json.dumps(r['questions'], sort_keys=True)) for r in replay}
    rows = []
    for item in items:
        row, label = item['row'], item['label']
        key = case_fingerprint(row)
        if not item.get('reviewer') or not item.get('reason') or not item.get('group') or item.get('group') in train_groups:
            raise ValueError('Standard validation requires review and a separate game group')
        if key in seen or not isinstance(label, int) or isinstance(label, bool) or not 0 <= label < len(row['candidates']):
            raise ValueError('Standard validation overlap or invalid label')
        text_key = (render_state(row, cards), json.dumps(question([render_candidate(row, c, cards)
                    for c in row['candidates']]), sort_keys=True))
        if text_key in rendered:
            raise ValueError('Standard validation text occurs in replay training data')
        seen.add(key)
        rows.append((row, label))
    if not rows:
        raise ValueError('Standard validation must not be empty')
    return rows


def eligible(before, after):
    suites = ('warrior_validation', 'older_validation', 'wild_retention', 'standard_validation', 'standard_fit')
    return (all(after[s]['total'] > 0 and after[s]['right'] >= before[s]['right']
                and after[s]['fallbacks'] == 0 and after[s]['raw_failures'] == 0 for s in suites)
            and after['standard_fit']['raw_right'] > before['standard_fit']['raw_right']
            and after['standard_validation']['raw_right'] >= before['standard_validation']['raw_right'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--lessons', type=Path, required=True)
    parser.add_argument('--retention', type=Path, required=True)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    cards = load_cards()
    fit, train_groups = reviewed(args.lessons, cards)
    wild, wild_groups = reviewed(args.retention, cards)
    replay = list(map(json.loads, args.replay.read_text(encoding='utf-8').splitlines()))
    development = list(decisions())
    validation = validate_holdout(list(map(json.loads, (args.lessons / 'validation.jsonl').read_text(encoding='utf-8').splitlines())),
                                  fit + wild + [(r, l) for _, _, r, l in development],
                                  train_groups | wild_groups | {g for g, _, _, _ in development}, replay, cards)
    suites = {'warrior_validation': [(r, l) for g, _, r, l in development if g in WARRIOR_TEST],
              'older_validation': [(r, l) for g, _, r, l in development if g in TEST_GROUPS and g not in WARRIOR_TEST],
              'wild_retention': wild, 'standard_fit': fit, 'standard_validation': validation}
    profile = load_profile(STANDARD_WARRIOR, 'standard')
    report = {'base': str(args.base), 'candidate': str(args.candidate), 'models': {},
              'scope': 'Standard fit and Wild retention are in-sample reviewed judgments. Standard validation '
                       'uses separate game groups and rejects exact raw/text overlap with replay. All labels are '
                       'assistant-reviewed preferences. Fixed older games are selection validation, not final tests. '
                       'These metrics do not measure ranked win rate.'}
    for name, path in (('base', args.base), ('candidate', args.candidate)):
        policy = LayaPolicy.load(cards, path, tactics=True)
        metrics = {}
        for suite, rows in suites.items():
            policy.rules.deck_profile = profile if suite.startswith('standard_') else {}
            print(f'Evaluating {name} {suite}: {len(rows)} cases', flush=True)
            metrics[suite] = evaluate_suite(policy, rows)
            m = metrics[suite]
            print(f'{name} {suite}: deployed {m["right"]}/{m["total"]}, raw {m["raw_right"]}/{m["total"]}', flush=True)
        report['models'][name] = metrics
        del policy
        gc.collect()
        import torch
        torch.cuda.empty_cache()
    report['eligible_for_promotion'] = eligible(report['models']['base'], report['models']['candidate'])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('eligible_for_promotion:', report['eligible_for_promotion'], flush=True)


if __name__ == '__main__':
    main()
