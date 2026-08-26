"""统一设置对话框：语音 / 热键 / 通用。

语音：朗读回答（TTS）开关、静音、音量滑杆。
热键：聊天 / 翻译剪贴板 / OCR 截图 三个组合键的可视化改键（按当前角色保存，
     通过 owner.prefs["hotkeys_<角色>"] 覆盖 config.json 的默认值）。
通用：默认角色（下次启动生效）、考试倒计时徽章开关。

保存时复用 owner 上已有的 setter（_set_tts / _toggle_mute / _on_volume_slider /
_apply_hotkey_overrides / _refresh_exam_badge），保证与右键菜单行为一致。
"""

from PyQt5 import QtCore, QtGui, QtWidgets

from . import logging as petlog
from . import theme, tts, updater

# DIALOG_QSS 未覆盖的控件：页签、滑杆、组合键输入框——补上统一的 Terminal 风格。
_EXTRA_QSS = """
QTabWidget::pane { border: 1px solid %s; border-radius: 4px; background: %s; }
QTabBar::tab { background: transparent; color: %s; padding: 8px 18px;
               font-size: 18px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: %s; border-bottom: 2px solid %s; }
QTabBar::tab:hover { color: %s; }
QSlider::groove:horizontal { height: 4px; background: %s; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: %s;
                             border-radius: 7px; }
QKeySequenceEdit { background: %s; color: %s; border: 1px solid %s;
                   border-radius: 4px; padding: 6px 8px;
                   selection-background-color: %s; font-family: %s; }
QKeySequenceEdit:focus { border: 1px solid %s; background: %s; }
""" % (
    theme.FLOAT_GRID, theme.DLG_BG,
    theme.FLOAT_TEXT_DIM, theme.FLOAT_ACCENT, theme.FLOAT_GOLD, theme.FLOAT_TEXT,
    theme.FLOAT_GRID, theme.FLOAT_GOLD,
    theme.DLG_FIELD, theme.FLOAT_TEXT, theme.FLOAT_GRID,
    theme.FLOAT_ACCENT, theme.MONO,
    theme.FLOAT_ACCENT, theme.DLG_FIELD_FOCUS,
)


def _spec_to_ks(spec):
    """'alt+a' -> QKeySequence('Alt+A')（无法识别的修饰键按普通键处理）。"""
    s = str(spec or "").strip()
    if not s:
        return QtGui.QKeySequence()
    mods, key = [], ""
    for p in s.split("+"):
        pl = p.strip().lower()
        if pl == "alt":
            mods.append("Alt")
        elif pl in ("ctrl", "control"):
            mods.append("Ctrl")
        elif pl == "shift":
            mods.append("Shift")
        elif pl in ("win", "super", "cmd", "meta"):
            mods.append("Meta")
        else:
            key = p.strip().upper()
    return QtGui.QKeySequence("+".join(mods + ([key] if key else [])))


