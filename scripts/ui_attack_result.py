"""Attack evidence from supplied frozen log prefixes and submission exports.

Exports are offline inputs, not authenticated game state. No input causation or
damage outcome is inferred from a matching block.
"""
from audit_attacks import audit


def assess_attack(before, after, action, evidence):
    result = {'status': 'attack_evidence_mismatch', 'execution_confirmed': False,
              'automatic_retry_allowed': False}
    def status(value): return dict(result, status=value)
    if any(before.get(k) != after.get(k) for k in ('session_id', 'game_number')):
        return status('session_or_game_changed')
    old = evidence['before_log'].encode('utf-8')
    new = evidence['after_log'].encode('utf-8')
    if len(new) > 64 * 1024 * 1024 or not old.endswith(b'\n') or not new.endswith(b'\n'):
        return status('incomplete_or_oversized_log')
    if not new.startswith(old): return status('log_prefix_changed')
    old_rows, new_rows = evidence['before_submissions'], evidence['after_submissions']
    if new_rows[:-1] != old_rows or len(new_rows) != len(old_rows) + 1:
        return status('unexpected_submission_history')
    baseline = audit(old, old_rows)
    report = audit(new, new_rows)
    if baseline['structural_errors'] or report['structural_errors']:
        return status('invalid_power_structure')
    row = new_rows[-1]
    previous = before['game']['logged_options']
    current = after['game']['logged_options']
    if (row['game_number'] != before['game_number'] or
            row['submission_number'] != previous['submissions_seen'] + 1 or
            row['submission_number'] != current['submissions_seen'] or
            row['submission'] != current['latest_submission']):
        return result
    correlation = row['submission']['correlation']
    if correlation.get('packet_id') != previous['latest']['id']:
        return result
    attempts = [a for a in report['attempts'] if
                (a['game_number'], a['submission_number']) ==
                (row['game_number'], row['submission_number'])]
    if len(attempts) != 1: return result
    attempt = attempts[0]
    if (attempt['source_entity'], attempt['target_entity']) != (action['source'], action['target']):
        return result
    if not after['game']['power_structure']['closed']:
        return status('attack_block_incomplete')
    return status(attempt['status'])
