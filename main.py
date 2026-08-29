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
from pet import logging as petlog
from pet.settings import Settings, characters_dirs


def _app_icon_path():
    """Locate app.ico for both source and frozen (PyInstaller) runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "app.ico")
    return path if os.path.isfile(path) else None


# 所有可能放置角色配置的目录（打包版：exe 旁 / 用户数据目录 / 内置副本）。
CHARACTERS_DIRS = characters_dirs()


def find_character(name=None):
    if name:
        for base in CHARACTERS_DIRS:
            path = os.path.join(base, name)
            if os.path.isfile(os.path.join(path, "config.json")):
                return path
        sys.exit(f"角色 '{name}' 不存在或缺少 config.json")
    configs = sorted(config for base in CHARACTERS_DIRS
                     for config in glob.glob(
                         os.path.join(base, "*", "config.json")))
    if not configs:
        sys.exit(f"在 {CHARACTERS_DIRS} 下没有找到任何角色")
    return os.path.dirname(configs[0])


def main():
    # 先装全局异常钩子：打包版 console=False，所有未捕获异常写入 pet.log
    # （%APPDATA%\AmiyaPet\pet.log），否则只能盲猜。
    petlog.init_logging()

    # 单实例守护：已有实例在运行则让它回到前台，本实例退出——
    # 避免两个桌宠抢全局热键 / 双份动画。
    from pet import single_instance
    if not single_instance.acquire():
        petlog.log("已有实例在运行，请求显示后退出")
        single_instance.request_show()
        sys.exit(0)

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
    petlog.log("角色: %s (%s)" % (character.key, character.display_name))
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
