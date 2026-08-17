"""Desktop pet launcher.

Usage:
    python main.py [character_name]

`character_name` is a folder under ./characters (default: the first one found).
"""

import glob
import os
import sys

from PyQt5 import QtCore, QtGui, QtWidgets

from pet import Character, PetWindow
from pet.settings import Settings


def _app_icon_path():
    """Locate app.ico for both source and frozen (PyInstaller) runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "app.ico")
    return path if os.path.isfile(path) else None


def _characters_dir():
    """Locate the characters folder for both source and frozen (exe) runs.

    When frozen, prefer a `characters/` next to the .exe (so users can drop in
    new characters), otherwise fall back to the copy bundled inside the exe.
    """
    if getattr(sys, "frozen", False):
        external = os.path.join(os.path.dirname(sys.executable), "characters")
        if os.path.isdir(external):
            return external
        return os.path.join(sys._MEIPASS, "characters")
    return os.path.join(os.path.dirname(__file__), "characters")


CHARACTERS_DIR = _characters_dir()


def find_character(name=None):
    if name:
        path = os.path.join(CHARACTERS_DIR, name)
        if os.path.isfile(os.path.join(path, "config.json")):
            return path
        sys.exit(f"角色 '{name}' 不存在或缺少 config.json")
    configs = sorted(glob.glob(os.path.join(CHARACTERS_DIR, "*", "config.json")))
    if not configs:
        sys.exit(f"在 {CHARACTERS_DIR} 下没有找到任何角色")
    return os.path.dirname(configs[0])


def main():
    # High-DPI scaling is enabled by default in PyQt5 5.15+; the explicit
    # attribute is deprecated and prints a runtime warning.
    app = QtWidgets.QApplication(sys.argv)

    icon_path = _app_icon_path()
    if icon_path:
        app.setWindowIcon(QtGui.QIcon(icon_path))

    arg_name = sys.argv[1] if len(sys.argv) > 1 else None
    saved_name = None if arg_name else Settings().get("character")
    try:
        char_path = find_character(arg_name or saved_name)
    except SystemExit:
        if arg_name:
            raise
        char_path = find_character(None)
    character = Character(char_path)
    window = PetWindow(character)
    window.show()

    # Run at below-normal priority so the desktop pet never fights the user's
    # foreground apps for CPU time.  BELOW_NORMAL is one notch above idle —
    # animations stay smooth but browsers/IDEs/games always win contention.
    if sys.platform == "win32":
        import ctypes
        BELOW_NORMAL = 0x00004000
        ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(), BELOW_NORMAL)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
