"""系统托盘协调器：托盘图标、托盘菜单、状态提示与最小化管理。"""

import os
import sys
import webbrowser

from PyQt5 import QtCore, QtGui, QtWidgets

from . import tts


def _app_icon_path():
    """Locate app.ico for both source and frozen (PyInstaller) runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # Script is at pet/tray.py, project root is two levels up.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "app.ico")
    return path if os.path.isfile(path) else None


class PetTrayCoordinator(QtCore.QObject):
    """协调系统托盘图标、右键托盘菜单及与主窗口的显隐交互。"""

    def __init__(self, window):
        parent = window if isinstance(window, QtCore.QObject) else None
        super().__init__(parent)
        self.window = window
        self._tray = None
        self._tray_menu = None
        self._tray_hint_shown = False
        self._setup_tray()

    def is_available(self):
        """系统托盘是否可用且已成功创建。"""
        return self._tray is not None

    @property
    def tray_icon(self):
        return self._tray

    def _setup_tray(self):
        """常驻系统托盘：关闭窗口只是隐藏，服务生命周期不再被误关打断。

        托盘菜单：显示/隐藏、聊天、TTS、静音、语音克隆启停、退出。
        语音克隆菜单项每次弹出时按真实状态重建（与右键菜单同源）。
        """
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QtWidgets.QSystemTrayIcon(self.parent())
        icon = _app_icon_path()
        if icon:
            self._tray.setIcon(QtGui.QIcon(icon))
        self.update_tooltip()
        self._tray_menu = QtWidgets.QMenu()
        self._tray_menu.aboutToShow.connect(self.rebuild_menu)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def update_tooltip(self):
        """更新托盘图标悬浮文案（含当前角色与语音克隆服务状态）。"""
        if not self._tray:
            return
        st = tts.clone_state()
        label = {"running": "语音克隆：运行中",
                 "starting": "语音克隆：加载中",
                 "stopped": "语音克隆：未启动"}.get(st, st)
        name = getattr(self.window.char, "display_name", "阿米娅")
        self._tray.setToolTip("阿米娅桌面宠物 · %s · %s" % (name, label))

    def rebuild_menu(self):
        """重新构建托盘右键菜单。"""
        if not self._tray_menu:
            return
        m = self._tray_menu
        m.clear()
        vis = m.addAction("隐藏桌宠" if self.window.isVisible() else "显示桌宠")
        vis.triggered.connect(self.toggle_visible)
        m.addAction("聊天…", self.tray_chat)
        m.addSeparator()

        tts_act = m.addAction("朗读回答（语音合成）")
        tts_act.setCheckable(True)
        tts_supported = getattr(self.window, "_tts_supported", True)
        tts_on = getattr(self.window, "_tts_on", False)
        tts_act.setEnabled(tts_supported and tts.available())
        tts_act.setChecked(tts_on)
        tts_act.toggled.connect(self.window._set_tts)

        mute = m.addAction("静音")
        mute.setCheckable(True)
        mute.setChecked(not self.window.voice.enabled)
        mute.toggled.connect(self.window._toggle_mute)
        m.addSeparator()

        if getattr(self.window, "_use_clone", False):
            state = tts.clone_state()
            if state == "running":
                m.addAction("停止语音克隆服务（释放显存）", self.window._stop_clone)
            elif state == "starting":
                loading = m.addAction("语音克隆服务加载中…")
                loading.setEnabled(False)
            else:
                m.addAction("启动语音克隆服务（AI 声线）", self.window._start_clone)
            m.addSeparator()

        m.addAction("退出", self.window._quit)

    def _on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.toggle_visible()
        elif reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self.show_pet()
            self.window.open_chat()

    def toggle_visible(self):
        """切换主窗口显示与隐藏。"""
        if self.window.isVisible():
            self.window.hide()
        else:
            self.show_pet()

    def show_pet(self):
        """将宠物窗口显示并置顶激活。"""
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def tray_chat(self):
        """从托盘激活聊天。"""
        self.show_pet()
        self.window.open_chat()

    def show_message(self, title, message,
                     icon=QtWidgets.QSystemTrayIcon.Information, timeout_ms=4000):
        """在托盘弹出系统气泡通知。"""
        if self._tray:
            self._tray.showMessage(title, message, icon, timeout_ms)

    def show_update_notification(self, tag, html_url):
        """弹出新版本发现通知，点击可跳转浏览器。"""
        if not self._tray:
            return
        msg = "发现新版本 %s，点击前往下载。" % tag
        try:
            self._tray.messageClicked.disconnect()
        except Exception:
            pass
        self._tray.messageClicked.connect(lambda: webbrowser.open(html_url))
        self._tray.showMessage("阿米娅桌面宠物 · 发现新版本", msg,
                               QtWidgets.QSystemTrayIcon.Information, 8000)

    def handle_close_event(self, event):
        """处理窗口关闭事件：拦截关闭并最小化到托盘。"""
        app = QtWidgets.QApplication.instance()
        saving = bool(getattr(app, "isSavingSession", lambda: False)()) if app else False
        quitting = getattr(self.window, "_quitting", False)
        if not self._tray or quitting or saving:
            self.window._quit()
            event.accept()
            return

        event.ignore()
        self.window.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            name = getattr(self.window.char, "display_name", "阿米娅")
            self._tray.showMessage(
                "%s还在" % name,
                "桌宠已最小化到托盘。右键托盘图标可退出，或从托盘菜单快速开关语音。",
                QtWidgets.QSystemTrayIcon.Information, 4000)
