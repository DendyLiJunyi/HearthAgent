import unittest
from test_spell_workflow import spell_fixture
from test_ui_spell_result import observations
from spell_geometry import plan_spell
from ui_spell_result import assess_spell


class UntargetedSpellTests(unittest.TestCase):
    def test_known_spells_require_reviewed_clear_drop_region(self):
        for card in ['CFM_630', 'CORE_EX1_145', 'GAME_005']:
            data = spell_fixture()
            data['observation']['board']['players'][0]['hand'][0]['card_id'] = card
            data['observation']['candidates'][0]['action']['PlayCard']['target'] = None
            with self.assertRaises(ValueError): plan_spell(**data)
            data['calibration']['spell_drop_box'] = [.45, .45, .55, .55]
            plan = plan_spell(**data)
            self.assertEqual(len(plan['gesture']), 4)
            self.assertFalse(plan['game_input_sent'])
            data['calibration']['spell_drop_box'] = [.4, .85, .5, .95]
            with self.assertRaises(ValueError): plan_spell(**data)

    def test_targeted_card_cannot_be_recast_as_untargeted(self):
        data = spell_fixture()
        data['observation']['candidates'][0]['action']['PlayCard']['target'] = None
        data['calibration']['spell_drop_box'] = [.45, .45, .55, .55]
        with self.assertRaises(ValueError): plan_spell(**data)

    def test_zero_target_submission_correlates_without_inventing_target_evidence(self):
        before, after = observations()
        before['game']['card_play_preview']['candidates'][0]['action']['PlayCard']['target'] = None
        before['game']['board']['players'][0]['hand'][0]['card_id'] = 'CFM_630'
        after['game']['board']['players'][0]['graveyard'][0]['card_id'] = 'CFM_630'
        submission = after['game']['logged_options']['latest_submission']
        submission['selection']['target'] = 0
        submission['correlation'].update(target_seen=None, target_error=None)
        self.assertEqual(assess_spell(before, after, 'play')['status'], 'submission_and_source_graveyard_observed')
        submission['selection']['target'] = 20
        self.assertEqual(assess_spell(before, after, 'play')['status'], 'different_submission_observed')


if __name__ == '__main__': unittest.main()
