import unittest
from probe_game_window import client_point


class WindowGeometryTests(unittest.TestCase):
    def test_physical_origin_can_be_on_a_negative_coordinate_monitor(self):
        window = {'minimized': False, 'client_screen_rect':
                  {'left': -1920, 'top': 100, 'right': 0, 'bottom': 1180}}
        self.assertEqual(client_point(window, .5, .5), {'x': -960, 'y': 640})
        self.assertEqual(client_point(window, 0, 0), {'x': -1920, 'y': 100})

    def test_invalid_points_and_unusable_windows_are_rejected(self):
        window = {'minimized': False, 'client_screen_rect':
                  {'left': 0, 'top': 0, 'right': 1920, 'bottom': 1080}}
        for value in [True, -0.1, 1, float('nan'), float('inf'), '0.5']:
            with self.assertRaises(ValueError):
                client_point(window, value, .5)
        window['minimized'] = True
        with self.assertRaises(ValueError):
            client_point(window, .5, .5)
        window['minimized'] = False
        window['client_screen_rect']['right'] = 0
        with self.assertRaises(ValueError):
            client_point(window, .5, .5)


if __name__ == '__main__':
    unittest.main()
