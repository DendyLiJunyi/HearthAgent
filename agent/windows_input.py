"""Windows cursor feedback and live mouse gestures through MAKCU."""
import ctypes
import time
from ctypes import wintypes

from . import geometry
from .loop import FocusLost
from .makcu import Makcu, MakcuError

VK_ESCAPE = 0x1B


def check_desktop_point(point, desktop):
    """Reject targets outside the virtual desktop, including negative-origin layouts."""
    left, top, width, height = desktop
    if width <= 1 or height <= 1 or not (left <= point[0] < left + width and top <= point[1] < top + height):
        raise geometry.GeometryError('point is outside the virtual desktop')


def path(start, end, steps=12):
    """Evenly spaced points. The game drops a drag that teleports."""
    return [(round(start[0] + (end[0] - start[0]) * i / steps),
             round(start[1] + (end[1] - start[1]) * i / steps)) for i in range(1, steps + 1)]


class WindowsInput:
    # (pause, hover) per speed. Careful is the timing every earlier live game ran on.
    # Recovery retries a failed fast gesture at careful speed, so fast can be tried safely.
    FAST = (0.01, 0.08)
    CAREFUL = (0.05, 0.4)
    FAST_STEPS, CAREFUL_STEPS = 8, 12
    FAST_PARK, CAREFUL_PARK = 0.03, 0.15
    FAST_GESTURE_PAUSE = 0.4
    MOVE_TOLERANCE = 2
    MOVE_SETTLE = 0.055
    MOVE_TIMEOUT = 2.0
    MAX_DELTA = 512
    careful = False

    def __init__(self, window, *, gesture_pause=0.6, current_window=None, port=None, baud=None):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.window, self.gesture_pause = window, gesture_pause
        self.current_window = current_window
        self.user.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user.GetCursorPos.restype = wintypes.BOOL
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.desktop = [self.user.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
        self._aborted = False
        self.device = Makcu.connect(port, baud)

    def close(self):
        self.device.close()

    def aborted(self):
        if self.user.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            self._aborted = True
        return self._aborted

    def ready(self):
        """A background window pauses the controller before a gesture; never sends input."""
        return self.user.GetForegroundWindow() == self.window['hwnd']

    def park(self):
        """Clear card/minion hover without clicking or changing the game state."""
        self._guard()
        # Let the client process button-up at its original target before moving away.
        # Immediate parking left mulligan Confirm unanswered despite successful card toggles.
        time.sleep(self.CAREFUL_PARK if self.careful else self.FAST_PARK)
        self._guard()
        self._move(geometry.scale(geometry.CANCEL_POINT, self.window))

    def _cursor(self):
        cursor = wintypes.POINT()
        if not self.user.GetCursorPos(ctypes.byref(cursor)):
            raise MakcuError('Could not read the Windows cursor position')
        return cursor.x, cursor.y

    def _move_step(self, error, damping):
        if abs(error) <= self.MOVE_TOLERANCE:
            return 0
        step = min(self.MAX_DELTA, max(1, round(abs(error) / damping)))
        return step if error > 0 else -step

    def _move(self, point):
        check_desktop_point(point, self.desktop)
        deadline = time.monotonic() + self.MOVE_TIMEOUT
        previous_error = (0, 0)
        damping = [2, 2]
        while True:
            self._guard()
            x, y = self._cursor()
            error = point[0] - x, point[1] - y
            if max(map(abs, error)) <= self.MOVE_TOLERANCE:
                return
            if time.monotonic() >= deadline:
                raise MakcuError(f'MAKCU cursor did not reach {point}; last position was {(x, y)}')
            # Windows pointer acceleration can turn a full correction into repeated overshoot.
            for axis, remaining in enumerate(error):
                previous = previous_error[axis]
                if abs(remaining) > self.MOVE_TOLERANCE and remaining * previous < 0:
                    damping[axis] = min(8, damping[axis] * 2)
                elif remaining * previous > 0 and abs(remaining) < abs(previous):
                    damping[axis] = max(2, damping[axis] - 1)
            dx, dy = (self._move_step(remaining, factor) for remaining, factor in zip(error, damping))
            self.device.command(f'km.move({dx},{dy})')
            previous_error = error
            time.sleep(self.MOVE_SETTLE)

    def _guard(self):
        if self.aborted():
            raise RuntimeError('stopped by the player')
        front = self.user.GetForegroundWindow()
        if front != self.window['hwnd']:
            title = ctypes.create_unicode_buffer(200)
            self.user.GetWindowTextW(front, title, 200)
            raise FocusLost(f'game is no longer the foreground window; "{title.value}" is in front')

    def _check_window(self):
        if self.current_window:
            now = self.current_window()
            if any(now[k] != self.window[k] for k in ('hwnd', 'left', 'top', 'width', 'height')):
                raise RuntimeError('game window moved or resized')

    def send(self, gestures):
        """Send gestures to the current foreground game window."""
        for index, gesture in enumerate(gestures):
            self._guard()
            self._check_window()
            self._gesture(gesture)
            # The game needs time between the steps of one move, but not after the last step.
            if index < len(gestures) - 1:
                time.sleep(self.gesture_pause if self.careful else min(self.gesture_pause, self.FAST_GESTURE_PAUSE))

    def _gesture(self, gesture):
        kind = gesture[0]
        if kind == 'wait':
            time.sleep(gesture[1])
            return
        if kind == 'move':
            self._move(geometry.scale(gesture[1], self.window))
            return
        button = 'right' if kind == 'right_click' else 'left'
        pause, hover = self.CAREFUL if self.careful and button == 'left' else self.FAST
        start = geometry.scale(gesture[1], self.window)
        end = geometry.scale(gesture[2], self.window) if kind == 'drag' else None
        if end is not None:
            check_desktop_point(end, self.desktop)
        self._move(start)
        time.sleep(hover)
        self._check_window()
        self._move(start)
        try:
            self.device.command(f'km.{button}(1)')
            time.sleep(pause)
            if end is not None:
                steps = self.CAREFUL_STEPS if self.careful else self.FAST_STEPS
                for point in path(start, end, steps):
                    self._check_window()
                    self._move(point)
                    time.sleep(pause / 2)
                time.sleep(pause)
                self._check_window()
                self._move(end)
        finally:
            try:
                self.device.release(button)
            except MakcuError as error:
                raise MakcuError(f'Could not confirm MAKCU {button} button release: {error}') from error
