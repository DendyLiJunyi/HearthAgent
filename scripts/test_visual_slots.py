import copy
import unittest
from map_visual_slots import map_slots
from test_spell_workflow import spell_fixture


def fixture():
    draft = spell_fixture()
    board = draft['observation']['board']
    board['players'][0]['hand'][0]['position'] = 1
    board['players'][1]['in_play'][0]['position'] = 1
    visual = {'frame_sha256': draft['frame_sha256'], 'window': copy.deepcopy(draft['current_window']),
              'stable': True, 'occluded': False, 'groups': {
                  'local_hand': [[.4, .85, .5, .95]], 'local_minions': [],
                  'opponent_minions': [[.45, .1, .55, .25]], 'local_hero': [], 'opponent_hero': []}}
    return draft, visual


class VisualSlotTests(unittest.TestCase):
    def test_mapping_assigns_entities_but_requires_review(self):
        draft, visual = fixture()
        original = copy.deepcopy(draft)
        result = map_slots(draft, visual)
        self.assertEqual(result['calibration']['entities'][0]['box'], [.4, .85, .5, .95])
        self.assertEqual(result['calibration']['annotation_status'], 'unreviewed')
        self.assertEqual(draft, original)

    def test_count_position_frame_and_animation_mismatches_fail(self):
        for mutate in [lambda d,v: v.update(stable=False), lambda d,v: v.update(occluded=True),
                       lambda d,v: v.update(frame_sha256='b'*64),
                       lambda d,v: v['groups']['local_hand'].clear(),
                       lambda d,v: d['observation']['board']['players'][0]['hand'][0].update(position=2),
                       lambda d,v: d['observation']['board']['players'][0]['hand'][0].update(position=True)]:
            draft, visual = fixture()
            mutate(draft, visual)
            with self.assertRaises(ValueError): map_slots(draft, visual)

    def test_log_order_does_not_override_positions(self):
        draft, visual = fixture()
        hand = draft['observation']['board']['players'][0]['hand']
        hand.append(dict(hand[0], entity_id=11, position=2))
        hand.reverse()
        draft['calibration']['entities'].append({'entity_id': 11, 'box': None})
        visual['groups']['local_hand'].append([.6, .85, .7, .95])
        result = map_slots(draft, visual)
        boxes = {e['entity_id']: e['box'] for e in result['calibration']['entities']}
        self.assertEqual(boxes[10], visual['groups']['local_hand'][0])
        self.assertEqual(boxes[11], visual['groups']['local_hand'][1])
        visual['groups']['local_hand'].reverse()
        with self.assertRaises(ValueError): map_slots(draft, visual)


if __name__ == '__main__': unittest.main()
