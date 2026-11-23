"""Exercise the serial protocol and gestures without moving the host cursor."""
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch

from agent.loop import FocusLost
from agent.makcu import Makcu, MakcuError
from agent.windows_input import WindowsInput


IDENTITY = b' km.MAKCU\r\n>>>'


def serial_port(*replies):
    return Mock(port='COM3', timeout=0.25, write=Mock(side_effect=len), read_until=Mock(side_effect=replies))


class MakcuProtocolTests(unittest.TestCase):
    def test_reopens_at_second_baud_and_accepts_legacy_echo(self):
        wrong = serial_port(b'')
        right = serial_port(b'km.version()\r\n' + IDENTITY)
        serial = ModuleType('serial')
        serial.Serial = Mock(side_effect=[wrong, right])
        serial_tools = ModuleType('serial.tools')
        serial_tools.list_ports = Mock()
        serial_tools.list_ports.comports.return_value = [
            SimpleNamespace(device='COM1', vid=None, pid=None),
            SimpleNamespace(device='COM3', vid=0x1A86, pid=0x55D3),
        ]
        with patch.dict(sys.modules, {'serial': serial, 'serial.tools': serial_tools}):
            connection = Makcu.connect()
        self.assertEqual([entry.args for entry in serial.Serial.call_args_list], [('COM3', 115200), ('COM3', 4000000)])
        wrong.close.assert_called_once()
        right.close.assert_not_called()
        connection.close()
        right.close.assert_called_once()

    def test_accepts_echoed_and_silent_setters(self):
        port = serial_port(b'km.move(12,-2)\r\n>>>', b' ', IDENTITY)
        device = Makcu(port)
        device.command('km.move(12,-2)')
        device.command('km.left(1)')
        self.assertEqual(port.write.call_args_list, [
            call(b'km.move(12,-2)\r'), call(b'km.left(1)\r'), call(b'km.version()\r'),
        ])
        self.assertEqual(port.timeout, 0.25)

    def test_rejection_stops_without_resending_the_press(self):
        port = serial_port(b'ERR\r\n>>>')
        with self.assertRaisesRegex(MakcuError, 'COM3: km.left.*device rejected'):
            Makcu(port).command('km.left(1)')
        port.write.assert_called_once_with(b'km.left(1)\r')

    def test_retries_only_the_confirmation_query(self):
        port = serial_port(b' ', b'', IDENTITY)
        device = Makcu(port)
        device.command('km.left(1)')
        self.assertEqual(port.write.call_args_list, [
            call(b'km.left(1)\r'), call(b'km.version()\r'), call(b'km.version()\r'),
        ])

    def test_reports_missing_release_state(self):
        port = serial_port(b'km.left(0)\n>>>', b'', b'')
        with self.assertRaisesRegex(MakcuError, 'missing MAKCU reply'):
            Makcu(port).release('left')
        self.assertEqual(port.write.call_args_list, [
            call(b'km.left(0)\r'), call(b'km.left()\r'), call(b'km.left()\r'),
        ])

    def test_release_checks_the_button_state_after_a_late_identity(self):
        ack = b'km.left(0)\n>>>'
        port = serial_port(IDENTITY, ack, b'km.left()\n1\r\n>>>', ack, b'2\r\n>>>')
        device = Makcu(port)
        device.release('left')
        self.assertEqual(port.write.call_args_list, [call(b'km.left(0)\r'), call(b'km.left()\r')])
        with self.assertRaisesRegex(MakcuError, 'still held by MAKCU'):
            device.release('left')

    def test_serial_disconnect_reports_the_port(self):
        port = serial_port()
        port.write.side_effect = OSError('device disconnected')
        with self.assertRaisesRegex(MakcuError, 'COM3: km.right.*device disconnected'):
            Makcu(port).command('km.right(1)')


