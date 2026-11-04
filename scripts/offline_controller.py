"""Bounded multi-step orchestration over supplied snapshots, recording input only.

This is a replay controller, not a live game adapter or a game simulator.
Policy and observation callbacks are injectable; no Windows input API is imported.
"""
import copy
import hashlib
import json
from pathlib import Path
import time
from rehearse_attack import rehearse
from rehearse_spell_result import run as rehearse_card
from ui_choice_result import assess_choice
from ui_attempt import save_report
from ui_baseline import check_baseline
from ui_result import assess_end_turn
from ui_attack_result import assess_attack


class OfflineController:
    def __init__(self, directory, *, max_steps=100, budget=60, clock=time.monotonic):
        if type(max_steps) is not int or not 1 <= max_steps <= 1000:
            raise ValueError('invalid step limit')
        if type(budget) not in (int, float) or not 0 < budget <= 3600:
            raise ValueError('invalid run budget')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.max_steps, self.budget, self.clock = max_steps, budget, clock

    def run(self, observe, policy):
        report_path = self.directory / 'run.json'
        # A crash, uncertainty or previous run never grants automatic restart.
        with report_path.open('x', encoding='utf-8') as output:
            json.dump({'status': 'reserved', 'game_input_sent': False}, output)
            output.flush()
            import os
            os.fsync(output.fileno())
        report = {'source': 'offline_multi_step_controller', 'status': 'running',
                  'game_input_sent': False, 'execution_confirmed': False,
                  'policy_quality_verified': False, 'steps': []}
        started = self.clock()
        session = game = None
        last_revision = -1
        seen = set()

        def stop(status):
            report['status'] = status
            save_report(report_path, report)
            return report

        def expired(): return self.clock() - started >= self.budget

        for index in range(self.max_steps):
            if expired(): return stop('budget_expired')
            try:
                frame = copy.deepcopy(observe())
                if expired(): return stop('budget_expired')
                if frame is None: return stop('supplied_sequence_complete')
                inputs = frame['inputs']
                snapshot = inputs['observation']['snapshot']
                identity = (snapshot['session_id'], snapshot['game_number'], snapshot['revision'])
                if type(identity[2]) is not int or identity[2] < 0:
                    return stop('invalid_revision')
                if session is None: session, game = identity[:2]
                if identity[:2] != (session, game): return stop('session_or_game_changed')
                if identity in seen or identity[2] <= last_revision: return stop('repeated_or_older_state')
                decision = policy(copy.deepcopy(inputs['observation']))
                if expired(): return stop('budget_expired')
                if decision is None: return stop('policy_abstained')
                if (decision.get('session_id'), decision.get('game_number'), decision.get('revision')) != identity:
                    return stop('stale_decision')
                candidate_id = decision['candidate_id']
                candidates = [c for c in inputs['observation']['candidates'] if c['id'] == candidate_id]
                if len(candidates) != 1: return stop('unknown_or_ambiguous_candidate')
                refreshed = copy.deepcopy(observe())
                if expired(): return stop('budget_expired')
                if refreshed != frame: return stop('state_changed_during_policy')
                inputs['candidate_id'] = candidate_id
                mode = frame['mode']
                action = candidates[0]['action']
                key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
                receipt = self.directory / (key + '.json')
                if mode in ('spell', 'minion'):
                    result = rehearse_card(inputs, frame['before'], frame['after'], receipt, mode=mode)
                    expected = ('submission_and_source_in_play_observed' if mode == 'minion'
                                else 'submission_and_source_graveyard_observed')
                elif mode == 'attack':
                    before, after = frame['before'], frame['after']
                    if any(before.get(k) != snapshot[k] for k in ('session_id', 'game_number', 'revision')):
                        return stop('attack_baseline_mismatch')
                    if before['game']['board'] != inputs['observation']['board']:
                        return stop('attack_baseline_mismatch')
                    attack = action['Attack']
                    evidence_result = assess_attack(before, after, attack, frame['attack_evidence'])
                    result = rehearse(inputs, receipt, mode=mode,
                                      collect_evidence=lambda: evidence_result)
                    expected = 'matching_attack_block_closed'
                elif mode == 'end_turn':
                    before, after = frame['before'], frame['after']
                    if any(before.get(k) != snapshot[k] for k in ('session_id', 'game_number', 'revision')):
                        return stop('end_turn_baseline_mismatch')
                    if before['game']['board'] != inputs['observation']['board']:
                        return stop('end_turn_baseline_mismatch')
                    option = check_baseline(before, game, before['game']['board']['turn'])
                    def evidence():
                        if after.get('session_id') != session:
                            return {'status': 'session_changed', 'execution_confirmed': False,
                                    'automatic_retry_allowed': False}
                        return assess_end_turn(before, after, option)
                    result = rehearse(inputs, receipt, mode=mode, collect_evidence=evidence)
                    expected = 'submission_and_handoff_observed'
                elif mode == 'choice':
                    before, after = frame['before'], frame['after']
                    if any(before.get(k) != snapshot[k] for k in ('session_id', 'game_number', 'revision')):
                        return stop('choice_baseline_mismatch')
                    if before['game']['choice_preview'] != inputs['observation']['choice_preview']:
                        return stop('choice_baseline_mismatch')
                    selected = action['ChooseOptions']['entities'][0]
                    if assess_choice(before, before, selected)['status'] != 'pending':
                        return stop('unsupported_choice_baseline')
                    def evidence():
                        if after.get('session_id') != session:
                            return {'status': 'session_changed', 'execution_confirmed': False,
                                    'automatic_retry_allowed': False}
                        return assess_choice(before, after, selected)
                    result = rehearse(inputs, receipt, mode=mode, collect_evidence=evidence)
                    expected = 'matching_choice_submission_observed'
                else:
                    return stop('unsupported_action_adapter')
                seen.add(identity)
                last_revision = identity[2]
                report['steps'].append({'index': index + 1, 'revision': identity[2],
                    'mode': mode, 'candidate_id': candidate_id, 'receipt': receipt.name,
                    'evidence_status': result['receipt']['status']})
                save_report(report_path, report)
                if result['receipt']['status'] != expected: return stop('unresolved_action_evidence')
                # Advancing here consumes the next supplied offline frame. It
                # does NOT authorize continuation after live uncertain input.
            except Exception:
                return stop('adapter_failed_review_required')
        return stop('step_limit_reached')
