import copy
import unittest
from audit_attacks import audit, entity_id


def power(text): return f'D 0 GameState.DebugPrintPower() - {text}\n'
CREATE = power('CREATE_GAME')
SEND = 'D 0 GameState.SendOption() - selectedOption=1 selectedSubOption=-1 selectedTarget=20 selectedPosition=0\n'
START = power('BLOCK_START BlockType=ATTACK Entity=10 EffectCardId= EffectIndex=0 Target=20 SubOption=-1')
END = power('BLOCK_END')


def row():
    return {'game_number': 1, 'submission_number': 1, 'submission': {
        'selection': {'option': 1, 'sub_option': -1, 'target': 20, 'position': 0},
        'correlation': {'option_kind': 'POWER', 'source_entity': 10, 'packet_was_stale': False,
                       'packet_malformed_records': 0, 'packet_unsupported_records': 0,
                       'option_seen': True, 'option_error': 'NONE', 'target_seen': True,
                       'target_ambiguous': False, 'target_error': 'NONE'}}}


class AttackAuditTests(unittest.TestCase):
    def test_visible_card_play_is_not_counted_as_an_unfinished_attack(self):
        for card_type, zone in [('SPELL', 'hand'), ('MINION', 'hand'), ('HERO_POWER', 'in_play')]:
            submission = row()
            submission['source_observation'] = {'entity_id': 10, 'card_type': card_type, 'zone': zone}
            report = audit((CREATE + SEND + START + END).encode(), [submission])
            self.assertEqual(report['counts'], {'non_attack_source_observed': 1})
            self.assertIsNone(report['attempts'][0]['attack_start_line'])
        submission['source_observation']['entity_id'] = 99
        with self.assertRaises(ValueError):
            audit((CREATE + SEND).encode(), [submission])

    def test_matching_attack_requires_its_own_end_after_nested_blocks_and_spells(self):
        nested = power('BLOCK_START BlockType=TRIGGER Entity=20') + power('SUB_SPELL_START Source=20')
        nested += power('SUB_SPELL_END') + END
        report = audit((CREATE + SEND + START + nested + END).encode(), [row()])
        self.assertEqual(report['counts'], {'matching_attack_block_closed': 1})
        self.assertEqual(report['attempts'][0]['attack_end_line'], 8)
        self.assertFalse(report['execution_confirmed'])
        self.assertEqual(report['structural_errors'], 0)

    def test_pre_submission_and_animation_events_do_not_supply_future_evidence(self):
        for data in [CREATE + START + END + SEND,
                     CREATE + SEND + (START + END).replace('GameState', 'PowerTaskList'),
                     CREATE + SEND + START + END.rstrip('\n')]:
            report = audit(data.encode(), [row()])
            self.assertEqual(report['counts'], {'prefix_ended_before_attack_completion': 1})

    def test_mismatched_target_and_broken_boundaries_cannot_be_repaired(self):
        for suffix, expected in [
            (START.replace('Target=20', 'Target=99') + END + START + END, 'different_attack_target_observed'),
            (START + power('SUB_SPELL_END') + END, 'malformed_block_boundary'),
            (power('BLOCK_START BlockType=ATTACK Entity=unknown') + END, 'unparsed_attack_header'),
            (START + START + END + END, 'multiple_matching_attack_starts'),
        ]:
            self.assertEqual(audit((CREATE + SEND + suffix).encode(), [row()])['counts'], {expected: 1})

    def test_new_send_and_new_game_close_unfinished_attempts(self):
        second = row()
        second['submission_number'] = 2
        report = audit((CREATE + SEND + SEND + START + END).encode(), [row(), second])
        self.assertEqual([a['status'] for a in report['attempts']],
                         ['next_submission_before_attack_completion', 'matching_attack_block_closed'])
        self.assertEqual(audit((CREATE + SEND + CREATE + START + END).encode(), [row()])['counts'],
                         {'new_game_before_attack_completion': 1})

    def test_invalid_packet_evidence_and_mismatched_exports_are_refused(self):
        for key, value in [('packet_was_stale', True), ('target_seen', False), ('target_ambiguous', True)]:
            invalid = row()
            invalid['submission']['correlation'][key] = value
            self.assertEqual(audit((CREATE + SEND + START + END).encode(), [invalid])['counts'],
                             {'unsupported_baseline': 1})
        invalid = row()
        invalid['submission']['selection']['target'] = 99
        for rows in [[], [invalid], [row(), copy.deepcopy(row())]]:
            with self.assertRaises(ValueError): audit((CREATE + SEND).encode(), rows)

    def test_reference_parser_uses_final_structured_id_without_exporting_names(self):
        self.assertEqual(entity_id('[entityName=Some id=999 name id=20 zone=PLAY player=2]'), 20)
        self.assertIsNone(entity_id('SomePlayer'))
        self.assertIsNone(entity_id('[entityName=Some id=bad zone=PLAY]'))
        self.assertIsNone(entity_id('[entityName=Some id=20 zone=PLAY'))


if __name__ == '__main__':
    unittest.main()
