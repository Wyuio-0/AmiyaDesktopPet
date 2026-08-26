"""打包版错误日志：%APPDATA%\\AmiyaPet\\pet.log（可用环境变量 AMIYA_LOG_FILE 覆盖）。

PyInstaller 打包时 console=False，所有 stderr 输出都消失，运行时异常只能靠
盲猜。本模块在启动时安装三层钩子，把异常写进日志文件：

1. sys.excepthook —— 主线程未捕获异常（含完整 traceback）
2. threading.excepthook —— stdlib 线程未捕获异常（Python 3.8+）
3. sys.unraisablehook —— PyQt 插槽等"不可抛出"异常（很多静默失败走这里）
4. Qt 消息处理器（qInstallMessageHandler）—— qWarning/qCritical 等
   （如 "QThread: Destroyed while thread is still running"）

另提供 log() 供业务代码记录关键事件（启动、热键注册结果、切角色等）。
日志超过 MAX_BYTES 时轮转为 pet.log.bak，不会无限增长。
"""

import os
import sys
import threading
import traceback
from datetime import datetime

MAX_BYTES = 5 * 1024 * 1024

_log_path = None
_installed = False


def _config_dir():
    try:
        from .settings import config_dir
        return config_dir()
    except Exception:
        return os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), "AmiyaPet")


def log_path():
    """日志文件路径（AMIYA_LOG_FILE 可覆盖，测试/定制用）。"""
    global _log_path
    if _log_path is None:
        _log_path = os.environ.get("AMIYA_LOG_FILE") or os.path.join(
            _config_dir(), "pet.log")
    return _log_path


def _write(level, text):
    path = log_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("[%s] [%s] %s\n" % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, text))
    except Exception:
        pass            # 日志失败绝不影响主程序


def log(message):
    """业务日志：记录关键事件（启动、热键注册、切角色、退出等）。"""
    _write("INFO", str(message))


def _rotate_if_needed():
    path = log_path()
    try:
        if os.path.isfile(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".bak")
    except Exception:
        pass


def _excepthook(exc_type, exc, tb):
    _write("EXC", "".join(traceback.format_exception(exc_type, exc, tb)).strip())
    sys.__excepthook__(exc_type, exc, tb)   # 保留默认 stderr 输出


def _thread_excepthook(args):
    _write("THREAD", "".join(traceback.format_exception(
        args.exc_type, args.exc_value, args.exc_traceback)).strip())


def _unraisable_hook(args):
    try:
        tb = ("\n" + "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
              if args.exc_traceback is not None else "")
    except Exception:
        tb = ""
    _write("UNRAISABLE", "%s: %s%s" % (args.exc_type.__name__,
                                       args.exc_value, tb))


def _qt_handler(mode, _context, message):
    # QtMsgType: 0=Debug 1=Warning 2=Critical 3=Fatal 4=Info 5=System
    if mode in (1, 2, 3):        # 只记 Warning 及以上，避免正常信息刷屏
        _write({1: "QWarning", 2: "QCritical", 3: "QFatal"}[mode], str(message))


def init_logging():
    """安装全局异常/日志钩子；幂等。返回日志文件路径。"""
    global _installed
    if _installed:
        return log_path()
    _installed = True
    try:
        os.makedirs(os.path.dirname(log_path()), exist_ok=True)
    except Exception:
        pass
    _rotate_if_needed()
    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook
    if hasattr(sys, "unraisablehook"):
        sys.unraisablehook = _unraisable_hook
    try:
        from PyQt5 import QtCore
        QtCore.qInstallMessageHandler(_qt_handler)
    except Exception:
        pass
    _write("INFO", "=== Amiya Desktop Pet 启动 ===")
    log("frozen=%s python=%s logfile=%s" % (
        getattr(sys, "frozen", False), sys.version.split()[0], log_path()))
    return log_path()
