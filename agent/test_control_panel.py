import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from agent.control_panel import format_record, load_settings, parse_record_period, save_settings, win_records


class SettingsTests(unittest.TestCase):
    def test_restores_the_saved_form_including_paths_and_empty_fields(self):
        defaults = {'task': '接管当前对局', 'mode': '练习', 'pace': '快速', 'games': '1',
                    'config': 'config/agent.json', 'port': '', 'baud': '自动', 'deck': '', 'menu': ''}
        options = dict(defaults, task='循环对局', mode='标准', games='12', port='COM3', baud='115200',
                       config='', menu='配置/标准菜单.json', deck='123')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.data/control-panel.json'
            save_settings(path, options)
            self.assertEqual(load_settings(path, defaults), options)
            save_settings(path, dict(options, games='20'))
            self.assertEqual(load_settings(path, defaults)['games'], '20')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_missing_malformed_or_obsolete_settings_fall_back_to_defaults(self):
        defaults = {'task': '接管当前对局', 'mode': '练习', 'baud': '自动', 'games': '1'}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'control-panel.json'
            self.assertEqual(load_settings(path, defaults), defaults)
            path.write_text('{', encoding='utf-8')
            self.assertEqual(load_settings(path, defaults), defaults)
            save_settings(path, {'task': None, 'mode': 'standard', 'baud': 115200, 'games': '3', 'unknown': 1})
            self.assertEqual(load_settings(path, defaults), dict(defaults, games='3'))


class WinRecordTests(unittest.TestCase):
    def test_counts_saved_games_by_mode_and_day_without_counting_summaries_twice(self):
        today = date(2026, 11, 23)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)

            def save(relative, data, day=23):
                path = folder / relative
                path.parent.mkdir(exist_ok=True, parents=True)
                path.write_text(json.dumps(data), encoding='utf-8')
                timestamp = datetime(2026, 11, day, 12).timestamp()
                os.utime(path, (timestamp, timestamp))

            save('loop/summary.json', {'mode': 'standard', 'won': 1, 'lost': 1})
            save('loop/001/outcome.json', {'mode': 'standard', 'result': {'won': True}})
            save('loop/002/outcome.json', {'result': {'won': False}}, day=22)
            save('single/outcome.json', {'mode': 'standard', 'result': {'won': None}})
            save('wild/outcome.json', {'mode': 'wild', 'result': {'won': True}})
            save('stopped/outcome.json', {'mode': 'standard', 'result': {'won': False}, 'stopped': 'Esc'})
            save('invalid/outcome.json', {'mode': 'standard', 'result': {'won': 1}})
            save('pending/outcome.json', {'mode': 'standard', 'result': {}})
            save('older/outcome.json', {'result': {'won': True}})
            (folder / 'older' / 'outcome.json').write_text('{', encoding='utf-8')

            self.assertEqual(win_records(folder, 'standard', today)[:2], ([1, 0, 1], [1, 1, 1]))
            self.assertEqual(win_records(folder, 'wild', today)[:2], ([1, 0, 0], [1, 0, 0]))
            self.assertEqual(win_records(folder, 'practice', today)[:2], ([0, 0, 0], [0, 0, 0]))
            yesterday = date(2026, 11, 22)
            self.assertEqual(win_records(folder, 'standard', today, yesterday, today)[2], [1, 1, 1])
            self.assertEqual(win_records(folder, 'standard', today, today, today)[2], [1, 0, 1])
            self.assertEqual(win_records(folder, 'standard', today, end=yesterday)[2], [0, 1, 0])
            self.assertEqual(win_records(folder, 'standard', today, start=today)[2], [1, 0, 1])

    def test_date_range_accepts_blank_bounds_and_rejects_invalid_dates(self):
        self.assertEqual(parse_record_period('', ' 2026-11-23 '), (None, date(2026, 11, 23)))
        self.assertEqual(parse_record_period('', ''), (None, None))
        with self.assertRaisesRegex(ValueError, 'YYYY-MM-DD'):
            parse_record_period('2026-02-29', '')
        with self.assertRaisesRegex(ValueError, 'YYYY-MM-DD'):
            parse_record_period('', '20261123')
        with self.assertRaisesRegex(ValueError, '开始日期不能晚于'):
            parse_record_period('2026-11-24', '2026-11-23')

    def test_display_includes_draws_in_the_denominator(self):
        self.assertEqual(format_record([0, 0, 0]), '暂无战绩')
        self.assertEqual(format_record([1, 1, 1]), '33.3%  ·  1胜 1负 1平')