def _ks_to_spec(ks):
    """QKeySequence -> 'alt+a'（可写回配置的小写格式）。"""
    s = ks.toString(QtGui.QKeySequence.PortableText)
    if not s:
        return ""
    mods = {"Alt": "alt", "Ctrl": "ctrl", "Shift": "shift", "Meta": "win"}
    parts = []
    for p in s.split("+"):
        pl = p.strip()
        parts.append(mods.get(pl, pl.lower()))
    return "+".join(parts)


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(540)
        self.setStyleSheet(theme.DIALOG_QSS + _EXTRA_QSS)
        self._build()
        self._load()

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QtWidgets.QLabel("SETTINGS", self)
        head.setObjectName("TerminalTitle")
        root.addWidget(head)
        sub = QtWidgets.QLabel("桌宠设置：语音 / 热键 / 通用。", self)
        sub.setObjectName("TerminalSubTitle")
        root.addWidget(sub)

        self.tabs = QtWidgets.QTabWidget(self)
        root.addWidget(self.tabs, 1)

        # ── 语音 ─────────────────────────────────────────────────────
        v = QtWidgets.QWidget(self)
        vl = QtWidgets.QVBoxLayout(v)
        vl.setSpacing(10)
        self.cb_tts = QtWidgets.QCheckBox("朗读回答（语音合成）", v)
        self.cb_mute = QtWidgets.QCheckBox("静音", v)
        self.cb_clone_autostop = QtWidgets.QCheckBox(
            "按钮启动的语音克隆 10 分钟未使用自动停止（默认关闭）", v)
        volrow = QtWidgets.QHBoxLayout()
        volrow.addWidget(QtWidgets.QLabel("音量", v))
        self.vol_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, v)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.valueChanged.connect(self._on_volume)
        self.vol_label = QtWidgets.QLabel("", v)
        volrow.addWidget(self.vol_slider, 1)
        volrow.addWidget(self.vol_label)
        vl.addWidget(self.cb_tts)
        vl.addWidget(self.cb_mute)
        vl.addWidget(self.cb_clone_autostop)
        vl.addLayout(volrow)
        vl.addStretch(1)
        self.tabs.addTab(v, "语音")

        # ── 热键 ─────────────────────────────────────────────────────
        h = QtWidgets.QWidget(self)
        hl = QtWidgets.QFormLayout(h)
        hl.setHorizontalSpacing(12)
        hl.setVerticalSpacing(12)
        self.hk_chat = QtWidgets.QKeySequenceEdit(h)
        self.hk_translate = QtWidgets.QKeySequenceEdit(h)
        self.hk_ocr = QtWidgets.QKeySequenceEdit(h)
        hl.addRow("聊天", self.hk_chat)
        hl.addRow("翻译剪贴板", self.hk_translate)
        hl.addRow("OCR 截图", self.hk_ocr)
        note = QtWidgets.QLabel(
            "热键按当前角色保存；被其他程序占用的组合键会注册失败。", h)
        note.setStyleSheet("color:%s;font-size:13px;" % theme.FLOAT_TEXT_DIM)
        hl.addRow("", note)
        self.tabs.addTab(h, "热键")

        # ── 通用 ─────────────────────────────────────────────────────
        g = QtWidgets.QWidget(self)
        gl = QtWidgets.QFormLayout(g)
        gl.setHorizontalSpacing(12)
        gl.setVerticalSpacing(12)
        self.cb_char = QtWidgets.QComboBox(g)
        for c in self.owner._available_characters():
            self.cb_char.addItem(c.display_name, c.key)
        self.cb_exam = QtWidgets.QCheckBox("显示考试倒计时常驻徽章", g)
        self.cb_check_updates = QtWidgets.QCheckBox("启动时检查更新", g)
        gl.addRow("默认角色", self.cb_char)
        gl.addRow("", self.cb_exam)
        gl.addRow("", self.cb_check_updates)
        self.ver_label = QtWidgets.QLabel(
            "当前版本 v%s" % updater.APP_VERSION, g)
        self.btn_check_updates = QtWidgets.QPushButton("检查更新…", g)
        self.btn_check_updates.clicked.connect(self._check_now)
        hrow = QtWidgets.QHBoxLayout()
        hrow.addWidget(self.ver_label)
        hrow.addStretch(1)
        hrow.addWidget(self.btn_check_updates)
        gl.addRow("版本", hrow)
        note2 = QtWidgets.QLabel("默认角色在下一次启动时生效。", g)
        note2.setStyleSheet("color:%s;font-size:13px;" % theme.FLOAT_TEXT_DIM)
        gl.addRow("", note2)
        self.tabs.addTab(g, "通用")

        # ── 按钮 ─────────────────────────────────────────────────────
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        self.btn_save = QtWidgets.QPushButton("保存", self)
        self.btn_cancel = QtWidgets.QPushButton("取消", self)
        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_cancel)
        root.addLayout(btns)

    def _load(self):
        o = self.owner
        self.cb_tts.setChecked(o._tts_on)
        self.cb_tts.setEnabled(o._tts_supported and tts.available())
        self.cb_mute.setChecked(not o.voice.enabled)
        self.cb_clone_autostop.setChecked(
            o.prefs.get("clone_manual_autostop", False))
        vol = int(round(o.voice.volume * 100))
        self.vol_slider.setValue(vol)
        self._on_volume(vol)
        ov = o.prefs.get("hotkeys_" + o.char.key, {}) or {}
        self.hk_chat.setKeySequence(_spec_to_ks(
            ov.get("chat") or o.char.cfg.get("hotkey", "alt+a")))
        self.hk_translate.setKeySequence(_spec_to_ks(
            ov.get("translate") or o.char.cfg.get("hotkey_translate", "alt+t")))
        self.hk_ocr.setKeySequence(_spec_to_ks(
            ov.get("ocr") or o.char.cfg.get("hotkey_ocr", "alt+s")))
        idx = self.cb_char.findData(o.prefs.get("character", ""))
        if idx >= 0:
            self.cb_char.setCurrentIndex(idx)
        self.cb_exam.setChecked(o.prefs.get("exam_badge", True))
        self.cb_check_updates.setChecked(o.prefs.get("check_updates", True))

    def _check_now(self):
        """立即检查更新（结果以气泡/托盘提示显示）。"""
        self.owner._check_updates(silent=False)

    def _on_volume(self, value):
        self.vol_label.setText("%d%%" % value)

    def _save(self):
        from .hotkey import parse_hotkey
        o = self.owner
        try:
            # 校验热键格式（至少一个修饰键 + 一个键，否则全局注册会失败）
            specs = {"chat": _ks_to_spec(self.hk_chat.keySequence()),
                     "translate": _ks_to_spec(self.hk_translate.keySequence()),
                     "ocr": _ks_to_spec(self.hk_ocr.keySequence())}
            bad = [k for k, s in specs.items() if s and parse_hotkey(s) is None]
            if bad:
                QtWidgets.QMessageBox.warning(
                    self, "热键无效",
                    "以下热键格式无效（需要一个修饰键+一个按键）：\n%s"
                    % ", ".join(bad))
                return
            o._set_tts(self.cb_tts.isChecked())
            o._toggle_mute(self.cb_mute.isChecked())
            o._on_volume_slider(self.vol_slider.value())
            o.prefs.set("clone_manual_autostop",
                        self.cb_clone_autostop.isChecked())
            tts.set_manual_auto_stop(self.cb_clone_autostop.isChecked())
            # 热键只保存到 prefs；真正重注册由窗口在对话框关闭后执行
            # （见 PetWindow._open_settings），避免在模态事件循环里碰
            # RegisterHotKey/原生事件过滤器导致进程崩溃。
            o.prefs.set("hotkeys_" + o.char.key, specs)
            key = self.cb_char.currentData()
            if key:
                o.prefs.set("character", key)
            o.prefs.set("exam_badge", self.cb_exam.isChecked())
            o.prefs.set("check_updates", self.cb_check_updates.isChecked())
            o._refresh_exam_badge()
        except Exception:
            import traceback
            petlog.log("settings save 异常:\n%s" % traceback.format_exc())
            QtWidgets.QMessageBox.warning(
                self, "保存失败", "保存设置时出错，已记录到 pet.log。")
            return
        self.accept()
