"""Read-only Hearthstone window geometry for a future external-input adapter."""
import argparse
import ctypes
from ctypes import wintypes
import json
import math
from pathlib import Path
import sys


def client_point(window, x, y):
    """Map a calibrated normalized point to physical screen pixels; never click."""
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or not 0 <= v < 1 for v in (x, y)):
        raise ValueError('normalized coordinates must be finite and in [0, 1)')
    rect = window['client_screen_rect']
    width, height = rect['right'] - rect['left'], rect['bottom'] - rect['top']
    if window['minimized'] or width <= 0 or height <= 0:
        raise ValueError('window has no usable client area')
    return {'x': rect['left'] + int(x * width), 'y': rect['top'] + int(y * height)}


def probe():
    if sys.platform != 'win32':
        raise RuntimeError('window probing requires Windows')
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def bind(dll, name, result, *args):
        function = getattr(dll, name)
        function.restype, function.argtypes = result, list(args)
        return function

    enum = bind(user, 'EnumWindows', wintypes.BOOL, callback_type, wintypes.LPARAM)
    visible = bind(user, 'IsWindowVisible', wintypes.BOOL, wintypes.HWND)
    iconic = bind(user, 'IsIconic', wintypes.BOOL, wintypes.HWND)
    foreground = bind(user, 'GetForegroundWindow', wintypes.HWND)
    pid_for = bind(user, 'GetWindowThreadProcessId', wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    rect_for = bind(user, 'GetClientRect', wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    to_screen = bind(user, 'ClientToScreen', wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    dpi_for = bind(user, 'GetDpiForWindow', wintypes.UINT, wintypes.HWND)
    dpi_context = bind(user, 'SetThreadDpiAwarenessContext', ctypes.c_void_p, ctypes.c_void_p)
    open_process = bind(kernel, 'OpenProcess', wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    image_name = bind(kernel, 'QueryFullProcessImageNameW', wintypes.BOOL, wintypes.HANDLE,
                      wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    close = bind(kernel, 'CloseHandle', wintypes.BOOL, wintypes.HANDLE)
    windows, errors = [], []

    @callback_type
    def visit(hwnd, _):
        # Never let Python exceptions escape through a native callback.
        try:
            if not visible(hwnd):
                return True
            pid = wintypes.DWORD()
            if not pid_for(hwnd, ctypes.byref(pid)):
                return True
            handle = open_process(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION only
            if not handle:
                return True
            try:
                name = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(name))
                if not image_name(handle, 0, name, ctypes.byref(size)):
                    return True
                if Path(name.value).name.casefold() != 'hearthstone.exe':
                    return True
            finally:
                close(handle)
            rect = wintypes.RECT()
            if not rect_for(hwnd, ctypes.byref(rect)):
                raise OSError('client_rect_unavailable')
            origin, corner = wintypes.POINT(rect.left, rect.top), wintypes.POINT(rect.right, rect.bottom)
            if not to_screen(hwnd, ctypes.byref(origin)) or not to_screen(hwnd, ctypes.byref(corner)):
                raise OSError('screen_coordinates_unavailable')
            windows.append({'hwnd': int(hwnd), 'pid': pid.value,
                            'foreground': foreground() == hwnd, 'minimized': bool(iconic(hwnd)),
                            'dpi': dpi_for(hwnd), 'client_screen_rect': {
                                'left': origin.x, 'top': origin.y, 'right': corner.x, 'bottom': corner.y}})
        except Exception:
            errors.append('window_probe_failed')
        return True

    old_context = dpi_context(ctypes.c_void_p(-4))  # Per-monitor aware V2
    if not old_context:
        raise RuntimeError('cannot establish physical-pixel DPI context')
    try:
        if not enum(visit, 0):
            raise RuntimeError('window_enumeration_failed')
    finally:
        dpi_context(old_context)
    status = 'window_found' if len(windows) == 1 else 'ambiguous_windows' if windows else 'no_visible_game_window'
    return {'source': 'win32_read_only_window_probe', 'status': status,
            'game_input_sent': False, 'actionable': False,
            'coordinate_space': 'physical_screen_pixels', 'windows': windows, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = probe()
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
