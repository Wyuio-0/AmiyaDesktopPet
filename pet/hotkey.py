"""System-wide hotkey (Windows) to summon the chat box even when unfocused.

Uses the Win32 RegisterHotKey API via ctypes (no extra dependency) plus a Qt
native event filter to catch WM_HOTKEY. No-op on non-Windows platforms, so the
pet still runs everywhere — it just loses the global shortcut off Windows.
"""

import ctypes
import sys

from PyQt5 import QtCore

_IS_WIN = sys.platform == "win32"
if _IS_WIN:
    from ctypes import wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_MODS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
         "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN, "cmd": MOD_WIN}


def _vk_for(key):
    """Map a single key name to its Win32 virtual-key code (None if unknown)."""
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())            # A-Z / 0-9
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)          # F1-F24
    return None


def parse_hotkey(spec):
    """'alt+a' -> (modifiers|MOD_NOREPEAT, vk). None if unparseable.

    Requires at least one modifier plus one key, so a bare letter can't grab
    every keypress system-wide.
    """
    if not spec:
        return None
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    mods, key = 0, None
    for p in parts:
        if p in _MODS:
            mods |= _MODS[p]
        else:
            key = p
    if not key or not mods:
        return None
    vk = _vk_for(key)
    if vk is None:
        return None
    return mods | MOD_NOREPEAT, vk


class GlobalHotkey(QtCore.QObject):
    """Registers a system-wide hotkey and emits `activated` when pressed.

    Install once; call unregister() on quit. Safe no-op off Windows or when the
    spec is invalid / the combo is already taken by another app.
    """

    activated = QtCore.pyqtSignal()
    _next_id = 1

    def __init__(self, hwnd, spec, parent=None):
        super().__init__(parent)
        self._id = GlobalHotkey._next_id
        GlobalHotkey._next_id += 1
        self._hwnd = int(hwnd)
        self._registered = False
        self._filter = None
        parsed = parse_hotkey(spec)
        if _IS_WIN and parsed is not None:
            mods, vk = parsed
            if ctypes.windll.user32.RegisterHotKey(
                    wintypes.HWND(self._hwnd), self._id, mods, vk):
                self._registered = True
                # installNativeEventFilter does NOT take ownership, so we must
                # keep a reference: otherwise the filter is garbage-collected as
                # soon as __init__ returns and WM_HOTKEY is never delivered —
                # the hotkey registers but silently does nothing.
                self._filter = _Filter(self)
                QtCore.QAbstractEventDispatcher.instance().installNativeEventFilter(
                    self._filter)

    @property
    def active(self):
        return self._registered

    def handle(self, wparam):
        if wparam == self._id:
            self.activated.emit()
            return True
        return False

    def unregister(self):
        if self._registered and _IS_WIN:
            ctypes.windll.user32.UnregisterHotKey(
                wintypes.HWND(self._hwnd), self._id)
            if self._filter is not None:
                QtCore.QAbstractEventDispatcher.instance(
                    ).removeNativeEventFilter(self._filter)
                self._filter = None
            self._registered = False


class _Filter(QtCore.QAbstractNativeEventFilter):
    """Routes WM_HOTKEY messages from the Windows event loop to the owner."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):
        if _IS_WIN and event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                if self._owner.handle(int(msg.wParam)):
                    return True, 0
        return False, 0
