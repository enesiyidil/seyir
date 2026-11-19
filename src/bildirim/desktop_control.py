"""Mouse and keyboard control for the screen agent."""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import c_double, c_int32, c_uint32, c_void_p
from pathlib import Path

_CG = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
)
_CF = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)


class _Point(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


_CG.CGEventCreateMouseEvent.restype = c_void_p
_CG.CGEventCreateMouseEvent.argtypes = [c_void_p, c_uint32, _Point, c_uint32]
_CG.CGEventCreateScrollWheelEvent2.restype = c_void_p
_CG.CGEventCreateScrollWheelEvent2.argtypes = [c_void_p, c_uint32, c_uint32, c_int32, c_int32, c_int32]
_CG.CGEventPost.argtypes = [c_uint32, c_void_p]
_CF.CFRelease.argtypes = [c_void_p]

_LEFT_DOWN = 1
_LEFT_UP = 2
_MOVE = 5
_LEFT_BUTTON = 0
_HID = 0
_LINE = 1


def _post(event: c_void_p) -> None:
    if not event:
        return
    _CG.CGEventPost(_HID, event)
    _CF.CFRelease(event)


def move(x: int, y: int) -> None:
    _post(_CG.CGEventCreateMouseEvent(None, _MOVE, _Point(x, y), _LEFT_BUTTON))


def click(x: int, y: int) -> None:
    point = _Point(int(x), int(y))
    _post(_CG.CGEventCreateMouseEvent(None, _MOVE, point, _LEFT_BUTTON))
    time.sleep(0.05)
    _post(_CG.CGEventCreateMouseEvent(None, _LEFT_DOWN, point, _LEFT_BUTTON))
    time.sleep(0.04)
    _post(_CG.CGEventCreateMouseEvent(None, _LEFT_UP, point, _LEFT_BUTTON))


def scroll(dx: int = 0, dy: int = 0) -> None:
    """Positive dy scrolls up. Positive dx scrolls right."""
    event = _CG.CGEventCreateScrollWheelEvent2(None, _LINE, 2, int(dy), int(-dx), 0)
    _post(event)


def screenshot(path: Path, *, window_id: int | None = None) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["/usr/sbin/screencapture", "-x", "-o", "-t", "jpg"]
    if window_id:
        cmd.extend(["-l", str(window_id)])
    else:
        cmd.append("-m")
    cmd.append(str(path))
    proc = subprocess.run(cmd, capture_output=True, check=False)
    return proc.returncode == 0 and path.is_file() and path.stat().st_size > 1000


def type_text(text: str) -> None:
    previous = subprocess.run(["pbpaste"], capture_output=True, check=False).stdout
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    finally:
        subprocess.run(["pbcopy"], input=previous, check=False)


def press(name: str) -> None:
    codes = {
        "return": 36,
        "enter": 36,
        "escape": 53,
        "esc": 53,
        "tab": 48,
        "space": 49,
        "left": 123,
        "right": 124,
        "down": 125,
        "up": 126,
        "delete": 51,
    }
    code = codes.get(name.lower().strip())
    if code is None:
        return
    subprocess.run(
        [
            "osascript",
            "-e",
            f'tell application "System Events" to key code {code}',
        ],
        capture_output=True,
        text=True,
        timeout=4,
        check=False,
    )


class _Size(ctypes.Structure):
    _fields_ = [("width", c_double), ("height", c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("origin", _Point), ("size", _Size)]


_CG.CGMainDisplayID.restype = c_uint32
_CG.CGDisplayBounds.argtypes = [c_uint32]
_CG.CGDisplayBounds.restype = _Rect
_CG.CGPreflightPostEventAccess.restype = ctypes.c_bool
_CG.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
_CG.CGEventCreateKeyboardEvent.argtypes = [c_void_p, ctypes.c_uint16, ctypes.c_bool]
_CG.CGEventCreateKeyboardEvent.restype = c_void_p
_CG.CGEventKeyboardSetUnicodeString.argtypes = [c_void_p, ctypes.c_ulong, ctypes.c_void_p]
_CG.CGEventSetIntegerValueField.argtypes = [c_void_p, c_uint32, ctypes.c_int64]


def desktop_permissions() -> dict[str, bool]:
    return {"screen_capture": _CG.CGPreflightScreenCaptureAccess(),
            "desktop_input": _CG.CGPreflightPostEventAccess()}


def _display_point(data: dict, x_key: str, y_key: str, bounds: _Rect) -> _Point:
    x, y = data.get(x_key), data.get(y_key)
    if any(type(n) not in (int, float) or not 0 <= n <= 1 for n in (x, y)):
        raise ValueError("Dokunuş ekranın dışında.")
    return _Point(bounds.origin.x + round(x * (bounds.size.width - 1)),
                  bounds.origin.y + round(y * (bounds.size.height - 1)))


def _keyboard_event(code: int, text: str = "") -> None:
    encoded = text.encode("utf-16-le")
    for down in (True, False):
        event = _CG.CGEventCreateKeyboardEvent(None, code, down)
        if not event:
            raise RuntimeError("Klavye olayı oluşturulamadı.")
        if encoded:
            _CG.CGEventKeyboardSetUnicodeString(event, len(encoded) // 2, encoded)
        _post(event)


def manual_control(data: dict) -> None:
    if not _CG.CGPreflightPostEventAccess():
        raise PermissionError("Mac’te botu çalıştıran uygulama için Erişilebilirlik iznini aç.")
    op = data.get("op")
    if op in ("click", "double", "right", "drag"):
        bounds = _CG.CGDisplayBounds(_CG.CGMainDisplayID())
        if bounds.size.width < 1 or bounds.size.height < 1:
            raise RuntimeError("Ana ekran bulunamadı.")
        point = _display_point(data, "x", "y", bounds)
        end = _display_point(data, "endX", "endY", bounds) if op == "drag" else point
        button = 1 if op == "right" else 0
        _post(_CG.CGEventCreateMouseEvent(None, _MOVE, point, 0))
        for count in range(1, 3 if op == "double" else 2):
            for kind, position in ((3 if button else _LEFT_DOWN, point),
                                   (4 if button else _LEFT_UP, end)):
                event = _CG.CGEventCreateMouseEvent(None, kind, position, button)
                if not event:
                    raise RuntimeError("Fare olayı oluşturulamadı.")
                _CG.CGEventSetIntegerValueField(event, 1, count)  # kCGMouseEventClickState
                _post(event)
                if kind == _LEFT_DOWN and op == "drag":
                    for step in range(1, 9):
                        pos = _Point(point.x + (end.x - point.x) * step / 8,
                                     point.y + (end.y - point.y) * step / 8)
                        _post(_CG.CGEventCreateMouseEvent(None, 6, pos, 0))
                        time.sleep(.012)
        return
    if op == "scroll":
        dy = data.get("dy")
        if type(dy) is not int or not -12 <= dy <= 12:
            raise ValueError("Kaydırma miktarı geçersiz.")
        scroll(dy=dy)
        return
    if op == "key":
        codes = {"enter": 36, "escape": 53, "tab": 48, "delete": 51,
                 "left": 123, "right": 124, "down": 125, "up": 126}
        name = data.get("name")
        if not isinstance(name, str) or name not in codes:
            raise ValueError("Tuş tanınmadı.")
        _keyboard_event(codes[name])
        return
    if op == "type":
        value = data.get("text")
        if not isinstance(value, str) or not 1 <= len(value) <= 2000:
            raise ValueError("1–2000 karakter gir.")
        value.encode("utf-16-le")
        for offset in range(0, len(value), 10):
            _keyboard_event(0, value[offset:offset+10])
        return
    raise ValueError("İşlem tanınmadı.")


_CG.CGEventSetFlags.argtypes = [c_void_p, ctypes.c_uint64]
_CG.CGEventCreate.argtypes = [c_void_p]
_CG.CGEventCreate.restype = c_void_p
_CG.CGEventGetLocation.argtypes = [c_void_p]
_CG.CGEventGetLocation.restype = _Point


def require_input() -> None:
    if not _CG.CGPreflightPostEventAccess():
        raise PermissionError("Mac’te Erişilebilirlik izni gerekiyor.")


def key_chord(code: int, flags: int = 0) -> None:
    require_input()
    modifiers = [(bit, scancode) for bit, scancode in
                 [(1 << 17, 56), (1 << 18, 59), (1 << 19, 58), (1 << 20, 55)] if flags & bit]
    held = 0
    def post_key(key: int, down: bool, mask: int) -> None:
        event = _CG.CGEventCreateKeyboardEvent(None, key, down)
        if not event:
            raise RuntimeError("Klavye olayı oluşturulamadı.")
        _CG.CGEventSetFlags(event, mask)
        _post(event)
    try:
        for bit, scancode in modifiers:
            held |= bit
            post_key(scancode, True, held)
        # Hardware arrow events carry the keypad and function flags on macOS.
        key_flags = flags | ((1 << 21) | (1 << 23) if code in (123,124,125,126) else 0)
        post_key(code, True, key_flags)
        time.sleep(.035)
        post_key(code, False, key_flags)
    finally:
        for bit, scancode in reversed(modifiers):
            if held & bit:
                held &= ~bit
                post_key(scancode, False, held)


def pointer_command(op: str, direction: str, distance: int) -> None:
    require_input()
    bounds = _CG.CGDisplayBounds(_CG.CGMainDisplayID())
    event = _CG.CGEventCreate(None)
    if not event or min(bounds.size.width, bounds.size.height) <= 1:
        raise RuntimeError("İmleç konumu okunamadı.")
    point = _CG.CGEventGetLocation(event)
    _CF.CFRelease(event)
    x, y = point.x - bounds.origin.x, point.y - bounds.origin.y
    if not (0 <= x < bounds.size.width and 0 <= y < bounds.size.height):
        raise RuntimeError("İmleç paylaşılan ana ekranın dışında.")
    if op == "move":
        dx, dy = {"saga":(1,0), "sola":(-1,0), "asagi":(0,1), "yukari":(0,-1)}[direction]
        move(round(bounds.origin.x + min(max(x + dx * distance, 0), bounds.size.width - 1)),
             round(bounds.origin.y + min(max(y + dy * distance, 0), bounds.size.height - 1)))
    else:
        manual_control({"op":op, "x":x/(bounds.size.width-1), "y":y/(bounds.size.height-1)})
