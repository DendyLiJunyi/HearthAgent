"""Offline metrics that separate model predictions, rule choices, and deployed decisions."""
import hashlib
import json
from collections import Counter


def case_fingerprint(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def evaluate_suite(policy, rows):
    right = raw_right = rules_right = raw_failures = 0
    picks, raw_picks, sources, elapsed = [], [], Counter(), []
    fallback_start = policy.fallbacks
    for row, label in rows:
        state, candidates, cards = row['state'], row['candidates'], row['cards']
        pick = policy.choose(state, candidates, cards)
        decision = policy.last_decision or {}
        raw = decision.get('raw_selected')
        if raw is None:
            try:
                scores = policy.rank(state, candidates, cards)
                raw = max(range(len(scores)), key=lambda i: (scores[i], -i))
            except Exception:
                raw_failures += 1
        right += pick == label
        raw_right += raw == label
        rules_right += policy.rules.choose(state, candidates, cards) == label
        picks.append(pick)
        raw_picks.append(raw)
        sources[decision.get('reason', 'unknown')] += 1
        elapsed.append(decision.get('elapsed_ms', 0))
    return {'right': right, 'raw_right': raw_right, 'rules_right': rules_right, 'total': len(rows),
            'picks': picks, 'raw_picks': raw_picks, 'raw_failures': raw_failures,
            'fallbacks': policy.fallbacks - fallback_start, 'decision_sources': dict(sources),
            'mean_decision_ms': sum(elapsed) / len(elapsed) if elapsed else None,
            'case_fingerprints': [case_fingerprint(row) for row, _ in rows]}


def load_final_test(path, known_rows, known_groups):
    """Reject overlap with known development data; provenance still needs independent review."""
    from pathlib import Path
    known = {case_fingerprint(row) for row in known_rows}
    seen, result = set(), []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        item = json.loads(line)
        row, label = item['row'], item['label']
        fingerprint = case_fingerprint(row)
        if not item.get('reviewer') or not item.get('group'):
            raise ValueError('final-test cases need reviewer and game group provenance')
        if item['group'] in known_groups or fingerprint in known or fingerprint in seen:
            raise ValueError('final-test data overlaps development data or contains duplicates')
        if isinstance(label, bool) or not isinstance(label, int) or not 0 <= label < len(row['candidates']):
            raise ValueError('invalid final-test label')
        seen.add(fingerprint)
        result.append((row, label))
    if not result:
        raise ValueError('final-test data is empty')
    return result
