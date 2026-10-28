"""Explicit one-shot UI integration experiment; NOT an autonomous gameplay policy.

Requires exact session/game/turn arguments. Reserves a durable attempt before
one mouse-input batch and never retries. Incomplete snapshots stay incomplete.
"""
__test__ = False
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time

from probe_game_window import probe, client_point


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class Input(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('mouse', MouseInput)]


def mouse_batch(point, desktop):
    left, top, width, height = desktop
    if width <= 1 or height <= 1 or not left <= point['x'] < left + width or not top <= point['y'] < top + height:
        raise RuntimeError('click point is outside a usable virtual desktop')
    if ctypes.sizeof(Input) != (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28):
        raise RuntimeError('unexpected Windows INPUT structure layout')
    x = round((point['x'] - left) * 65535 / (width - 1))
    y = round((point['y'] - top) * 65535 / (height - 1))
    return (Input * 3)(Input(0, MouseInput(x, y, 0, 0xC001, 0, 0)),
                       Input(0, MouseInput(0, 0, 0, 2, 0, 0)), Input(0, MouseInput(0, 0, 0, 4, 0, 0)))


def replay(binary, log):
    result = subprocess.run([str(binary.resolve()), 'replay', str(log), '--json'],
                            capture_output=True, check=True, timeout=10)
    return json.loads(result.stdout.splitlines()[-1])


def check_baseline(row, game_number, turn):
    g = row['game']
    b = g['board']
    packet = g['logged_options']['latest']
    tags = next((e['last_observed_tags'] for e in g['entities'] if e['id'] == g['game_entity']), {})
    if (row['game_number'] != game_number or row['ignored_partial_line']
            or b['turn'] != turn or b['perspective'] is None or b['active_player'] != b['perspective']
            or tags.get('STATE') != 'RUNNING' or tags.get('STEP') != 'MAIN_ACTION'
            or g['unresolved_references'] or g['malformed_records'] or b['invalid_fields']
            or not g['power_structure']['closed'] or packet is None or packet['stale']
            or packet['malformed_records'] or packet['unsupported_records']):
        raise RuntimeError('expected stable local turn is not currently observed')
    ends = [option for option in packet['options'] if option['kind'] == 'END_TURN']
    if (len(ends) != 1 or ends[0]['entity_id'] is not None or ends[0]['targets'] or ends[0]['sub_options']
            or ends[0]['error'] not in ('NONE', 'INVALID')):
        raise RuntimeError('unsupported end-turn option shape')
    return ends[0]['index']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--game', type=int, required=True)
    parser.add_argument('--turn', type=int, required=True)
    parser.add_argument('--execute', action='store_true', help='Without this flag only check the baseline.')
    parser.add_argument('--installation', type=Path, default=Path(r'D:\Hearthstone'))
    args = parser.parse_args()
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    if not user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        raise RuntimeError('cannot establish physical-pixel input coordinates')
    if Path(args.session).name != args.session or not args.session.startswith('Hearthstone_'):
        parser.error('session must be a Hearthstone session directory name')
    binary = Path('target/validation/debug/hearth-agent.exe')
    sessions = sorted(p for p in (args.installation / 'Logs').iterdir() if p.is_dir() and p.name.startswith('Hearthstone_'))
    if not sessions or sessions[-1].name != args.session:
        raise RuntimeError('expected session is no longer current')
    log = sessions[-1] / 'Power.log'
    stamp = (log.stat().st_size, log.stat().st_mtime_ns)
    before = replay(binary, log)
    option_index = check_baseline(before, args.game, args.turn)
    geometry = probe()
    if geometry['status'] != 'window_found' or geometry['errors']:
        raise RuntimeError('game window is unavailable or ambiguous')
    window = geometry['windows'][0]
    if window['minimized'] or window['dpi'] != 96:
        raise RuntimeError('unsupported or minimized window')
    if not args.execute:
        print(json.dumps({'status': 'baseline_only', 'game_input_sent': False,
                          'window': window, 'option_index': option_index}))
        return
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetForegroundWindow(window['hwnd'])
    time.sleep(.2)
    if user.GetForegroundWindow() != window['hwnd']:
        raise RuntimeError('game did not acquire foreground focus')
    captured = subprocess.run(['powershell.exe', '-NoProfile', '-File', 'scripts/capture-game-window.ps1'],
                              capture_output=True, check=True, timeout=5)
    capture = json.loads(captured.stdout)
    if (capture['hwnd'] != window['hwnd'] or capture['pid'] != window['pid']
            or (capture['width'], capture['height']) != (1920, 1080)
            or capture['end_turn_yellow_fraction'] < .5):
        raise RuntimeError('current capture does not match the calibrated enabled end-turn button')
    current = probe()
    if current['windows'] != [dict(window, foreground=True)] or current['errors']:
        raise RuntimeError('window changed during validation')
    if (log.stat().st_size, log.stat().st_mtime_ns) != stamp:
        raise RuntimeError('game log changed during validation; no input sent')
    point = client_point(window, 1558 / 1920, 500 / 1080)
    user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user.GetAsyncKeyState.restype = ctypes.c_short
    if any(user.GetAsyncKeyState(key) & 0x8000 for key in (0x1B, 0x01, 0x02)):
        raise RuntimeError('Escape or a mouse button is held; cancelled')
    user.WindowFromPoint.argtypes = [wintypes.POINT]
    user.WindowFromPoint.restype = wintypes.HWND
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    at_point = user.WindowFromPoint(wintypes.POINT(point['x'], point['y']))
    if user.GetAncestor(at_point, 2) != window['hwnd']:
        raise RuntimeError('another window covers the click point')
    user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user.SendInput.restype = wintypes.UINT
    inputs = mouse_batch(point, [user.GetSystemMetrics(index) for index in (76, 77, 78, 79)])
    ledger = Path('.data/ui-attempts')
    ledger.mkdir(parents=True, exist_ok=True)
    path = ledger / f'{args.session}-game{args.game}-turn{args.turn}-end-turn.json'
    report = {'status': 'dispatch_reserved', 'session': args.session, 'game': args.game, 'turn': args.turn,
              'hwnd': window['hwnd'], 'pid': window['pid'], 'option_index': option_index,
              'execution_confirmed': False, 'automatic_retry_allowed': False}
    with path.open('x', encoding='utf-8') as output:
        output.write(json.dumps(report) + '\n')
        output.flush()
        os.fsync(output.fileno())
    if (user.GetForegroundWindow() != window['hwnd']
            or (log.stat().st_size, log.stat().st_mtime_ns) != stamp
            or user.GetAsyncKeyState(0x1B) & 0x8000):
        raise RuntimeError('state or focus changed after reservation; no input sent, attempt remains reserved')
    # One batch only. Never retry a short or failed return; delivery may be partial.
    report['input_events_inserted'] = user.SendInput(3, inputs, ctypes.sizeof(Input))
    report['status'] = 'input_attempted_result_unconfirmed'
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
