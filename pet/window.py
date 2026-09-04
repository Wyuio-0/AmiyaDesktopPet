"""Frameless, always-on-top, click-through-transparent desktop pet window."""

import glob
import json
import os
import random
import sys
import traceback
import webbrowser
from datetime import date, datetime, timedelta

import cv2
from PyQt5 import QtCore, QtGui, QtWidgets

from .ai import AmiyaBrain
from .character import Character
from .focus import PetFocusToolsManager
from .frames import key_frame
from .hotkey import GlobalHotkey
from .info_panel import InfoPanel, PAGE_OCR, PAGE_SCHEDULE, PAGE_TASKS
from .input_controller import PetInputController
from .menu import PetContextMenuBuilder
from .ocr import OcrError, ocr_image, summarize_ai
from .region_select import RegionSelect
from .settings import Settings, characters_dirs
from .translate import TranslationPopup, TranslateWorker
from .tray import PetTrayCoordinator
from .voice import VoicePlayer
from . import actions, knowledge, logging as petlog, memory, theme, tts
from . import single_instance, updater


class CloneStateProbe(QtCore.QThread):
    """One-shot background probe of the voice-clone service state.

    Refreshes tts.clone_state() off the GUI thread so the context menu never
    blocks on the /ping round-trip (up to 0.6 s while the model is loading).
    A short-lived thread is started every few seconds; the cached value is
    read synchronously by the menu.
    """

    def run(self):
        tts.refresh_clone_state()


class UpdateCheckThread(QtCore.QThread):
    """后台查 GitHub 最新 Release；发现比当前版本新则发 result(dict)，否则 None。"""

    result = QtCore.pyqtSignal(object)

    def run(self):
        info = updater.latest_release()
        if info:
            tag, html, installer = info
            if updater.is_newer(tag):
                self.result.emit({"tag": tag, "html": html,
                                  "installer": installer})
                return
        self.result.emit(None)


class OcrWorker(QtCore.QThread):
    """截图 OCR + 翻译/总结，跑在后台线程，完成后经信号回 UI。

    done(text, result, error)：text 为识别出的原文，result 为译文/总结；
    error 非空表示失败（此时 text/result 为空）。
    """

    done = QtCore.pyqtSignal(str, str, str)

    def __init__(self, image, brain, mode, parent=None):
        super().__init__(parent)
        self.image = image
        self.brain = brain
        self.mode = mode

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            text, backend = ocr_image(self.image, self.brain.cfg)
        except OcrError as e:
            self.done.emit("", "", str(e))
            return
        except Exception as e:
            self.done.emit("", "", "OCR 识别出错：%s" % type(e).__name__)
            return
        if not text:
            self.done.emit("", "", "选区内没有识别到文字。")
            return
        if self.isInterruptionRequested():
            return

        if self.mode == "summarize":
            try:
                res = summarize_ai(text, self.brain.cfg)
                self.done.emit(text, res, "")
            except Exception as e:
                self.done.emit(text, "", "AI 总结失败：%s" % type(e).__name__)
            return

        # mode == "translate"
        try:
            from .translate import _translate_via_ai, _translate_via_google
            if self.brain.online:
                res = _translate_via_ai(text, self.brain.cfg)
            else:
                res = _translate_via_google(text)
            self.done.emit(text, res, "")
        except Exception as e:
            self.done.emit(text, "", "翻译失败：%s" % type(e).__name__)


