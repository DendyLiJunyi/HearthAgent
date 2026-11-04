"""Real mouse input through SendInput. Only `cli play --execute` ever constructs this class."""
import ctypes
import time
from ctypes import wintypes

from . import geometry

VK_ESCAPE = 0x1B
MOVE_ABSOLUTE = 0x0001 | 0x8000 | 0x4000  # move, absolute, whole virtual desktop
LEFT_DOWN, LEFT_UP = 0x0002, 0x0004
RIGHT_DOWN, RIGHT_UP = 0x0008, 0x0010


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class Input(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('mouse', MouseInput)]


def to_absolute(point, desktop):
    """Convert a screen pixel to SendInput's 0-65535 virtual desktop range."""
    left, top, width, height = desktop
    if width <= 1 or height <= 1 or not (left <= point[0] < left + width and top <= point[1] < top + height):
        raise geometry.GeometryError('point is outside the virtual desktop')
    return (round((point[0] - left) * 65535 / (width - 1)), round((point[1] - top) * 65535 / (height - 1)))


def path(start, end, steps=12):
    """Evenly spaced points. The game drops a drag that teleports."""
    return [(round(start[0] + (end[0] - start[0]) * i / steps),
             round(start[1] + (end[1] - start[1]) * i / steps)) for i in range(1, steps + 1)]


class WindowsInput:
    # (pause, hover) per speed. Careful is the timing every earlier live game ran on.
    FAST = (0.02, 0.15)
    CAREFUL = (0.05, 0.4)

    def __init__(self, window, *, gesture_pause=0.6, current_window=None):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.window, self.gesture_pause = window, gesture_pause
        self.current_window = current_window
        self.careful = False
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.desktop = [self.user.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
        self._aborted = False

    def aborted(self):
        if self.user.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            self._aborted = True
        return self._aborted

    def _raw(self, flags, dx=0, dy=0):
        event = Input(0, MouseInput(dx, dy, 0, flags, 0, 0))
        if self.user.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
            raise RuntimeError('SendInput did not insert the event')

    def _move(self, point):
        x, y = to_absolute(point, self.desktop)
        self._raw(MOVE_ABSOLUTE, x, y)

    def _guard(self):
        if self.aborted():
            raise RuntimeError('stopped by the player')
        front = self.user.GetForegroundWindow()
        if front != self.window['hwnd']:
            title = ctypes.create_unicode_buffer(200)
            self.user.GetWindowTextW(front, title, 200)
            raise RuntimeError(f'game is no longer the foreground window; "{title.value}" is in front')

    def send(self, gestures):
        """If anything fails mid-drag, the button is released so it cannot stay held."""
        if self.current_window:
            now = self.current_window()
            if any(now[k] != self.window[k] for k in ('hwnd', 'left', 'top', 'width', 'height')):
                raise RuntimeError('game window moved or resized')
        for index, gesture in enumerate(gestures):
            self._guard()
            self._gesture(gesture)
            # The game needs time between the steps of one move, but not after the last step.
            if index < len(gestures) - 1:
                time.sleep(self.gesture_pause)

    def _gesture(self, gesture):
        kind = gesture[0]
        if kind == 'wait':
            time.sleep(gesture[1])
            return
        if kind == 'move':
            self._move(geometry.scale(gesture[1], self.window))
            return
        if kind == 'right_click':
            self._move(geometry.scale(gesture[1], self.window))
            time.sleep(self.FAST[1])
            self._raw(RIGHT_DOWN)
            time.sleep(self.FAST[0])
            self._raw(RIGHT_UP)
            return
        pause, hover = self.CAREFUL if self.careful else self.FAST
        start = geometry.scale(gesture[1], self.window)
        self._move(start)
        time.sleep(hover)
        self._raw(LEFT_DOWN)
        try:
            time.sleep(pause)
            if kind == 'drag':
                for point in path(start, geometry.scale(gesture[2], self.window)):
                    self._guard()
                    self._move(point)
                    time.sleep(pause / 2)
                time.sleep(pause)
        finally:
            self._raw(LEFT_UP)
