"""Closing the game between games, so a long run can start again from a fresh client.

The game is asked to close first, and forced only if it does not. Nothing here looks at game state, so
the caller must be out of the game scene before closing it.
"""
import ctypes
import random
import subprocess
import time
from ctypes import wintypes

from .loop import Stop

WM_CLOSE = 0x0010
CLOSE_TIMEOUT = 30.0
FORCE_TIMEOUT = 15.0
AFTER_EXIT_PAUSE = 5.0  # Battle.net needs a moment to see that the game has gone before it will start it again.


class RestartPlan:
    """Picks how many games to play before each restart, again after every restart."""

    def __init__(self, choices, rng=random):
        self.choices, self.rng = choices, rng
        self.played = 0
        self.target = rng.choice(choices) if choices else None

    def game_played(self):
        """Count a finished game. True when a restart is due."""
        self.played += 1
        return self.target is not None and self.played >= self.target

    def restarted(self):
        self.played = 0
        self.target = self.rng.choice(self.choices)


def parse_restart_every(text):
    """'6' or '5,6,7'. With several numbers, one is picked at random for each stretch of games."""
    try:
        choices = [int(part) for part in text.split(',')]
    except ValueError:
        raise ValueError(f'expected numbers such as 6 or 5,6,7, not {text}') from None
    if any(choice <= 0 for choice in choices):
        raise ValueError('each number of games must be positive')
    return choices


def post_close(hwnd):
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    return bool(user.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def game_process_running(pid):
    """The process ID must still belong to Hearthstone, because Windows can reuse an ID."""
    done = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True, text=True,
                          errors='replace', timeout=15, check=True)
    return 'hearthstone.exe' in done.stdout.casefold()


def force_close(pid):
    subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=15, check=False)


def bring_to_front(hwnd):
    """Best effort, because Windows can refuse. Until the game is in front, the menu walker just waits."""
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.SetForegroundWindow.restype = wintypes.BOOL
    return bool(user.SetForegroundWindow(hwnd))


def close_game(window, aborted=lambda: False, *, post=post_close, running=game_process_running, force=force_close,
               clock=time.monotonic, sleep=time.sleep, log=print):
    """Close this game window's process and wait until it is really gone."""
    pid = window['pid']

    def wait_for_exit(timeout):
        deadline = clock() + timeout
        while clock() < deadline:
            if aborted():
                raise Stop('stopped by the player')
            if not running(pid):
                return True
            sleep(0.5)
        return not running(pid)

    if post(window['hwnd']) and wait_for_exit(CLOSE_TIMEOUT):
        sleep(AFTER_EXIT_PAUSE)
        return 'closed'
    log(f'Hearthstone did not close when asked, so forcing it to (process {pid}).')
    force(pid)
    if not wait_for_exit(FORCE_TIMEOUT):
        raise Stop('Hearthstone would not close')
    sleep(AFTER_EXIT_PAUSE)
    return 'forced'