class PetWindow(QtWidgets.QWidget):
    # Emitted from the AI worker thread when a reminder is scheduled; the queued
    # connection marshals it onto the UI thread where QTimer is safe to use.
    reminder_requested = QtCore.pyqtSignal(int, str)
    # AI 敏感操作确认：worker 线程通过它把"弹确认框"的请求投递到 GUI 线程。
    confirm_dialog_requested = QtCore.pyqtSignal(object)

    def __init__(self, character):
        super().__init__()
        self.char = character
        self.characters_dir = os.path.dirname(character.dir)
        self._cap = None            # cv2.VideoCapture of the current clip
        self._cur_action = None     # Action currently playing
        self._qimg = None           # keep a ref so QImage data stays alive
        self._alpha = None          # last frame alpha, for hit-testing
        self._drag_offset = None
        self._moved = False         # whether the current press turned into a drag
        self._loops_left = 0        # remaining loop_count replays this clip
        self._frames = []           # cached frames: raw BGRA ndarray 或 PNG bytes
        self._caching = False       # accumulate frames this pass?
        self._replay = False        # serving from cache instead of decoding?
        self._replay_i = 0          # next index into _frames when replaying
        self._cache_full = False    # budget exhausted for current clip?
        self._bbox = None           # cached body bbox (logical px) for current frame

        # Lazy background compression
        self._compress_timer = QtCore.QTimer(self)
        self._compress_timer.setSingleShot(False)
        self._compress_timer.timeout.connect(self._compress_tick)
        self._compress_i = 0
        self._skip_count = 0      # frame-skip counter (resets per clip)
        self._last_bgra = None    # last shown frame, reused when skipping
        self._first_frame_shown = False  # place window after first real frame

        self._mem = memory.get()    # adaptive memory manager

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool  # no taskbar entry
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        self.label = QtWidgets.QLabel(self)
        self.label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        # Render at physical pixel density so HiDPI screens stay crisp.
        self._dpr = self.screen().devicePixelRatio() if self.screen() else 1.0

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)

        # Idle -> sit -> sleep escalation
        self._rest_timer = QtCore.QTimer(self)
        self._rest_timer.setSingleShot(True)
        self._rest_timer.timeout.connect(self._rest_step)
        self._load_rest_config()

        # Persisted user preferences
        self.prefs = Settings()

        # Voice
        vcfg = self.char.cfg.get("voice", {})
        self.voice = VoicePlayer(
            self.char.dir,
            volume=self.prefs.get("volume", vcfg.get("volume", 0.7)),
            enabled=self.prefs.get("voice_enabled", vcfg.get("enabled", True)),
        )
        self._tts_cfg = vcfg.get("tts", {})
        self._tts_supported = bool(self._tts_cfg.get("enabled", True))
        self._tts_on = (self._tts_supported
                        and self.prefs.get("tts_on", True)
                        and tts.available())
        self._tts_worker = None
        self._tts_gen = 0
        self._use_clone = bool(self._tts_cfg.get("use_clone", True))
        self._clone_probe = None
        self._clone_probe_timer = QtCore.QTimer(self)
        self._clone_probe_timer.timeout.connect(self._schedule_clone_probe)
        if self._use_clone:
            self._clone_probe_timer.start(3000)
            self._schedule_clone_probe()
        self._clone_character = self._tts_cfg.get("clone_character",
            os.path.basename(os.path.normpath(self.char.dir)))

        # Debounce persisting the volume while the slider is being dragged.
        self._save_vol_timer = QtCore.QTimer(self)
        self._save_vol_timer.setSingleShot(True)
        self._save_vol_timer.timeout.connect(
            lambda: self.prefs.set("volume", self.voice.volume))

        # AI dialogue brain & popups
        persona = self.char.cfg.get("persona")
        self.brain = AmiyaBrain(self.char.dir, persona=persona,
                                fallback=self.char.cfg.get("fallback"))
        self.trans_popup = TranslationPopup()
        self._trans_worker = None
        self._ocr_worker = None
        self._info_panel_widget = None

        # 托盘模式与生命周期
        self._quitting = False
        self.confirm_dialog_requested.connect(self._run_confirm_dialog)
        self._clone_was_starting = False
        self._clone_notified = False
        tts.set_manual_auto_stop(self.prefs.get("clone_manual_autostop", False))

        # ── 关注点分离 (SoC) 独立控制器实例化 ─────────────────────────
        self.focus_mgr = PetFocusToolsManager(self)
        self.input_ctrl = PetInputController(self)
        self.tray_coord = PetTrayCoordinator(self)
        self.menu_builder = PetContextMenuBuilder(self)

        # AI 定时提醒路由
        self.reminder_requested.connect(
            self.focus_mgr.schedule_reminder, QtCore.Qt.QueuedConnection)
        actions.set_scheduler(self.reminder_requested.emit)

        self.play("start")
        self._setup_hotkey()
        self._attach_brain_services()

        # 自动更新：启动数秒后静默检查
        if self.prefs.get("check_updates", True):
            QtCore.QTimer.singleShot(4000, self._check_updates)

        # 空闲克隆停止检查
        self._clone_idle_timer = QtCore.QTimer(self)
        self._clone_idle_timer.timeout.connect(
            lambda: tts.maybe_stop_idle_clone(600))
        self._clone_idle_timer.start(60 * 1000)

    # ── 向后兼容属性与门面方法 (Facade Properties & Methods) ───────────

    @property
    def schedule(self):
        """课程表数据源（兼容 InfoPanel.owner.schedule）。"""
        return self.focus_mgr.schedule

    @property
    def tasks(self):
        """待办与考试数据源（兼容 InfoPanel.owner.tasks）。"""
        return self.focus_mgr.tasks

    @property
    def bubble(self):
        """语音气泡（兼容直接访问 self.bubble）。"""
        return self.input_ctrl.bubble

    @property
    def input(self):
        """用户输入框（兼容直接访问 self.input）。"""
        return self.input_ctrl.input

    @property
    def badge(self):
        """专注倒计时徽章。"""
        return self.focus_mgr.badge

    @property
    def _exam_badge(self):
        """考试倒计时徽章。"""
        return self.focus_mgr._exam_badge

    @property
    def _tray(self):
        """系统托盘图标。"""
        return self.tray_coord.tray_icon

    @property
    def _pomo(self):
        return self.focus_mgr._pomo

    @property
    def _worker(self):
        return self.input_ctrl.worker

    @property
    def _chat_anchor(self):
        return self.input_ctrl.chat_anchor

    def open_chat(self):
        self.input_ctrl.open_chat()

    def _toggle_chat(self):
        self.input_ctrl.toggle_chat()

    def _ask(self, text):
        self.input_ctrl.ask(text)

    def _update_chat_placeholder(self):
        self.input_ctrl.update_placeholder()

    def _menu(self, pos):
        self.menu_builder.show_menu(pos)

    def _available_characters(self):
        return self.menu_builder.available_characters()

    def _show_today(self):
        self.focus_mgr.show_today()

    def _show_next(self):
        self.focus_mgr.show_next()

    def _show_week(self):
        self.focus_mgr.show_week()

    def _import_schedule(self):
        self.focus_mgr.import_schedule()

    def _add_task(self, kind):
        self.focus_mgr.add_task(kind)

    def _show_tasks(self):
        self.focus_mgr.show_tasks()

    def _show_exam_countdown(self):
        self.focus_mgr.show_exam_countdown()

    def _manage_tasks(self):
        self.focus_mgr.manage_tasks()

    def _toggle_exam_badge(self, checked):
        self.focus_mgr.toggle_exam_badge(checked)

    def _reminder_dialog(self):
        self.focus_mgr.reminder_dialog()

    def _countdown_dialog(self):
        self.focus_mgr.countdown_dialog()

    def _pomodoro_dialog(self):
        self.focus_mgr.pomodoro_dialog()

    def _stop_focus(self):
        self.focus_mgr.stop_focus()

    def _schedule_reminder(self, seconds, message):
        self.focus_mgr.schedule_reminder(seconds, message)

    def _setup_greetings(self):
        self.focus_mgr.setup_greetings()

    def _check_greetings(self):
        self.focus_mgr.check_greetings()

    def _say_greeting(self, text):
        self._announce(text)

    def _update_tray_tooltip(self):
        self.tray_coord.update_tooltip()

    def _rebuild_tray_menu(self):
        self.tray_coord.rebuild_menu()

    def _toggle_tray_visible(self):
        self.tray_coord.toggle_visible()

    def _show_pet(self):
        self.tray_coord.show_pet()

    def _open_ai_settings(self):
        self.menu_builder.open_ai_settings()

    def _open_app_whitelist(self):
        self.menu_builder.open_app_whitelist()

    def _open_settings(self):
        self.menu_builder.open_settings()

    # ------------------------------------------------------------------ #
    # Animation escalation & Rest config                                   #
    # ------------------------------------------------------------------ #

    def _load_rest_config(self):
        rest = self.char.cfg.get("rest", {})
        self._idle_to_sit_ms = self._range_ms(rest.get("idle_to_sit"), 300, 600)
        self._sit_to_sleep_ms = self._range_ms(
            rest.get("sit_to_sleep"), 3600, 7200)

    def _info_panel(self):
        """懒创建信息面板（课程表 / 待办 / OCR 集中窗口）。"""
        if self._info_panel_widget is None:
            self._info_panel_widget = InfoPanel(self)
        return self._info_panel_widget

    def _show_text(self, text):
        """长文本用翻译浮窗展示（可点击关闭、自动隐藏），避免气泡过高。"""
        self.trans_popup.hide()
        self.bubble.hide()
        self.trans_popup.show_translation("", text, self._body_rect())

    def _attach_brain_services(self):
        """把课表/待办/知识库挂到 brain 和 actions。"""
        actions.set_schedule_provider(lambda: self.schedule)
        actions.set_tasks_provider(lambda: self.tasks)
        actions.set_confirm_provider(self._confirm_action)
        self.brain.knowledge = knowledge.KnowledgeBase(
            use_embed=self.prefs.get("knowledge_embed", True))

    def _apply_knowledge_prefs(self):
        """设置里改讲义检索后端后重建知识库（重新加载 + 编码）。"""
        self.brain.knowledge = knowledge.KnowledgeBase(
            use_embed=self.prefs.get("knowledge_embed", True))

    # ── AI 敏感操作确认（截图 / 剪贴板读取 / 键盘打字）────────────────

    def _confirm_action(self, name):
        key = "perm_" + name
        if self.prefs.get(key, "") == "allow":
            return True
        holder = {}

        def ask():
            desc = actions._SENSITIVE_DESC.get(name, "")
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setWindowTitle("阿米娅请求确认")
            box.setText("博士，阿米娅想执行「%s」。\n%s" % (name, desc))
            cb = QtWidgets.QCheckBox("不再询问，总是允许此类操作", box)
            box.setCheckBox(cb)
            allow_btn = box.addButton("允许", QtWidgets.QMessageBox.AcceptRole)
            deny_btn = box.addButton("拒绝", QtWidgets.QMessageBox.RejectRole)
            box.setDefaultButton(deny_btn)
            box.exec_()
            ok = box.clickedButton() is allow_btn
            if ok and cb.isChecked():
                self.prefs.set(key, "allow")
                petlog.log("confirm: %s -> 总是允许" % name)
            holder["ok"] = ok

        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(
            30000, lambda: loop.quit() if "ok" not in holder else None)
        self.confirm_dialog_requested.emit(lambda: (ask(), loop.quit()))
        loop.exec_()
        return holder.get("ok", False)

    def _run_confirm_dialog(self, fn):
        fn()

    def _announce(self, text, use_tts=False):
        """统一通知外显：唤醒宠物、播放问候动作、浮窗置顶、弹气泡并可选用 TTS 播报。"""
        self._wake()
        self.play("greet")
        self.raise_()
        self.trans_popup.hide()
        self.bubble.say(text, self._body_rect(),
                        auto_ms=max(4000, 10000))
        if use_tts:
            self._speak(text, fallback="greet")
        else:
            self.voice.play("greet")

    # ------------------------------------------------------------------ #
    # 全局热键 (Windows)                                                 #
    # ------------------------------------------------------------------ #

    def _setup_hotkey(self):
        """注册全局快捷键（聊天 / 翻译 / OCR）。"""
        _ov = self.prefs.get("hotkeys_" + self.char.key, {}) or {}
        self._hotkey_spec = _ov.get("chat") or self.char.cfg.get(
            "hotkey", "alt+a")
        self._translate_hotkey_spec = _ov.get("translate") or self.char.cfg.get(
            "hotkey_translate", "alt+t")
        self._ocr_hotkey_spec = _ov.get("ocr") or self.char.cfg.get(
            "hotkey_ocr", "alt+s")
        self.hotkey = None
        self._translate_hotkey = None
        self._ocr_hotkey = None
        hwnd = int(self.winId())
        seen = set()
        for spec, attr, slot in (
                (self._hotkey_spec, "hotkey", self._toggle_chat),
                (self._translate_hotkey_spec, "_translate_hotkey",
                 self._translate_clipboard),
                (self._ocr_hotkey_spec, "_ocr_hotkey",
                 lambda: self._ocr_flow("translate"))):
            if not spec or spec in seen:
                continue
            seen.add(spec)
            hk = GlobalHotkey(hwnd, spec, self)
            if hk.active:
                hk.activated.connect(slot)
                setattr(self, attr, hk)
        petlog.log("hotkeys: %s" % ", ".join(
            "%s=%s" % (spec, getattr(self, attr, None) is not None
                       and getattr(self, attr).active)
            for spec, attr, _s in (
                (self._hotkey_spec, "hotkey", None),
                (self._translate_hotkey_spec, "_translate_hotkey", None),
                (self._ocr_hotkey_spec, "_ocr_hotkey", None))))

    def _unregister_hotkeys(self):
        for attr in ("hotkey", "_translate_hotkey", "_ocr_hotkey"):
            h = getattr(self, attr, None)
            if h is not None:
                try:
                    h.unregister()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _apply_hotkey_overrides(self):
        try:
            self._unregister_hotkeys()
            self._setup_hotkey()
        except Exception:
            petlog.log("重注册热键异常:\n%s" % traceback.format_exc())

    # ------------------------------------------------------------------ #
    # 快捷翻译与 OCR 截图                                                #
    # ------------------------------------------------------------------ #

    def _translate_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        text = (clipboard.text() or "").strip()
        self.input.hide()
        self.bubble.hide()
        if not text:
            self.raise_()
            self.bubble.say("剪贴板里没有文字哦，博士。", self._body_rect())
            return
        self._chat_anchor_rect = self._body_rect()
        self._do_translate(text)

    def _do_translate(self, text):
        if self._trans_worker is not None and self._trans_worker.isRunning():
            return
        self._trans_worker = TranslateWorker(self.brain, text, parent=self)
        self._trans_worker.done.connect(self._on_translate_done)
        self._trans_worker.start()

    def _on_translate_done(self, source, translated):
        self.bubble.hide()
        rect = getattr(self, "_chat_anchor_rect", None) or self._body_rect()
        self.trans_popup.show_translation(source, translated, rect)

    def _ocr_flow(self, mode):
        self._ocr_mode = mode
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            self.raise_()
            self.bubble.say("截图失败：找不到可用的屏幕。", self._body_rect())
            return
        geo = screen.geometry()
        dpr = screen.devicePixelRatio()
        bbox = (int(geo.x() * dpr), int(geo.y() * dpr),
                int((geo.x() + geo.width()) * dpr),
                int((geo.y() + geo.height()) * dpr))
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=bbox)
        except Exception as e:
            self.raise_()
            self.bubble.say("截图失败：%s" % type(e).__name__, self._body_rect())
            return
        sel = RegionSelect(img, geo, dpr=dpr)
        sel.selected.connect(self._on_ocr_region)
        sel.cancelled.connect(sel.close)
        sel.show()
        sel.raise_()
        sel.activateWindow()

    def _on_ocr_region(self, crop):
        if self._ocr_worker is not None and self._ocr_worker.isRunning():
            return
        self.bubble.say("正在识别…", self._body_rect())
        self._ocr_worker = OcrWorker(crop, self.brain, self._ocr_mode, parent=self)
        self._ocr_worker.done.connect(self._on_ocr_done)
        self._ocr_worker.start()

    def _on_ocr_done(self, text, result, error):
        self.bubble.hide()
        if error:
            self.raise_()
            self.bubble.say(error, self._body_rect())
            return
        p = self._info_panel()
        p.show_ocr(self._ocr_mode, text, result)
        p.present()

    # ------------------------------------------------------------------ #
    # 角色切换与生命周期管理                                             #
    # ------------------------------------------------------------------ #

    def _switch_character(self, char_dir):
        if os.path.normcase(char_dir) == os.path.normcase(self.char.dir):
            return
        try:
            new_char = Character(char_dir)
        except Exception as e:
            self.trans_popup.hide()
            self.bubble.say("切换失败：%s" % type(e).__name__, self._body_rect())
            return

        self._timer.stop()
        self._rest_timer.stop()
        self.focus_mgr.close()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.voice.stop()
        self._unregister_hotkeys()

        # 停止所有进行中的线程
        self.input_ctrl.stop_worker(3000)
        for w in (self._tts_worker, self._trans_worker, self._ocr_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()
                if not w.wait(3000):
                    w.terminate()
                    w.wait(1000)
        self._tts_worker = None
        self._trans_worker = None
        self._ocr_worker = None

        self.char = new_char
        self.characters_dir = os.path.dirname(new_char.dir)
        self.prefs.set("character", new_char.key)
        self._cur_action = None
        self._loops_left = 0
        self._frames = []
        self._mem.clear_cache()
        self._caching = False
        self._replay = False
        self._replay_i = 0
        self._cache_full = False
        self._skip_count = 0
        self._last_bgra = None
        self._compress_timer.stop()
        self._compress_i = 0
        self._alpha = None
        self._bbox = None

        self._load_rest_config()
        vcfg = self.char.cfg.get("voice", {})
        self.voice = VoicePlayer(
            self.char.dir,
            volume=self.prefs.get("volume", vcfg.get("volume", 0.7)),
            enabled=self.prefs.get("voice_enabled", vcfg.get("enabled", True)),
        )
        self._tts_cfg = vcfg.get("tts", {})
        self._tts_supported = bool(self._tts_cfg.get("enabled", True))
        self._tts_on = (self._tts_supported
                        and self.prefs.get("tts_on", True)
                        and tts.available())
        self._use_clone = bool(self._tts_cfg.get("use_clone", True))
        self._clone_character = self._tts_cfg.get("clone_character",
            os.path.basename(os.path.normpath(self.char.dir)))
        tts.set_manual_auto_stop(
            self.prefs.get("clone_manual_autostop", False))

        self.menu_builder.invalidate_characters_cache()
        self._clone_probe_timer.stop()
        if self._use_clone:
            self._clone_probe_timer.start(3000)
            self._schedule_clone_probe()

        self.brain = AmiyaBrain(self.char.dir,
                                persona=self.char.cfg.get("persona"),
                                fallback=self.char.cfg.get("fallback"))
        self._attach_brain_services()
        self.input_ctrl.update_placeholder()
        self._setup_hotkey()
        self.focus_mgr.setup_greetings()

        self.play("start")
        self.raise_()
        self.trans_popup.hide()
        self.bubble.say("已切换到%s。" % self.char.display_name, self._body_rect())
        self.voice.play("greet")

    def _speak(self, text, fallback="reply"):
        if not self.voice.enabled or self.voice.volume <= 0:
            return
        if self._tts_on and (text or "").strip():
            self._tts_gen += 1
            gen = self._tts_gen
            if self._tts_worker is not None and self._tts_worker.isRunning():
                self._tts_worker.requestInterruption()
            self._tts_worker = tts.TtsWorker(
                text,
                voice=self._tts_cfg.get("voice") or tts.DEFAULT_VOICE,
                rate=self._tts_cfg.get("rate", "+0%"),
                volume=self._tts_cfg.get("synth_volume", "+0%"),
                pitch=self._tts_cfg.get("pitch", "+0Hz"),
                use_clone=self._use_clone,
                clone_character=self._clone_character,
                parent=self,
            )
            self._tts_worker.done.connect(
                lambda path: self._on_tts_done(path, fallback, gen))
            self._tts_worker.start()
        else:
            self.voice.play(fallback)

    def _on_tts_done(self, path, fallback="reply", gen=None):
        if gen is not None and gen != self._tts_gen:
            return
        if path:
            self.voice.play_file(path)
        else:
            self.voice.play(fallback)

    def _reposition_popups(self):
        rect = self._body_rect()
        self.input_ctrl.reposition(rect)
        self.focus_mgr.reposition_badges(rect)
        if self.trans_popup.isVisible():
            self.trans_popup.reposition(rect)

    def moveEvent(self, e):
        self._sync_dpr()
        self._reposition_popups()
        super().moveEvent(e)

    def _current_dpr(self):
        pt = self.frameGeometry().center()
        scr = QtWidgets.QApplication.screenAt(pt) or self.screen()
        return scr.devicePixelRatio() if scr else 1.0

    def _sync_dpr(self):
        dpr = self._current_dpr()
        if abs(dpr - self._dpr) < 1e-3:
            return
        self._dpr = dpr
        if self._cur_action is not None and self._frames:
            self._frames = []
            self._mem.clear_cache()
            self._caching = self._cur_action.loop
            self._replay = False
            self._replay_i = 0
            self._cache_full = False
            self._compress_timer.stop()
            self._compress_i = 0
        if self._cur_action is not None:
            self._timer.setInterval(max(1, int(1000.0 / self._cur_action.fps)))

    def play(self, action_name):
        act = self.char.action(action_name)
        if not act or not act.files:
            return
        fn = random.choice(act.files)
        cap = cv2.VideoCapture(fn)
        if not cap.isOpened():
            return
        if self._cap is not None:
            self._cap.release()
        self._cap = cap
        self._cur_action = act
        self._loops_left = act.loop_count
        self._frames = []
        self._mem.clear_cache()
        self._caching = act.loop
        self._replay = False
        self._replay_i = 0
        self._cache_full = False
        self._skip_count = 0
        self._last_bgra = None
        self._compress_timer.stop()
        self._compress_i = 0
        self._sync_dpr()
        self._timer.setInterval(max(1, int(1000.0 / act.fps)))
        self._timer.start()
        self._schedule_rest(action_name)

    @staticmethod
    def _range_ms(cfg, def_lo_s, def_hi_s):
        lo, hi = def_lo_s, def_hi_s
        if isinstance(cfg, (list, tuple)) and len(cfg) >= 2:
            try:
                lo, hi = float(cfg[0]), float(cfg[1])
            except (ValueError, TypeError):
                pass
        return int(lo * 1000), int(hi * 1000)

    def _schedule_rest(self, action_name):
        self._rest_timer.stop()
        if action_name == "idle" and self.char.action("sit"):
            self._rest_target = "sit"
            lo, hi = self._idle_to_sit_ms
            self._rest_timer.start(random.randint(lo, hi))
        elif action_name == "sit" and self.char.action("sleep"):
            self._rest_target = "sleep"
            lo, hi = self._sit_to_sleep_ms
            self._rest_timer.start(random.randint(lo, hi))

    def _rest_step(self):
        target = getattr(self, "_rest_target", None)
        if target:
            self.play(target)

    def _wake(self):
        if self._cur_action and self._cur_action.name in ("sit", "sleep"):
            self.play("idle")
        elif self._cur_action and self._cur_action.name == "idle":
            self._schedule_rest("idle")

    def _tick(self):
        tier = self._mem.tier
        if tier.fps_divisor > 1:
            self._skip_count += 1
            if self._skip_count % tier.fps_divisor != 0:
                return

        if self._replay:
            if not self._frames:
                self._replay = False
                self._caching = bool(self._cur_action and self._cur_action.loop)
            else:
                entry = self._frames[self._replay_i]
                if isinstance(entry, bytes):
                    bgra = cv2.imdecode(
                        memory.from_buffer_uint8(entry), cv2.IMREAD_UNCHANGED)
                else:
                    bgra = entry
                self._replay_i = (self._replay_i + 1) % len(self._frames)
                self._show(bgra)
                return

        if self._cap is None:
            return
        ret, frame = self._cap.read()
        if not ret:
            if self._cur_action and self._cur_action.loop:
                if self._caching and self._frames and not self._cache_full:
                    self._replay = True
                    self._replay_i = 0
                    self._caching = False
                    self._cap.release()
                    self._cap = None
                    self._compress_i = 0
                    self._compress_timer.start(15)
                    self._tick()
                    return
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self._cap.read()
                if not ret:
                    return
            elif self._loops_left > 1:
                self._loops_left -= 1
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self._cap.read()
                if not ret:
                    return
            else:
                self._cap.release()
                self._cap = None
                self.play(self._cur_action.next_action if self._cur_action else "idle")
                return

        bgra = key_frame(frame, dpr=self._dpr * tier.dpr_factor)
        if self._caching:
            if not self._mem.can_cache_more():
                self._cache_full = True
                self._caching = False
                self._frames = []
            else:
                self._frames.append(bgra)
        self._show(bgra)

    def _compress_tick(self):
        while self._compress_i < len(self._frames):
            entry = self._frames[self._compress_i]
            if not isinstance(entry, bytes):
                ok, png = cv2.imencode(".png", entry)
                if ok:
                    png_bytes = png.tobytes()
                    self._frames[self._compress_i] = png_bytes
                    self._mem.record_cached_frame(len(png_bytes))
                self._compress_i += 1
                return
            self._compress_i += 1
        self._compress_timer.stop()

    def _show(self, bgra):
        h, w = bgra.shape[:2]
        self._alpha = bgra[:, :, 3]
        self._bbox = None
        self._qimg = QtGui.QImage(
            bgra.data, w, h, w * 4, QtGui.QImage.Format_ARGB32)
        pix = QtGui.QPixmap.fromImage(self._qimg)
        pix.setDevicePixelRatio(self._dpr)
        self.label.setPixmap(pix)
        log_w = int(w / self._dpr)
        log_h = int(h / self._dpr)
        self.label.resize(log_w, log_h)
        self.resize(log_w, log_h)

        if not self._first_frame_shown:
            self._first_frame_shown = True
            if not self._restore_position():
                self._place_bottom_center()

    def _place_bottom_center(self):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() - self.height()
        self.move(x, y)

    def _save_pet_position(self):
        self.prefs.set("pet_x", self.x())
        self.prefs.set("pet_y", self.y())

    def _position_visible(self, x, y, w, h):
        for scr in QtWidgets.QApplication.screens():
            ag = scr.availableGeometry()
            overlap_w = max(0, min(x + w, ag.right()) - max(x, ag.left()))
            overlap_h = max(0, min(y + h, ag.bottom()) - max(y, ag.top()))
            if overlap_w * overlap_h >= 0.3 * w * h:
                return True
        return False

    def _restore_position(self):
        x = self.prefs.get("pet_x")
        y = self.prefs.get("pet_y")
        if x is None or y is None:
            return False
        w, h = self.width(), self.height()
        if not self._position_visible(x, y, w, h):
            return False
        self.move(x, y)
        return True

    def _body_rect(self):
        if self._bbox is not None:
            x, y, w, h = self._bbox
            return QtCore.QRect(self.mapToGlobal(QtCore.QPoint(x, y)),
                                QtCore.QSize(w, h))
        if self._alpha is None:
            return self.frameGeometry()
        ys, xs = (self._alpha > 40).nonzero()
        if len(xs) == 0:
            return self.frameGeometry()
        d = self._dpr
        self._bbox = (int(xs.min() / d), int(ys.min() / d),
                      int((xs.max() - xs.min()) / d),
                      int((ys.max() - ys.min()) / d))
        x, y, w, h = self._bbox
        return QtCore.QRect(self.mapToGlobal(QtCore.QPoint(x, y)),
                            QtCore.QSize(w, h))

    def _opaque_at(self, pos):
        if self._alpha is None:
            return False
        x, y = int(pos.x() * self._dpr), int(pos.y() * self._dpr)
        if 0 <= y < self._alpha.shape[0] and 0 <= x < self._alpha.shape[1]:
            return self._alpha[y, x] > 40
        return False

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    pos = self.mapFromGlobal(QtCore.QPoint(x, y))
                    if not self._opaque_at(pos):
                        return True, -1
                elif msg.message == self._show_request_msg():
                    self._show_pet()
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    def _show_request_msg(self):
        if getattr(self, "_show_msg_id", None) is None:
            self._show_msg_id = single_instance.show_message_id()
        return self._show_msg_id or -1

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag_offset = e.globalPos() - self.frameGeometry().topLeft()
            self._moved = False
            self.play("drag")
            self.voice.play("drag")
            self._wake()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self._moved = True
            self.move(e.globalPos() - self._drag_offset)
            self._reposition_popups()

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            if self._moved:
                self._save_pet_position()
            self._drag_offset = None
            if not self._moved:
                self.play(self.char.interaction("on_click") or "click")
                self.voice.play("click")
            else:
                self.play("idle")

    def mouseDoubleClickEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.open_chat()

    def _apply_ai_settings(self, cfg):
        old_history = self.brain.history
        self.brain = AmiyaBrain(self.char.dir,
                                persona=self.char.cfg.get("persona"),
                                fallback=self.char.cfg.get("fallback"))
        self.brain.history = old_history
        self._attach_brain_services()
        if cfg.get("api_key"):
            text = "模型配置已保存，%s会用新的大模型回答博士。" % self.char.display_name
        else:
            text = "模型配置已保存。没有 API Key 时，%s会先用内置台词。" % self.char.display_name
        self.trans_popup.hide()
        self.bubble.say(text, self._body_rect())

    def _act_voice(self, action, voice_event):
        self.play(action)
        self.voice.play(voice_event)

    def _schedule_clone_probe(self):
        probe = self._clone_probe
        if probe is not None and probe.isRunning():
            return
        probe = CloneStateProbe(self)
        probe.finished.connect(lambda p=probe: self._clone_probe_done(p))
        self._clone_probe = probe
        probe.start()

    def _clone_probe_done(self, probe):
        if self._clone_probe is probe:
            self._clone_probe = None
            state = tts.clone_state()
            self.tray_coord.update_tooltip()
            if state == "running":
                if self._clone_was_starting and not self._clone_notified:
                    self._clone_notified = True
                    self._note("语音克隆模型已就绪，博士可以用我的声音了。")
                self._clone_was_starting = False
            elif state == "starting":
                self._clone_was_starting = True
                self._clone_notified = False
            else:
                self._clone_was_starting = False
                self._clone_notified = False

    def _check_updates(self, silent=True):
        if self._quitting:
            return
        t = getattr(self, "_update_thread", None)
        if t is not None and t.isRunning():
            return
        t = UpdateCheckThread(self)
        t.result.connect(lambda info: self._update_result(info, silent))
        self._update_thread = t
        t.start()

    def _update_result(self, info, silent):
        self._update_thread = None
        if not info:
            if not silent:
                self._note("已经是最新版本了，博士。")
            return
        tag = info["tag"]
        html = info["html"] or "https://github.com/%s/releases" % updater.REPO
        if self.tray_coord.is_available():
            self.tray_coord.show_update_notification(tag, html)
        else:
            self._note("发现新版本 %s，点击前往下载。" % tag)

    def _start_clone(self):
        was_running = tts.clone_state() == "running"
        ok = tts.start_clone_service(
            self._tts_cfg.get("clone_dir"), character=self._clone_character,
            manual=True)
        if ok and not was_running:
            tts.set_clone_state("starting")
            self._clone_was_starting = True
            self._clone_notified = False
        self._schedule_clone_probe()
        if ok:
            self._note("正在加载语音克隆模型，大约 30 秒后博士就能听到我的声音了。")
        else:
            self._note("语音克隆服务启动失败，请检查 voiceclone 部署。")

    def _stop_clone(self):
        tts.stop_clone_service()
        tts.set_clone_state("stopped")
        self._clone_was_starting = False
        self._clone_notified = False
        self._schedule_clone_probe()
        self._note("语音克隆服务已停止，显存已释放。")

    def _note(self, text):
        self._wake()
        self.raise_()
        self.trans_popup.hide()
        self.bubble.say(text, self._body_rect(), auto_ms=max(4000, 10000))

    def _set_tts(self, on):
        self._tts_on = bool(on) and self._tts_supported and tts.available()
        self.prefs.set("tts_on", bool(on))

    def _toggle_mute(self, muted):
        self.voice.set_enabled(not muted)
        self.prefs.set("voice_enabled", not muted)

    def _on_volume_slider(self, value):
        self.voice.set_volume(value / 100.0)
        self._save_vol_timer.start(400)

    def _quit(self):
        self._quitting = True
        petlog.log("exit")
        self._save_pet_position()
        self._unregister_hotkeys()
        self.voice.stop()

        self._clone_probe_timer.stop()
        probe = self._clone_probe
        if probe is not None and probe.isRunning():
            probe.wait(1500)

        self.input_ctrl.stop_worker(3000)
        self.focus_mgr.close()

        for w in (self._tts_worker, self._trans_worker, self._ocr_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()
                if not w.wait(3000):
                    w.terminate()
                    w.wait(1000)

        tts.stop_clone_service()
        self.voice.stop()
        tts.cleanup_temp_files()

        self.input_ctrl.close()
        self.trans_popup.close()
        if self._info_panel_widget is not None:
            self._info_panel_widget.close()
        QtWidgets.QApplication.quit()

    def closeEvent(self, event):
        self.tray_coord.handle_close_event(event)
