"""Fast read-only capture of the game window, inside this process. It never sends input."""
import ctypes
import struct
import zlib
from ctypes import wintypes

# The same samples the capture script averages, so the lit-button rule keeps its calibration.
BUTTON_XS = range(1515, 1601, 5)
BUTTON_YS = range(480, 516, 5)
FRAME_SIZE = (1920, 1080)
PW_CLIENTONLY_FULLCONTENT = 3


def average_rgb(bgra, width, xs=BUTTON_XS, ys=BUTTON_YS):
    red = green = blue = samples = 0
    for y in ys:
        for x in xs:
            at = (y * width + x) * 4
            blue += bgra[at]
            green += bgra[at + 1]
            red += bgra[at + 2]
            samples += 1
    return [round(red / samples), round(green / samples), round(blue / samples)]


def encode_png(bgra, width, height, level=1):
    """Standard library only. Level 1 keeps a full frame near a tenth of a second."""
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    stride = width * 3
    rows = b''.join(b'\0' + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows, level)) + chunk(b'IEND', b'')


class BitmapInfo(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
                ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


class GameScreen:
    """Copies the game window with PrintWindow, the source the button colors were measured from."""

    def __init__(self, window):
        self.hwnd, self.width, self.height = window['hwnd'], window['width'], window['height']
        self.user, self.gdi = ctypes.WinDLL('user32'), ctypes.WinDLL('gdi32')
        self.user.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.user.GetDC.restype = wintypes.HDC
        self.user.GetDC.argtypes = [wintypes.HWND]
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        self.gdi.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self.gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self.gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                       ctypes.POINTER(BitmapInfo), wintypes.UINT]
        screen = self.user.GetDC(None)
        self.memory = self.gdi.CreateCompatibleDC(screen)
        self.bitmap = self.gdi.CreateCompatibleBitmap(screen, self.width, self.height)
        self.gdi.SelectObject(self.memory, self.bitmap)
        self.user.ReleaseDC(None, screen)
        # A negative height asks for rows top first.
        self.info = BitmapInfo(ctypes.sizeof(BitmapInfo), self.width, -self.height, 1, 32, 0, 0, 0, 0, 0, 0)
        self.buffer = ctypes.create_string_buffer(self.width * self.height * 4)

    def frame(self):
        """The window's pixels as top-down BGRA bytes."""
        if not self.user.PrintWindow(self.hwnd, self.memory, PW_CLIENTONLY_FULLCONTENT):
            raise OSError('window capture failed')
        if self.gdi.GetDIBits(self.memory, self.bitmap, 0, self.height, self.buffer, ctypes.byref(self.info), 0) != self.height:
            raise OSError('reading the captured pixels failed')
        return self.buffer.raw

    def button_rgb(self):
        if (self.width, self.height) != FRAME_SIZE:
            raise ValueError('End Turn color is only measured at 1920x1080')
        return average_rgb(self.frame(), self.width)

    def save(self, path, pixels=None):
        with open(path, 'wb') as out:
            out.write(encode_png(pixels if pixels is not None else self.frame(), self.width, self.height))
