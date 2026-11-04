"""Build reviewable lessons from confirmed agent decisions. A loss is context, never a label."""
import hashlib
import json
from pathlib import Path

from . import geometry
from .power import PowerLog, candidates_from

KEYS = ('option', 'sub', 'target')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def review_session(folder, cards):
    """Only packets both recorded by this agent and confirmed by SendOption become strategy cases."""
    folder = Path(folder)
    outcome = read_json(folder / 'outcome.json')
    report = {'schema': 1, 'session': str(folder), 'policy': outcome.get('policy'),
              'checkpoint': outcome.get('checkpoint'), 'cases': [], 'execution_failures': [], 'mulligans': []}
    moves = folder / 'moves.jsonl'
    events = [json.loads(line) for line in moves.read_text(encoding='utf-8').splitlines()] if moves.exists() else []
    report['execution_failures'] = [e for e in events if e['kind'] == 'no_send']
    for event in events:
        if event.get('type') == 'MULLIGAN':
            # Older recordings stored gestures rather than replacement entity IDs.
            replaced = event.get('replace')
            if replaced is None:
                clicks = {tuple(g[1]) for g in event['gestures'][:-1] if g[0] == 'click'}
                shown = geometry.MULLIGAN_ROW.get(len(event['entities']), (0,))[0]
                replaced = [entity for i, entity in enumerate(event['entities'][:shown])
                            if geometry.mulligan_point(i, len(event['entities'])) in clicks]
            for entity, card in zip(event['entities'], event['cards']):
                if card and card.removeprefix('CORE_') == 'CFM_637' and entity not in replaced:
                    report['mulligans'].append({'card': card, 'chosen': 'keep', 'correction': 'replace',
                                               'reason': 'Patches must stay in the deck to be summoned by a Pirate.',
                                               'label_source': 'user_correction'})
    if outcome.get('result', {}).get('won') is not False or outcome.get('stopped'):
        report['classification'] = 'execution_failure' if outcome.get('stopped') else 'not_a_completed_loss'
        return report
    log = PowerLog()
    for line in (folder / 'Power.log').read_text(encoding='utf-8', errors='replace').splitlines():
        log.feed(line)
    recorded = {(e['packet'], digest(e['state']), tuple(e['candidate'][k] for k in KEYS))
                for e in events if e['kind'] == 'option'}
    failed_packets = {e.get('packet') for e in report['execution_failures']}
    for game in log.games:
        if not game.over or game.result.get('won') is not False:
            continue
        for entry in game.sends:
            packet, sent = entry['packet'], entry['sent']
            key = (packet['id'], digest(packet['state']), tuple(sent[k] for k in KEYS))
            if key not in recorded or packet['id'] in failed_packets:
                continue
            found = []
            for candidate in candidates_from(packet):
                try:
                    geometry.plan_action(packet['state'], candidate)
                except geometry.GeometryError:
                    continue
                found.append(candidate)
            chosen = [i for i, c in enumerate(found) if all(c[k] == sent[k] for k in KEYS)]
            if len(chosen) != 1 or not 1 < len(found) <= 32:
                continue
            row = {'state': packet['state'], 'cards': packet['cards'], 'candidates': found}
            # The ID excludes folder names, game numbers and results so copied logs deduplicate.
            case = {'id': digest({'row': row, 'chosen': chosen[0]}), 'row': row, 'chosen': chosen[0],
                    'game': game.number, 'packet': packet['id'], 'source': str(folder),
                    'suggestions': []}
            report['cases'].append(case)
    report['classification'] = 'completed_loss'
    return report


def write_review(report, folder, cards):
    """A local report has no automatic gold labels: suggested alternatives still need review."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/imitation'))
    from combos import combo_setups
    from features import render_candidate, render_state
    from .policy import RulesPolicy
    rules = RulesPolicy(cards)
    lines = ['# Match lessons', '', 'Losses are evidence to review, not proof every move was wrong.', '',
             f"Classification: {report['classification']}",
             f"Execution failures: {len(report['execution_failures'])}", '']
    for lesson in report['mulligans']:
        lines += [f"Mulligan correction: {lesson['card']} → replace. {lesson['reason']}", '']
    for case in report['cases']:
        row, chosen = case['row'], case['chosen']
        setups = combo_setups(row, cards)
        for reason, indices in setups.items():
            if chosen not in indices:
                case['suggestions'].append({'reason': reason, 'alternatives': indices, 'source': 'heuristic'})
        if rules.is_blunder(row['state'], row['candidates'][chosen], row['candidates']):
            case['suggestions'].append({'reason': 'Rules blunder check', 'source': 'heuristic',
                                        'alternatives': [rules.choose(row['state'], row['candidates'], row['cards'])]})
        lines += [f"## {case['id']}", '', render_state(row, cards), '', f"Chosen: {chosen}",
                  f"Review hints: {json.dumps(case['suggestions'], ensure_ascii=False)}", '']
        lines += [f"- {i}: {render_candidate(row, c, cards)}" for i, c in enumerate(row['candidates'])]
        lines += ['']
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'lessons.json').write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    (folder / 'lessons.md').write_text('\n'.join(lines), encoding='utf-8')


def collect(root, output, cards):
    cases, sessions, mulligans = {}, [], []
    for path in sorted(Path(root).rglob('outcome.json')):
        if not path.with_name('Power.log').exists():
            continue
        report = review_session(path.parent, cards)
        write_review(report, path.parent, cards)
        sessions.append({k: report[k] for k in ('session', 'classification')})
        mulligans.extend(report['mulligans'])
        for case in report['cases']:
            cases.setdefault(case['id'], case)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = list(cases.values())
    (output / 'cases.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in rows), encoding='utf-8')
    summary = {'cases': len(rows), 'sessions': sessions, 'mulligan_corrections': len(mulligans),
               'hinted_cases': sum(bool(c['suggestions']) for c in rows)}
    (output / 'summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    # Never overwrite existing review decisions when collecting another match.
    labels = output / 'labels.json'
    if not labels.exists():
        labels.write_text(json.dumps({'schema': 1, 'labels': []}, indent=1), encoding='utf-8')
    return summary


def corrected_rows(cases_path, labels_path, cards):
    """Validate content-addressed labels before exporting any gold training targets."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/imitation'))
    from features import question, render_candidate, render_state
    cases = {c['id']: c for c in [json.loads(line) for line in Path(cases_path).read_text(encoding='utf-8').splitlines()]}
    labels = read_json(labels_path)
    if labels.get('schema') != 1:
        raise ValueError('unsupported labels schema')
    result, seen = [], set()
    for label in labels['labels']:
        case = cases[label['id']]
        if case['id'] in seen:
            raise ValueError('duplicate correction')
        seen.add(case['id'])
        row, pick = case['row'], label['corrected']
        if case['id'] != digest({'row': row, 'chosen': case['chosen']}):
            raise ValueError('case content changed after review')
        if type(pick) is not int or not 0 <= pick < len(row['candidates']):
            raise ValueError('corrected action is not a candidate')
        if pick == case['chosen'] or not label.get('reason', '').strip() or not label.get('reviewer', '').strip():
            raise ValueError('a correction requires a different action, a reason and a reviewer')
        result.append({'state': render_state(row, cards),
                       'questions': question([render_candidate(row, c, cards) for c in row['candidates']]),
                       'gold': {'action': {'probabilities': {f'c{pick}': 1.0}}}})
    return result
