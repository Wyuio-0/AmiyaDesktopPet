"""单实例守护（Windows）。

第二个实例启动时通过**命名互斥体**检测到已有实例在运行，广播一条系统级
注册窗口消息让旧实例回到前台，然后自身退出——避免两个桌宠抢全局热键、
跑双份动画、重复注册托盘。

非 Windows 平台直接放行（互斥体/消息都是 Win32 API）。
"""

import ctypes
import sys

_MUTEX_NAME = "AmiyaDesktopPet_SingleInstance"
_SHOW_MSG = "AmiyaDesktopPet_ShowRequest"

_mutex = None


def acquire():
    """尝试持有单实例互斥体；返回 False 表示已有实例在运行。"""
    global _mutex
    if sys.platform != "win32":
        return True
    try:
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            return False
    except Exception:
        pass    # 互斥体失败就放行，别让守护本身挡住启动
    return True


def request_show():
    """广播「显示请求」给已有实例（检测到重复启动时调用），随后本实例退出。"""
    if sys.platform != "win32":
        return
    try:
        msg = ctypes.windll.user32.RegisterWindowMessageW(_SHOW_MSG)
        # HWND_BROADCAST + SMTO_ABORTIFHUNG：发完不等太久，防止旧实例卡死拖住新实例
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, msg, 0, 0, 0x0002, 1000, None)
    except Exception:
        pass


def show_message_id():
    """本进程用于接收「显示请求」的窗口消息 id（与发送方一致，系统级唯一）。"""
    if sys.platform != "win32":
        return None
    try:
        return ctypes.windll.user32.RegisterWindowMessageW(_SHOW_MSG)
    except Exception:
        return None
