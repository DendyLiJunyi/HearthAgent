import unittest
from test_ui_spell_result import observations
from ui_spell_result import assess_minion


def pair():
    before, after = observations()
    before['game']['card_play_preview']['candidates'][0]['action']['PlayCard'].update(target=None, position=1)
    before['game']['board']['players'][0]['hand'][0].update(card_type='MINION', card_id='LOOT_412')
    player = after['game']['board']['players'][0]
    player['in_play'] = player['graveyard']
    player['graveyard'] = []
    player['in_play'][0].update(card_type='MINION', card_id='LOOT_412', position=1)
    submission = after['game']['logged_options']['latest_submission']
    submission['selection'].update(target=0, position=1)
    submission['correlation'].update(target_seen=None, target_error=None)
    return before, after


class MinionResultTests(unittest.TestCase):
    def test_source_in_play_and_position_are_observed_not_confirmation(self):
        result = assess_minion(*pair(), 'play')
        self.assertEqual(result['status'], 'submission_and_source_in_play_observed')
        self.assertFalse(result['execution_confirmed'])
        self.assertFalse(result['automatic_retry_allowed'])

    def test_wrong_submission_or_final_position_is_not_success(self):
        before, after = pair()
        after['game']['logged_options']['latest_submission']['selection']['position'] = 2
        self.assertEqual(assess_minion(before, after, 'play')['status'], 'different_submission_observed')
        after['game']['logged_options']['latest_submission']['selection']['position'] = 1
        after['game']['board']['players'][0]['in_play'][0]['position'] = 2
        self.assertEqual(assess_minion(before, after, 'play')['status'], 'different_board_position_observed')

    def test_immediate_death_does_not_fabricate_success_or_retry(self):
        before, after = pair()
        player = after['game']['board']['players'][0]
        player['graveyard'], player['in_play'] = player['in_play'], []
        result = assess_minion(before, after, 'play')
        self.assertEqual(result['status'], 'pending')
        self.assertTrue(result['matching_submission_observed'])
        self.assertFalse(result['automatic_retry_allowed'])


if __name__ == '__main__': unittest.main()
