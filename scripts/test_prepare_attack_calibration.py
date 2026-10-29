import copy
import struct
import unittest
import zlib
from attack_geometry import plan_attack
from prepare_attack_calibration import prepare, png_dimensions
from test_attack_geometry import fixture


def png(width=1920, height=1080):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    pixels = zlib.compress((b'\0' + bytes(width * 3)) * height)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', pixels) + chunk(b'IEND', b'')


def inputs():
    data = fixture()
    observation = data['observation']
    snapshot = dict(observation['snapshot'], protocol_version=1, status='observed_log_state',
                    backlog=False, pending_bytes=0, game={
                        'board': observation['board'], 'action_preview': {
                            'blocked_by': [], 'candidates': observation['candidates']},
                        'entities': [{'card_id': 'RAW_PRIVATE_ENTITY'}]})
    snapshot['game']['board']['players'][1]['hand'] = [{'card_id': 'PRIVATE_HAND'}]
    probe = {'status': 'window_found', 'errors': [], 'windows': [data['current_window']]}
    return snapshot, probe, data


class CalibrationPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.frame = png()

    def test_draft_excludes_private_data_and_requires_explicit_review_before_planning(self):
        snapshot, probe, data = inputs()
        original = copy.deepcopy(snapshot)
        draft = prepare(snapshot, probe, self.frame, data['candidate_id'])
        self.assertEqual(snapshot, original)
        self.assertNotIn('PRIVATE', str(draft))
        self.assertTrue(all(entity['box'] is None for entity in draft['calibration']['entities']))
        with self.assertRaises(ValueError): plan_attack(**draft)
        draft['calibration']['annotation_status'] = 'reviewed'
        boxes = {entry['entity_id']: entry['box'] for entry in data['calibration']['entities']}
        for entry in draft['calibration']['entities']: entry['box'] = boxes[entry['entity_id']]
        self.assertFalse(plan_attack(**draft)['actionable'])

    def test_backlog_partial_line_and_blocked_previews_are_refused(self):
        for key, value in [('backlog', True), ('pending_bytes', 1), ('status', 'waiting_for_power_log')]:
            snapshot, probe, data = inputs()
            snapshot[key] = value
            with self.assertRaises(ValueError): prepare(snapshot, probe, self.frame, data['candidate_id'])
        snapshot, probe, data = inputs()
        snapshot['game']['action_preview']['blocked_by'] = ['stale_options']
        with self.assertRaises(ValueError): prepare(snapshot, probe, self.frame, data['candidate_id'])

    def test_corrupt_truncated_and_dimension_mismatched_captures_are_refused(self):
        self.assertEqual(png_dimensions(self.frame), (1920, 1080))
        for frame in [self.frame[:-1], self.frame + b'extra', b'not png',
                      self.frame[:20] + bytes([self.frame[20] ^ 1]) + self.frame[21:]]:
            with self.assertRaises(ValueError): png_dimensions(frame)
        snapshot, probe, data = inputs()
        with self.assertRaises(ValueError): prepare(snapshot, probe, png(640, 480), data['candidate_id'])

    def test_ambiguous_windows_candidates_and_entities_are_refused(self):
        for mutate in [lambda s, p: p['windows'].append(copy.deepcopy(p['windows'][0])),
                       lambda s, p: s['game']['action_preview']['candidates'].append(
                           copy.deepcopy(s['game']['action_preview']['candidates'][0])),
                       lambda s, p: s['game']['board']['players'][0]['in_play'].append(
                           copy.deepcopy(s['game']['board']['players'][0]['in_play'][0]))]:
            snapshot, probe, data = inputs()
            mutate(snapshot, probe)
            with self.assertRaises(ValueError): prepare(snapshot, probe, self.frame, data['candidate_id'])


if __name__ == '__main__':
    unittest.main()
