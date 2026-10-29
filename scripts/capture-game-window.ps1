param([string]$OutputPath = '.data/game-window.png')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class HearthWindowCapture {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr value);
}
'@
$games = @(Get-Process -Name Hearthstone -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 })
if ($games.Count -ne 1) { throw 'Expected one Hearthstone game window.' }
$gameWindow = $games[0].MainWindowHandle
if ([HearthWindowCapture]::IsIconic($gameWindow)) { throw 'Game window is minimized.' }
$oldDpi = [HearthWindowCapture]::SetThreadDpiAwarenessContext([IntPtr](-4))
if ($oldDpi -eq [IntPtr]::Zero) { throw 'Could not establish physical-pixel DPI context.' }
$bitmap = $null
$graphics = $null
$dc = [IntPtr]::Zero
try {
    $rectangle = New-Object HearthWindowCapture+RECT
    if (-not [HearthWindowCapture]::GetClientRect($gameWindow, [ref]$rectangle)) { throw 'Client rectangle unavailable.' }
    $width = $rectangle.Right - $rectangle.Left
    $height = $rectangle.Bottom - $rectangle.Top
    if ($width -le 0 -or $height -le 0 -or $width -gt 8192 -or $height -gt 8192) { throw 'Unsupported capture dimensions.' }
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    # PW_CLIENTONLY | PW_RENDERFULLCONTENT. Captures this window, not the desktop.
    $captured = [HearthWindowCapture]::PrintWindow($gameWindow, $dc, 3)
    $graphics.ReleaseHdc($dc)
    $dc = [IntPtr]::Zero
    if (-not $captured) { throw 'Window capture failed.' }
    $destination = [IO.Path]::GetFullPath($OutputPath)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
    $bitmap.Save($destination, [System.Drawing.Imaging.ImageFormat]::Png)
    $yellow = 0
    $samples = 0
    if ($width -eq 1920 -and $height -eq 1080) {
        for ($x = 1515; $x -le 1600; $x += 5) {
            for ($y = 480; $y -le 515; $y += 5) {
                $color = $bitmap.GetPixel($x, $y)
                $samples++
                if ($color.R -gt 140 -and $color.G -gt 120 -and $color.B -lt 100) { $yellow++ }
            }
        }
    }
    $fraction = if ($samples -gt 0) { $yellow / $samples } else { 0 }
    @{ source = 'read_only_game_window_capture'; pid = $games[0].Id; hwnd = $gameWindow.ToInt64(); width = $width; height = $height; image = $destination; end_turn_yellow_fraction = $fraction; game_input_sent = $false } | ConvertTo-Json
} finally {
    if ($dc -ne [IntPtr]::Zero) { $graphics.ReleaseHdc($dc) }
    if ($null -ne $graphics) { $graphics.Dispose() }
    if ($null -ne $bitmap) { $bitmap.Dispose() }
    [HearthWindowCapture]::SetThreadDpiAwarenessContext($oldDpi) | Out-Null
}