class MakcuGestureTests(unittest.TestCase):
    def setUp(self):
        self.inputs = WindowsInput.__new__(WindowsInput)
        self.inputs.window = {'left': -1920, 'top': 0, 'width': 1920, 'height': 1080, 'hwnd': 3}
        self.inputs.desktop = (-1920, 0, 3840, 1080)
        self.inputs.current_window = None
        self.inputs._guard = Mock()
        self.inputs.device = Mock()
        self.inputs._cursor = Mock()
        self.enterContext(patch('agent.windows_input.time.sleep'))

    def test_rechecks_actual_cursor_after_each_relative_move(self):
        self.inputs._cursor.side_effect = [(0, 300), (-60, 328), (-99, 348)]
        self.inputs._move((-100, 350))
        self.assertEqual(self.inputs.device.command.call_args_list, [
            call('km.move(-50,25)'), call('km.move(-20,11)'),
        ])

    def test_accelerated_cursor_converges_from_a_screen_edge(self):
        position = [0, 1045]
        self.inputs.desktop = (0, 0, 1920, 1080)
        self.inputs._cursor.side_effect = lambda: tuple(position)
        elapsed = 0.0

        def advance(seconds):
            nonlocal elapsed
            elapsed += seconds

        def apply_motion(command):
            delta = [int(axis) for axis in command.removeprefix('km.move(').removesuffix(')').split(',')]
            gain = 2.6 if max(map(abs, delta)) >= 20 else 1.6
            for axis, limit in enumerate((1919, 1079)):
                position[axis] = max(0, min(limit, position[axis] + round(delta[axis] * gain)))

        self.inputs.device.command.side_effect = apply_motion
        with patch('agent.windows_input.time.monotonic', side_effect=lambda: elapsed), \
                patch('agent.windows_input.time.sleep', side_effect=advance):
            self.inputs._move((960, 1066))

        self.assertLessEqual(max(abs(position[0] - 960), abs(position[1] - 1066)), 2)
        self.assertLess(elapsed, 1.0)

    def test_cursor_timeout_avoids_pressing_a_button(self):
        self.inputs._cursor.return_value = (-1920, 0)
        with patch('agent.windows_input.time.monotonic', side_effect=[0, 0, self.inputs.MOVE_TIMEOUT]):
            with self.assertRaisesRegex(MakcuError, 'cursor did not reach'):
                self.inputs.send([('click', (100, 100))])
        self.inputs.device.command.assert_called_once_with('km.move(50,50)')

    def test_click_and_drag_use_the_expected_buttons_and_end_point(self):
        events = []
        self.inputs._move = lambda point: events.append(point)
        self.inputs.device.command.side_effect = events.append
        self.inputs.device.release.side_effect = lambda button: events.append(f'km.{button}(0)')
        self.inputs.send([('right_click', (100, 100))])
        self.assertEqual(events, [(-1820, 100), (-1820, 100), 'km.right(1)', 'km.right(0)'])
        events.clear()
        self.inputs.send([('drag', (100, 100), (180, 180))])
        self.assertEqual(events[2:4], ['km.left(1)', (-1810, 110)])
        self.assertEqual(events[-3:], [(-1740, 180), (-1740, 180), 'km.left(0)'])

    def test_focus_loss_or_escape_mid_drag_releases_left_button(self):
        for interruption in (FocusLost('lost focus'), RuntimeError('stopped by the player')):
            with self.subTest(interruption=interruption):
                self.inputs._guard.side_effect = [None, None, None, interruption]
                self.inputs._cursor.return_value = (-1820, 100)
                self.inputs.device.reset_mock()
                with self.assertRaisesRegex(type(interruption), str(interruption)):
                    self.inputs.send([('drag', (100, 100), (180, 180))])
                self.assertEqual(self.inputs.device.mock_calls, [
                    call.command('km.left(1)'), call.release('left'),
                ])

    def test_uncertain_right_press_still_attempts_release(self):
        self.inputs._move = Mock()
        self.inputs.device.command.side_effect = MakcuError('disconnected')
        self.inputs.device.release.side_effect = MakcuError('disconnected')
        with self.assertRaisesRegex(MakcuError, 'Could not confirm MAKCU right button release'):
            self.inputs.send([('right_click', (100, 100))])
        self.assertEqual(self.inputs.device.mock_calls, [call.command('km.right(1)'), call.release('right')])
