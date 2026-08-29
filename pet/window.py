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
from .ai_settings import AiSettingsDialog
from .apps_ui import AppWhitelistDialog
from .character import Character
from .chat import InputBar, ReplyWorker, SpeechBubble
from .frames import key_frame
from .hotkey import GlobalHotkey
from .info_panel import InfoPanel, PAGE_OCR, PAGE_SCHEDULE, PAGE_TASKS
from .ocr import OcrError, ocr_image, summarize_ai
from .region_select import RegionSelect
from .schedule import Schedule
from .settings import Settings, characters_dirs
from .tasks import Tasks
from .tasks_ui import TaskDialog, TaskListDialog
from .timers import CountdownBadge, DurationDialog, PomodoroDialog
from .translate import TranslationPopup, TranslateWorker
from .translate import _translate_via_ai, _translate_via_google
from .voice import VoicePlayer
from . import actions, knowledge, logging as petlog, memory, schedule, theme, translate, tts
from . import single_instance, updater

# Typewriter reveal: show the streamed reply at a steady pace regardless of how
# bursty the network delivery is. One "step" reveals TYPE_STEP chars every
# TYPE_INTERVAL_MS; when the backlog is large we reveal a few more per step so
# long answers don't lag far behind, while short replies stay char-by-char.
TYPE_INTERVAL_MS = 55
TYPE_STEP = 1

# Auto-hide the reply bubble after a reading time that scales with length:
# ~250ms per character, clamped so short lines linger and long ones don't
# camp on screen forever.
READ_MS_PER_CHAR = 250
READ_MS_MIN = 4000
READ_MS_MAX = 20000


def _app_icon_path():
    """Locate app.ico for both source and frozen (PyInstaller) runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # Script is at pet/window.py, project root is two levels up.
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "app.ico")
    return path if os.path.isfile(path) else None


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
        self._image = image
        self._brain = brain
        self._cfg = brain.cfg if brain else None
        self._mode = mode   # 'translate' | 'summarize'

    def run(self):
        try:
            text, _ = ocr_image(self._image, self._cfg)
        except OcrError as e:
            self.done.emit("", "", str(e))
            return
        text = (text or "").strip()
        if not text:
            self.done.emit("", "", "没有识别到文字，换个区域试试。")
            return
        try:
            if self._mode == "translate":
                result = (_translate_via_ai(self._brain, text)
                          or _translate_via_google(text))
                if not result:
                    self.done.emit(text, "", "翻译失败：AI 与 Google 均不可用。")
                    return
                self.done.emit(text, result, "")
            else:
                self.done.emit(text, summarize_ai(self._cfg, text), "")
        except Exception as e:
            self.done.emit(text, "", "处理失败：%s" % type(e).__name__)


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
        self._chars_cache = None   # characters/ scan cache (see _available_characters)
        self._chars_mtime = None
        self._cap = None            # cv2.VideoCapture of the current clip
        self._cur_action = None     # Action currently playing
        self._qimg = None           # keep a ref so QImage data stays alive
        self._alpha = None          # last frame alpha, for hit-testing
        self._drag_offset = None
        self._moved = False         # whether the current press turned into a drag
        self._loops_left = 0        # remaining loop_count replays this clip
        # Frame cache for looping clips: decode+key each frame once on the
        # first pass (raw BGRA, keeps the first loop at original speed), then
        # replay from memory so the idle loop stops re-running
        # floodFill/erode/resize every tick.  A lazy background pass converts
        # raw frames to PNG to shrink memory (see _compress_tick).
        self._frames = []           # cached frames: raw BGRA ndarray 或 PNG bytes
        self._caching = False       # accumulate frames this pass?
        self._replay = False        # serving from cache instead of decoding?
        self._replay_i = 0          # next index into _frames when replaying
        self._cache_full = False    # budget exhausted for current clip?
        self._bbox = None           # cached body bbox (logical px) for current frame
        self.badge = None              # created in _setup_focus_tools()
        self._exam_badge = None        # created in _setup_tasks()（moveEvent 可能先触发）

        # Lazy background compression: after a looping clip's first pass,
        # raw BGRA frames are converted to PNG one-by-one on this timer
        # so the animation never stutters from encoding overhead.
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

        # Idle -> sit -> sleep escalation: when left untouched she gradually
        # relaxes. Any interaction resets her back to idle (see _wake).
        # She stands (idle) only briefly, then sits for a long stretch before
        # finally lying down. Each wait is randomised within its range so the
        # rhythm feels natural rather than clockwork. Overridable per-character
        # via config.json "rest": {"idle_to_sit":[min,max], ...} in seconds.
        self._rest_timer = QtCore.QTimer(self)
        self._rest_timer.setSingleShot(True)
        self._rest_timer.timeout.connect(self._rest_step)
        self._load_rest_config()

        # Persisted user preferences override the character's config defaults.
        self.prefs = Settings()

        # Voice
        vcfg = self.char.cfg.get("voice", {})
        self.voice = VoicePlayer(
            self.char.dir,
            volume=self.prefs.get("volume", vcfg.get("volume", 0.7)),
            enabled=self.prefs.get("voice_enabled", vcfg.get("enabled", True)),
        )
        # Text-to-speech: read arbitrary AI replies aloud. Prefers Amiya's
        # cloned voice (local service), falls back to edge-tts, then to a
        # fixed voice line. When unavailable we fall back gracefully.
        self._tts_cfg = vcfg.get("tts", {})
        self._tts_supported = bool(self._tts_cfg.get("enabled", True))
        self._tts_on = (self._tts_supported
                        and self.prefs.get("tts_on", True)
                        and tts.available())
        self._tts_worker = None
        self._tts_gen = 0   # 递增令牌：旧 TTS 合成完成时若已被新请求取代则丢弃
        self._use_clone = bool(self._tts_cfg.get("use_clone", True))
        # Background probe keeps the clone-state label fresh without ever
        # blocking the GUI thread on /ping (see CloneStateProbe).
        self._clone_probe = None
        self._clone_probe_timer = QtCore.QTimer(self)
        self._clone_probe_timer.timeout.connect(self._schedule_clone_probe)
        if self._use_clone:
            self._clone_probe_timer.start(3000)
            self._schedule_clone_probe()   # warm the label once at startup
        # Character key for voice-clone per-request reference switching
        self._clone_character = self._tts_cfg.get("clone_character",
            os.path.basename(os.path.normpath(self.char.dir)))
        # Clone service is NOT started eagerly — it loads a large model into
        # GPU memory (2-4 GB).  We start it lazily on the first TTS request
        # instead, and auto-stop it after a period of TTS inactivity.

        # Debounce persisting the volume while the slider is being dragged.
        self._save_vol_timer = QtCore.QTimer(self)
        self._save_vol_timer.setSingleShot(True)
        self._save_vol_timer.timeout.connect(
            lambda: self.prefs.set("volume", self.voice.volume))

        # AI dialogue
        persona = self.char.cfg.get("persona")
        self.brain = AmiyaBrain(self.char.dir, persona=persona,
                                fallback=self.char.cfg.get("fallback"))
        self.bubble = SpeechBubble()
        self.input = InputBar()
        self.trans_popup = TranslationPopup()
        self._update_chat_placeholder()
        self.input.submitted.connect(self._ask)
        self._worker = None
        self._trans_worker = None

        # Frozen bubble anchor during a reply (set in _ask, follows on drag).
        self._chat_anchor = None
        self._info_panel_widget = None   # 信息面板（课程表/待办/OCR），懒创建
        # 托盘模式：关闭窗口默认隐藏到托盘而不是退出；真退出由 _quit 执行。
        self._quitting = False
        self._tray_hint_shown = False
        # AI 敏感操作确认：worker 线程的信号在 GUI 线程弹确认框。
        self.confirm_dialog_requested.connect(self._run_confirm_dialog)
        # 语音克隆：加载完成提醒的过渡状态；手动启动是否参与空闲自动停止。
        self._clone_was_starting = False
        self._clone_notified = False
        tts.set_manual_auto_stop(self.prefs.get("clone_manual_autostop", False))
        # 自动更新：启动数秒后静默检查（可在设置里关闭）。
        if self.prefs.get("check_updates", True):
            QtCore.QTimer.singleShot(4000, self._check_updates)
        # Typewriter reveal state (see TYPE_* constants).
        self._type_target = ""      # full text received so far (may still grow)
        self._type_shown = 0        # chars currently revealed in the bubble
        self._type_final = False    # has generation finished?
        self._type_timer = QtCore.QTimer(self)
        self._type_timer.timeout.connect(self._type_tick)

        self.play("start")
        self._setup_hotkey()
        self._setup_tray()
        self._setup_reminders()
        self._setup_greetings()
        self._setup_focus_tools()
        self._setup_schedule()
        self._setup_tasks()
        self._attach_brain_services()
        # Periodically check whether the voice-clone service has been idle
        # long enough to auto-stop (frees 2-4 GB GPU RAM until next use).
        self._clone_idle_timer = QtCore.QTimer(self)
        self._clone_idle_timer.timeout.connect(
            lambda: tts.maybe_stop_idle_clone(600))
        self._clone_idle_timer.start(60 * 1000)

    def _load_rest_config(self):
        rest = self.char.cfg.get("rest", {})
        # (min_ms, max_ms): idle 5-10 min, sit 1-2 h by default.
        self._idle_to_sit_ms = self._range_ms(rest.get("idle_to_sit"), 300, 600)
        self._sit_to_sleep_ms = self._range_ms(
            rest.get("sit_to_sleep"), 3600, 7200)

    def _update_chat_placeholder(self):
        self.input.setPlaceholderText(
            "和%s说点什么…（回车发送，Esc 关闭）" % self.char.display_name)

    # ------------------------------------------------------------------ #
    # Schedule (course timetable)                                          #
    # ------------------------------------------------------------------ #

    def _setup_schedule(self):
        """课程表：加载已导入的课表，每分钟检查一次上课提醒。"""
        self.schedule = Schedule()
        self._sched_reminded = set()   # (week, weekday, sec_start, name) 防重复
        self._sched_timer = QtCore.QTimer(self)
        self._sched_timer.timeout.connect(self._sched_tick)
        self._sched_timer.start(30 * 1000)

    def _sched_tick(self):
        """上课前 remind_minutes 分钟提醒一次（今天、本周内）。"""
        s = self.schedule
        if not s.courses or not s.term_start:
            return
        week_no = s.week_no()
        if not week_no or week_no <= 0:
            return
        today = date.today().isoweekday()
        now = datetime.now()
        remind = s.remind_minutes
        for c in s.courses_on(today, week_no):
            hm = c.start_time(week_no, s.sections)
            if hm is None:
                continue
            start = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
            if start <= now:
                continue
            if (start - now).total_seconds() > remind * 60:
                continue
            key = (s.term_start.isoformat(), week_no, today,
                   c.sec_start, c.name)
            if key in self._sched_reminded:
                continue
            self._sched_reminded.add(key)
            where = "在%s" % c.room if c.room else "地点待定"
            self._announce(
                "博士，还有%d分钟要上%s了，%s。" % (remind, c.name, where),
                use_tts=True)

    def _show_today(self):
        """信息面板展示今天的课程。"""
        if not self.schedule.courses:
            self.bubble.say("还没有导入课表，右键菜单 → 课程表 → 导入课表。",
                            self._body_rect())
            return
        p = self._info_panel()
        p.show_schedule("today")
        p.present()

    def _show_next(self):
        """信息面板展示下一节课。"""
        if not self.schedule.courses:
            self.bubble.say("还没有导入课表，右键菜单 → 课程表 → 导入课表。",
                            self._body_rect())
            return
        p = self._info_panel()
        p.show_schedule("next")
        p.present()

    def _show_week(self):
        """信息面板展示本周完整课表。"""
        if not self.schedule.courses:
            self.bubble.say("还没有导入课表，右键菜单 → 课程表 → 导入课表。",
                            self._body_rect())
            return
        p = self._info_panel()
        p.show_schedule("week")
        p.present()

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

    def _import_schedule(self):
        """选择强智课表 JSON 文件导入；首次需填写第 1 周周一日期。"""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择强智课表 JSON", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            self.bubble.say("课表文件读取失败：%s" % type(e).__name__,
                            self._body_rect())
            return
        if not raw.get("kbList") and not raw.get("sjkList"):
            self.bubble.say("这看起来不是强智课表 JSON（缺少 kbList）。",
                            self._body_rect())
            return
        # 第 1 周周一：默认今天所在周的周一，用户可改为实际开学日期。
        default = date.today() - timedelta(days=date.today().isoweekday() - 1)
        term_start = default
        text, ok = QtWidgets.QInputDialog.getText(
            self, "开学日期",
            "第 1 周周一的日期（YYYY-MM-DD）：",
            text=default.isoformat())
        if ok and text.strip():
            try:
                term_start = date.fromisoformat(text.strip())
            except ValueError:
                pass  # 非法输入则沿用默认
        courses, notes, skipped = schedule.import_strongzhi(raw, term_start)
        if not courses:
            self.bubble.say("没有解析出课程，请检查 JSON 内容。", self._body_rect())
            return
        # 原始 JSON 留档（方便每学期重新导入/核对）。
        try:
            raw_dir = os.path.dirname(schedule._data_path())
            if raw_dir:
                os.makedirs(raw_dir, exist_ok=True)
            with open(schedule._raw_path(), "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        xs = raw.get("xsxx", {}) or {}
        term = "%s-第%s学期" % (xs.get("XNMC", ""), xs.get("XQMMC", ""))
        self.schedule.save(term=term, term_start=term_start,
                           courses=courses, notes=notes)
        skipped_note = "（%d 条无法解析，已跳过）" % len(skipped) if skipped else ""
        self._announce("课表导入完成，共 %d 门课%s。开学日期已设为 %s。"
                       % (len(courses), skipped_note, term_start.isoformat()),
                       use_tts=False)

    def _setup_reminders(self):
        """Let the AI schedule reminders; fire them back on the UI thread."""
        self._reminders = []  # keep QTimer refs alive
        self.reminder_requested.connect(
            self._schedule_reminder, QtCore.Qt.QueuedConnection)
        actions.set_scheduler(self.reminder_requested.emit)

    # ------------------------------------------------------------------ #
    # Tasks (homework DDLs & exams)                                        #
    # ------------------------------------------------------------------ #

    def _setup_tasks(self):
        """待办/考试：加载任务，周期检查到期提醒 + 考试倒计时徽章。"""
        self.tasks = Tasks()
        self._task_reminded = set()   # 已提醒过的 task_id（完成/过期后清理）
        self._tasks_timer = QtCore.QTimer(self)
        self._tasks_timer.timeout.connect(self._tasks_tick)
        self._tasks_timer.start(30 * 1000)
        # 考试倒计时常驻徽章（放桌宠左上，避免与专注徽章重叠）。
        self._exam_badge = CountdownBadge()
        self._exam_timer = QtCore.QTimer(self)
        self._exam_timer.timeout.connect(self._refresh_exam_badge)
        self._exam_timer.start(60 * 60 * 1000)   # 每小时刷新天数
        self._refresh_exam_badge()

    def _refresh_exam_badge(self):
        """最近考试剩余天数显示在桌宠旁；无考试或开关关闭时隐藏。"""
        b = self._exam_badge
        if not self.prefs.get("exam_badge", True):
            b.hide()
            return
        exams = self.tasks.exams()
        if not exams:
            b.hide()
            return
        t = exams[0]
        days = max((t.due - datetime.now()).days, 0)
        b.show_text("距%s\n还有 %d 天" % (t.title, days), self._body_rect())
        self._place_exam_badge()

    def _place_exam_badge(self):
        """考试徽章定位到桌宠左上角（专注徽章在右上角）。"""
        b = self._exam_badge
        rect = self._body_rect()
        x = rect.left() - b.width() // 2
        y = rect.top() - b.height() // 2
        b.move(max(0, x), max(0, y))

    def _toggle_exam_badge(self, checked):
        self.prefs.set("exam_badge", bool(checked))
        if checked:
            self._refresh_exam_badge()
        else:
            self._exam_badge.hide()

    def _attach_brain_services(self):
        """把课表/待办/知识库挂到 brain 和 actions。

        brain 在切换角色 / 保存模型配置时会被重建，重建后需要重新挂载。
        actions 的注入让 LLM 工具能读取 schedule/tasks；knowledge 让对话
        基于讲义检索上下文。
        """
        actions.set_schedule_provider(lambda: self.schedule)
        actions.set_tasks_provider(lambda: self.tasks)
        actions.set_confirm_provider(self._confirm_action)
        self.brain.knowledge = knowledge.KnowledgeBase(
            use_embed=self.prefs.get("knowledge_embed", True))

    def _apply_knowledge_prefs(self):
        """设置里改讲义检索后端后重建知识库（重新加载 + 编码）。"""
        self.brain.knowledge = knowledge.KnowledgeBase(
            use_embed=self.prefs.get("knowledge_embed", True))

    # -- AI 敏感操作确认（截图 / 剪贴板读取 / 键盘打字）------------------

    def _confirm_action(self, name):
        """AI 敏感操作确认入口（worker 线程调用，阻塞等待 GUI 结果）。

        已「总是允许」的工具直接放行；否则把弹框请求投递到 GUI 线程，
        用户选允许/拒绝，勾选「不再询问」则持久化到 prefs（perm_<tool>）。
        30 秒无响应（应用正在退出等极端情况）兜底放行，避免对话卡死。
        """
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
        return holder.get("ok", True)

    def _run_confirm_dialog(self, fn):
        """GUI 线程执行确认框（QueuedConnection 投递过来的回调）。"""
        fn()

    def _tasks_tick(self):
        """到期前提醒一次；顺带清理已结束任务的提醒记录。"""
        now = datetime.now()
        # 清理：已完成或已过期的任务不再占用提醒记录
        for t in self.tasks.items:
            if t.done or t.expired(now):
                self._task_reminded.discard(t.id)
        for t in self.tasks.due_soon(now=now):
            if t.id in self._task_reminded:
                continue
            self._task_reminded.add(t.id)
            left = t.due - now
            if left.days >= 1:
                when = "%d 天" % left.days
            elif left.seconds >= 3600:
                when = "%d 小时" % (left.seconds // 3600)
            else:
                when = "%d 分钟" % max(1, left.seconds // 60)
            verb = "考试" if t.kind == "exam" else "作业"
            self._announce("博士，%s《%s》还有 %s 到期，别忘了。"
                           % (verb, t.title, when), use_tts=True)

    def _course_names(self):
        """课表里的课程名，供添加任务时下拉选择。"""
        return sorted({c.name for c in self.schedule.courses})

    def _add_task(self, kind):
        dlg = TaskDialog(kind, courses=self._course_names(), parent=self)
        dlg.confirmed.connect(
            lambda title, course, due, remind: self._on_task_added(
                kind, title, course, due, remind))
        dlg.exec_()

    def _on_task_added(self, kind, title, course, due, remind_min):
        self.tasks.add(title, kind=kind, due=due, course=course,
                       remind_min=remind_min)
        when = due.strftime("%m-%d %H:%M")
        self._announce("已添加%s：《%s》%s到期，阿米娅会提前提醒博士。"
                       % ("考试" if kind == "exam" else "作业", title, when),
                       use_tts=False)

    def _show_tasks(self):
        """信息面板展示待办/考试列表。"""
        p = self._info_panel()
        p.refresh_tasks()
        p.present()

    def _show_exam_countdown(self):
        """信息面板展示待办/考试（含考试倒计时）。"""
        p = self._info_panel()
        p.refresh_tasks()
        p.present()

    def _manage_tasks(self):
        dlg = TaskListDialog(self.tasks, parent=self)
        dlg.exec_()

    def _add_tasks_menu(self, parent):
        sub = parent.addMenu("待办与考试")
        sub.addAction("添加作业 DDL…", lambda: self._add_task("homework"))
        sub.addAction("添加考试…", lambda: self._add_task("exam"))
        sub.addSeparator()
        sub.addAction("即将到期", self._show_tasks)
        sub.addAction("考试倒计时", self._show_exam_countdown)
        sub.addAction("管理待办…", self._manage_tasks)
        badge_act = sub.addAction("考试倒计时徽章")
        badge_act.setCheckable(True)
        badge_act.setChecked(self.prefs.get("exam_badge", True))
        badge_act.toggled.connect(self._toggle_exam_badge)

    def _schedule_reminder(self, seconds, message):
        t = QtCore.QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda: self._fire_reminder(t, message))
        t.start(seconds * 1000)
        self._reminders.append(t)

    def _fire_reminder(self, timer, message):
        if timer in self._reminders:
            self._reminders.remove(timer)
        self._announce("博士，%s" % message, use_tts=True)

    def _announce(self, text, use_tts=False):
        """Surface a message: wake, play greet, raise, bubble + optionally speak.

        Shared by scheduled reminders, time-based greetings, and the focus
        tools (countdown / pomodoro) so every notification looks the same.

        `use_tts`: when True the text is read aloud in the character's voice
        (clone or edge-tts). Auto-greetings pass False to avoid starting the
        voice-clone service — the pre-recorded greeting voice line plays via
        ``voice.play("greet")`` instead.
        """
        self._wake()
        self.play("greet")
        self.raise_()  # surface above other windows so it's noticed
        self.trans_popup.hide()
        self.bubble.say(text, self._body_rect(),
                        auto_ms=max(READ_MS_MIN, READ_MS_MAX // 2))
        if use_tts:
            # Read aloud (cloned voice / edge-tts), falling back to a greeting
            # voice line when TTS is off — so a notification is never silent.
            self._speak(text, fallback="greet")
        else:
            self.voice.play("greet")

    # ------------------------------------------------------------------ #
    # Time-based greetings (morning / noon rest / late night)              #
    # ------------------------------------------------------------------ #

    def _setup_greetings(self):
        """Greet on entering a time window (早安 / 午休 / 深夜), once per entry.

        A window is a [start, end) clock range with a pool of lines; ranges
        that wrap past midnight (e.g. 23:30-03:00) are handled. We poll once a
        minute and fire only on the transition from outside->inside a window,
        so each window greets exactly once per day it's entered.
        """
        gcfg = self.char.cfg.get("greetings", {})
        self._greet_windows = []
        if gcfg.get("enabled", True):
            for key in ("morning", "noon", "late_night"):
                w = gcfg.get(key)
                if not isinstance(w, dict) or not w.get("lines"):
                    continue
                start = self._parse_hhmm(w.get("start"))
                end = self._parse_hhmm(w.get("end"))
                if start is None or end is None:
                    continue
                self._greet_windows.append({
                    "name": key,
                    "start": start,
                    "end": end,
                    "lines": list(w["lines"]),
                    "inside": None,  # unknown until first poll
                })
        self._greet_timer = QtCore.QTimer(self)
        self._greet_timer.timeout.connect(self._check_greetings)
        if self._greet_windows:
            # First poll shortly after launch so opening the app inside a window
            # (e.g. late at night) still gets a greeting once the start clip ends.
            QtCore.QTimer.singleShot(4000, self._check_greetings)
            self._greet_timer.start(60 * 1000)

    @staticmethod
    def _parse_hhmm(text):
        """'HH:MM' -> minutes since midnight, or None if malformed."""
        try:
            h, m = str(text).split(":")
            h, m = int(h), int(m)
        except (ValueError, AttributeError):
            return None
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
        return None

    @staticmethod
    def _in_window(now_min, start, end):
        """Is now_min within [start, end)? Handles ranges wrapping midnight."""
        if start <= end:
            return start <= now_min < end
        return now_min >= start or now_min < end  # wraps past 24:00

    def _check_greetings(self):
        """Fire a greeting when the clock has just entered one of the windows."""
        import datetime
        now = datetime.datetime.now()
        now_min = now.hour * 60 + now.minute
        for w in self._greet_windows:
            inside = self._in_window(now_min, w["start"], w["end"])
            was_inside = w["inside"]
            w["inside"] = inside
            # Fire only on the outside->inside edge. On the very first poll
            # (was_inside is None) we still greet if we're inside a window.
            if inside and not was_inside:
                self._say_greeting(random.choice(w["lines"]))
                break  # at most one greeting per tick

    def _say_greeting(self, text):
        """Show + speak a scheduled greeting, reusing the notification surface."""
        self._announce(text)

    # ------------------------------------------------------------------ #
    # Focus tools: reminder / countdown / pomodoro                         #
    # ------------------------------------------------------------------ #

    def _setup_focus_tools(self):
        """State for the visible countdown badge and the pomodoro machine."""
        self.badge = CountdownBadge()
        self._cd_timer = QtCore.QTimer(self)
        self._cd_timer.timeout.connect(self._cd_tick)
        self._cd_left = 0          # seconds remaining on the visible countdown
        self._cd_label = ""        # short label shown on the badge
        self._cd_done = None       # callback fired when it reaches 0
        # Pomodoro: None when idle, else dict(phase, round, rounds, work, brk).
        self._pomo = None

    def _cancel_countdown(self):
        """Stop just the visible countdown (not the pomodoro state machine)."""
        self._cd_timer.stop()
        self._cd_left = 0
        self._cd_done = None
        if self.badge:
            self.badge.hide()

    def _start_countdown(self, seconds, label, on_done):
        """Show a ticking badge; call on_done() when it hits zero."""
        self._cd_left = int(seconds)
        self._cd_label = label
        self._cd_done = on_done
        self._cd_tick()               # paint immediately, no 1s blank
        self._cd_timer.start(1000)

    def _cd_tick(self):
        if self._cd_left <= 0:
            self._cd_timer.stop()
            if self.badge:
                self.badge.hide()
            done, self._cd_done = self._cd_done, None
            if done:
                done()
            return
        m, s = divmod(self._cd_left, 60)
        if self.badge:
            self.badge.show_text("%s %02d:%02d" % (self._cd_label, m, s),
                                 self._body_rect())
        self._cd_left -= 1

    def _reminder_dialog(self):
        dlg = DurationDialog("提醒事项", "SET A REMINDER",
                             "该休息一下了", 10, self)
        dlg.confirmed.connect(self._start_reminder)
        dlg.exec_()

    def _start_reminder(self, total, message):
        # A plain reminder: no badge, reuse the existing scheduler path.
        self._schedule_reminder(total, message)
        self._announce("好的博士，%s后我会提醒您：%s"
                       % (actions._fmt_delay(total), message), use_tts=True)

    def _countdown_dialog(self):
        dlg = DurationDialog("倒计时", "SET A COUNTDOWN",
                             "倒计时结束", 5, self)
        dlg.confirmed.connect(self._start_manual_countdown)
        dlg.exec_()

    def _start_manual_countdown(self, total, message):
        self._pomo = None             # a manual countdown supersedes pomodoro
        self._announce("倒计时开始，%s。博士加油！"
                       % actions._fmt_delay(total), use_tts=True)
        self._start_countdown(
            total, "⏳", lambda: self._announce("博士，%s" % message, use_tts=True))

    def _pomodoro_dialog(self):
        dlg = PomodoroDialog(self)
        dlg.confirmed.connect(self._start_pomodoro)
        dlg.exec_()

    def _start_pomodoro(self, work, brk, rounds):
        self._pomo = {"phase": "work", "round": 1, "rounds": rounds,
                      "work": work, "brk": brk}
        self._announce("番茄钟开始咯，博士。第 1 轮，专注 %d 分钟，加油！" % work, use_tts=True)
        self._start_countdown(work * 60, "🍅专注", self._pomo_next)

    def _pomo_next(self):
        """Advance the pomodoro machine when a phase's countdown ends."""
        p = self._pomo
        if not p:
            return
        if p["phase"] == "work":
            if p["round"] >= p["rounds"]:
                self._pomo = None
                self._announce("博士，%d 轮番茄钟全部完成，辛苦了！好好休息吧。"
                               % p["rounds"], use_tts=True)
                return
            p["phase"] = "break"
            self._announce("第 %d 轮专注结束，休息 %d 分钟，博士放松一下。"
                           % (p["round"], p["brk"]), use_tts=True)
            self._start_countdown(p["brk"] * 60, "☕休息", self._pomo_next)
        else:
            p["phase"] = "work"
            p["round"] += 1
            self._announce("休息结束，第 %d 轮开始，继续专注 %d 分钟！"
                           % (p["round"], p["work"]), use_tts=True)
            self._start_countdown(p["work"] * 60, "🍅专注", self._pomo_next)

    def _stop_focus(self):
        self._pomo = None
        self._cancel_countdown()
        self._announce("好的博士，已经停下计时了。", use_tts=True)

    def _setup_hotkey(self):
        """Register system-wide shortcuts (Win only).

        Chat / translate / OCR hotkeys come from per-character config.json
        "hotkey" / "hotkey_translate" / "hotkey_ocr", overridable by the
        settings dialog via prefs["hotkeys_<角色>"]（保存到用户数据目录，
        打包版内置角色目录只读时也能改键）。Duplicate
        specs are registered only once (chat wins), so a config that sets
        "hotkey": "alt+t" can't silently kill the translate shortcut — and
        the chat hotkey itself can't be lost to a fixed default collision.
        """
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
        # winId() forces native window creation so we have a real HWND.
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
        self._ocr_worker = None
        # 热键注册结果写入 pet.log（排障：热键没反应先看这里，注册失败多为
        # 组合键被其他程序占用）。
        petlog.log("hotkeys: %s" % ", ".join(
            "%s=%s" % (spec, getattr(self, attr, None) is not None
                       and getattr(self, attr).active)
            for spec, attr, _s in (
                (self._hotkey_spec, "hotkey", None),
                (self._translate_hotkey_spec, "_translate_hotkey", None),
                (self._ocr_hotkey_spec, "_ocr_hotkey", None))))

    def _unregister_hotkeys(self):
        """反注册全部全局热键（切角色 / 退出 / 设置改键前调用）。"""
        for attr in ("hotkey", "_translate_hotkey", "_ocr_hotkey"):
            h = getattr(self, attr, None)
            if h is not None:
                try:
                    h.unregister()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _apply_hotkey_overrides(self):
        """设置对话框保存热键后调用：反注册旧热键并重新注册，改键即时生效。"""
        try:
            self._unregister_hotkeys()
            self._setup_hotkey()
        except Exception:
            petlog.log("重注册热键异常:\n%s" % traceback.format_exc())

    def _toggle_chat(self):
        """Hotkey action: pop the input if hidden, else dismiss it."""
        if self.input.isVisible():
            self.input.hide()
        else:
            self.raise_()
            self.open_chat()

    # ------------------------------------------------------------------ #
    # System tray                                                          #
    # ------------------------------------------------------------------ #

    def _setup_tray(self):
        """常驻系统托盘：关闭窗口只是隐藏，服务生命周期不再被误关打断。

        托盘菜单：显示/隐藏、聊天、TTS、静音、语音克隆启停、退出。
        语音克隆菜单项每次弹出时按真实状态重建（与右键菜单同源）。
        """
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray = QtWidgets.QSystemTrayIcon(self)
        icon = _app_icon_path()
        if icon:
            self._tray.setIcon(QtGui.QIcon(icon))
        self._update_tray_tooltip()
        self._tray_menu = QtWidgets.QMenu()
        self._tray_menu.aboutToShow.connect(self._rebuild_tray_menu)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _update_tray_tooltip(self):
        if not getattr(self, "_tray", None):
            return
        st = tts.clone_state()
        label = {"running": "语音克隆：运行中",
                 "starting": "语音克隆：加载中",
                 "stopped": "语音克隆：未启动"}.get(st, st)
        self._tray.setToolTip("阿米娅桌面宠物 · %s · %s" % (
            self.char.display_name, label))

    def _rebuild_tray_menu(self):
        m = self._tray_menu
        m.clear()
        vis = m.addAction("隐藏桌宠" if self.isVisible() else "显示桌宠")
        vis.triggered.connect(self._toggle_tray_visible)
        m.addAction("聊天…", self._tray_chat)
        m.addSeparator()
        tts_act = m.addAction("朗读回答（语音合成）")
        tts_act.setCheckable(True)
        tts_act.setEnabled(self._tts_supported and tts.available())
        tts_act.setChecked(self._tts_on)
        tts_act.toggled.connect(self._set_tts)
        mute = m.addAction("静音")
        mute.setCheckable(True)
        mute.setChecked(not self.voice.enabled)
        mute.toggled.connect(self._toggle_mute)
        m.addSeparator()
        if self._use_clone:
            state = tts.clone_state()
            if state == "running":
                m.addAction("停止语音克隆服务（释放显存）", self._stop_clone)
            elif state == "starting":
                loading = m.addAction("语音克隆服务加载中…")
                loading.setEnabled(False)
            else:
                m.addAction("启动语音克隆服务（AI 声线）", self._start_clone)
            m.addSeparator()
        m.addAction("退出", self._quit)

    def _on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self._toggle_tray_visible()
        elif reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self._show_pet()
            self.open_chat()

    def _toggle_tray_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self._show_pet()

    def _show_pet(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_chat(self):
        self._show_pet()
        self.open_chat()

    # ------------------------------------------------------------------ #
    # Quick translation                                                     #
    # ------------------------------------------------------------------ #

    def _translate_clipboard(self):
        """Read the system clipboard and translate its text content."""
        clipboard = QtWidgets.QApplication.clipboard()
        text = (clipboard.text() or "").strip()
        # Dismiss any lingering chat UI so it doesn't overlap the translation.
        self.input.hide()
        self.bubble.hide()
        if not text:
            self.raise_()
            self.bubble.say("剪贴板里没有文字哦，博士。", self._body_rect())
            return
        self._chat_anchor = self._body_rect()
        self._do_translate(text)

    def _do_translate(self, text):
        """Fire a background translation for *text* (called from hotkey or chat)."""
        if self._trans_worker is not None and self._trans_worker.isRunning():
            return
        self._trans_worker = TranslateWorker(self.brain, text, parent=self)
        self._trans_worker.done.connect(self._on_translate_done)
        self._trans_worker.start()

    def _on_translate_done(self, source, translated):
        """Show the finished translation in the popup."""
        self.bubble.hide()
        rect = self._chat_anchor or self._body_rect()
        self.trans_popup.show_translation(source, translated, rect)

    # ------------------------------------------------------------------ #
    # OCR screenshot (region select -> recognize -> translate/summarize)   #
    # ------------------------------------------------------------------ #

    def _ocr_flow(self, mode):
        """全屏截图 -> 拖拽框选区域 -> OCR -> 翻译/总结（后台线程）。"""
        self._ocr_mode = mode
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            self.raise_()
            self.bubble.say("截图失败：找不到可用的屏幕。", self._body_rect())
            return
        geo = screen.geometry()            # 逻辑坐标
        dpr = screen.devicePixelRatio()    # 物理/逻辑 缩放比
        # ImageGrab 按物理像素工作，且无参时只抓主屏。这里显式抓桌宠所在
        # 屏幕的物理区域：多显示器时截图与遮罩才不会错位，HiDPI 缩放下
        # 选区的裁剪坐标也才能和物理像素对上（RegionSelect 按 dpr 换算）。
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
        self._ocr_worker = OcrWorker(crop, self.brain, self._ocr_mode,
                                     parent=self)
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

    def _add_ocr_menu(self, parent):
        sub = parent.addMenu("OCR 截图")
        sub.addAction("截图翻译（Alt+S）", lambda: self._ocr_flow("translate"))
        sub.addAction("截图总结", lambda: self._ocr_flow("summarize"))
        sub.addSeparator()
        sub.addAction("重新加载知识库", self._reload_knowledge)

    def _reload_knowledge(self):
        """重新扫描讲义目录（%APPDATA%\\AmiyaPet\\knowledge\\）。"""
        kb = getattr(self.brain, "knowledge", None)
        if kb is None:
            self._attach_brain_services()
            kb = self.brain.knowledge
        kb.reload()
        if len(kb):
            self.bubble.say("知识库已重新加载：%d 个片段。"
                            % len(kb), self._body_rect())
        else:
            self.bubble.say("知识库为空。请把讲义 .txt / .md 放进\n%s"
                            % kb.folder, self._body_rect())

    # ------------------------------------------------------------------ #
    # Character switching                                                  #
    # ------------------------------------------------------------------ #

    def _available_characters(self):
        """All characters found across every character directory (bundled +
        user data), cached by the tuple of directory mtimes.

        The cache only invalidates when a character folder appears/disappears,
        so after the first call the per-right-click cost is one stat() per
        directory instead of scanning and JSON-parsing every character.
        """
        dirs = characters_dirs()
        try:
            key = tuple(
                (d, os.path.getmtime(d)) if os.path.isdir(d) else (d, None)
                for d in dirs)
        except OSError:
            key = None
        if self._chars_cache is not None and self._chars_mtime == key:
            return self._chars_cache
        chars = []
        seen = set()
        for base in dirs:
            for cfg_path in sorted(
                    glob.glob(os.path.join(base, "*", "config.json"))):
                try:
                    ch = Character(os.path.dirname(cfg_path))
                except Exception:
                    continue
                # 多目录（exe旁 / 用户数据 / 内置）可能含同名角色：
                # 按键去重并保留第一个，即 characters_dirs() 中靠前的目录优先。
                key = os.path.normcase(ch.key)
                if key in seen:
                    continue
                seen.add(key)
                chars.append(ch)
        self._chars_cache = chars
        self._chars_mtime = key
        return chars

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
        if getattr(self, "_greet_timer", None):
            self._greet_timer.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self.voice.stop()
        self._unregister_hotkeys()
        # Stop in-flight workers so their callbacks can't touch the new
        # character's state (old brain / old voice player). terminate() is the
        # last-resort fallback when a thread is stuck in blocking I/O.
        for w in (self._worker, self._tts_worker, self._trans_worker,
                  self._ocr_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()
                if not w.wait(3000):
                    w.terminate()
                    w.wait(1000)
        self._worker = None
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
        self._chat_anchor = None

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
        # Character scan cache and clone-state probe follow the new character
        # (use_clone may differ per character).
        self._chars_cache = None
        self._chars_mtime = None
        self._clone_probe_timer.stop()
        if self._use_clone:
            self._clone_probe_timer.start(3000)
            self._schedule_clone_probe()
        # Clone service starts on first TTS request (lazy), not here.
        # Ensure focus-tool windows exist (they may have failed in __init__).
        if self.badge is None:
            self._setup_focus_tools()

        self.brain = AmiyaBrain(self.char.dir,
                                persona=self.char.cfg.get("persona"),
                                fallback=self.char.cfg.get("fallback"))
        self._attach_brain_services()
        self._update_chat_placeholder()
        self._setup_hotkey()
        self._setup_greetings()
        self.play("start")
        self.raise_()
        self.trans_popup.hide()
        self.bubble.say("已切换到%s。" % self.char.display_name,
                        self._body_rect())
        self.voice.play("greet")

    # ------------------------------------------------------------------ #
    # AI dialogue                                                          #
    # ------------------------------------------------------------------ #

    def open_chat(self):
        if not self._first_frame_shown:
            return  # window has no size yet, defer until first animation frame
        self._rest_timer.stop()  # don't drift off to sleep mid-conversation
        self._wake()
        self.trans_popup.hide()
        self.input.pop_up(self._body_rect())

    def _ask(self, text):
        # Quick translation prefix: "翻译: xxx" or "翻译： xxx" → skip the AI
        # chat flow and translate directly (faster, stateless, no history pollution).
        if text.startswith("翻译:") or text.startswith("翻译："):
            source = text[3:].strip()
            if source:
                self._chat_anchor = self._body_rect()
                self._do_translate(source)
            return
        # Serialize submissions: a running worker is blocked on the network and
        # already modifying brain.history, so starting a second one would
        # interleave turns and corrupt the conversation.
        if self._worker is not None and self._worker.isRunning():
            # 别静默丢消息：用翻译浮窗提示「稍等」——它不碰正在流式的气泡，
            # 短时显示后自动隐藏。
            self.trans_popup.show_translation(
                "", "博士稍等，我还在想上一个问题…", self._body_rect(),
                auto_ms=2500)
            return
        self.trans_popup.hide()
        # Freeze the bubble anchor for this whole reply so her idle animation
        # (whose body outline shifts frame to frame) can't jitter it. It's only
        # refreshed when she's actually dragged (see _reposition_popups).
        self._chat_anchor = self._body_rect()
        self.bubble.start_stream(self._chat_anchor, "……")  # thinking
        # Reset typewriter state for this reply.
        self._type_target = ""
        self._type_shown = 0
        self._type_final = False
        self._type_timer.stop()
        self._worker = ReplyWorker(self.brain, text, self)
        self._worker.delta.connect(self._on_delta)
        self._worker.done.connect(self._on_reply)
        self._worker.start()

    def _on_delta(self, text):
        """Buffer streamed text; the timer reveals it at a steady pace."""
        self._type_target = text or ""
        if not self._type_timer.isActive():
            self._type_timer.start(TYPE_INTERVAL_MS)

    def _type_tick(self):
        """Reveal a few more characters of the buffered reply."""
        remaining = len(self._type_target) - self._type_shown
        if remaining <= 0:
            if self._type_final:
                self._type_timer.stop()
                self._finish_reply()
            return
        # Catch up faster when a big backlog has queued up.
        step = TYPE_STEP + (remaining // 20)
        self._type_shown = min(len(self._type_target), self._type_shown + step)
        self.bubble.update_stream(self._type_target[:self._type_shown],
                                  self._chat_anchor)

    def _on_reply(self, text):
        """Generation finished: play the reaction/voice, let the typewriter
        drain the remaining buffer, then auto-hide."""
        self._type_target = text or self._type_target
        self._type_final = True
        self.play(self.char.interaction("on_double_click") or "greet")
        self._speak(text)
        if not self._type_timer.isActive():
            self._type_tick()  # nothing streamed (offline) -> reveal now

    def _finish_reply(self):
        """Called once the full reply is on screen; arm a length-based hide."""
        self.bubble.update_stream(self._type_target, self._chat_anchor)
        hide_ms = max(READ_MS_MIN,
                      min(READ_MS_MAX, len(self._type_target) * READ_MS_PER_CHAR))
        self.bubble.end_stream(self._chat_anchor, auto_ms=hide_ms)

    def _speak(self, text, fallback="reply"):
        """Read `text` aloud via TTS; fall back to a fixed voice line.

        `fallback` is the voice event used when TTS is off or synthesis fails
        (e.g. "greet" for reminders, "reply" for chat).
        """
        if not self.voice.enabled or self.voice.volume <= 0:
            return
        if self._tts_on and (text or "").strip():
            # The voice-clone service is started MANUALLY from the context menu
            # (it loads a 2-4 GB model into GPU memory, so it's not worth
            # spinning up for every reply). Here we only pass the worker its
            # clone preference: it uses the clone when the service is already
            # running and otherwise falls back to edge-tts.
            self._tts_gen += 1
            gen = self._tts_gen
            # 快速连续回复时，旧 worker 若还在合成，先请求中断（不阻塞 UI）；
            # 真正防止音频重叠靠 gen 令牌——旧结果到达时直接丢弃不播放。
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
            return  # 这条合成已被更新的请求取代，丢弃以免音频重叠
        if path:
            self.voice.play_file(path)
        else:  # synthesis failed (offline etc.) -> in-game line
            self.voice.play(fallback)

    def _reposition_popups(self):
        """Keep the bubble and input box directly above Amiya's body.

        Only fires on real window moves (drag / cross-screen), not on idle
        frame changes, so it also refreshes the frozen chat anchor to follow
        her without introducing per-frame jitter.
        """
        rect = self._body_rect()
        self._chat_anchor = rect
        if self.bubble.isVisible():
            self.bubble.reposition(rect)
        if self.input.isVisible():
            self.input.reposition(rect)
        if self.badge and self.badge.isVisible():
            self.badge.reposition(rect)
        if self._exam_badge and self._exam_badge.isVisible():
            self._place_exam_badge()
        if self.trans_popup.isVisible():
            self.trans_popup.reposition(rect)

    def moveEvent(self, e):
        # Moving across monitors can change the device-pixel-ratio; keep our
        # rendering/hit-test scale in sync so she doesn't blur or mis-align.
        self._sync_dpr()
        self._reposition_popups()
        super().moveEvent(e)

    def _current_dpr(self):
        """Device-pixel-ratio of the screen the window currently sits on."""
        pt = self.frameGeometry().center()
        scr = QtWidgets.QApplication.screenAt(pt) or self.screen()
        return scr.devicePixelRatio() if scr else 1.0

    def _sync_dpr(self):
        """Refresh `_dpr` when the window has moved to a differently-scaled
        screen, and immediately re-key the current frame at the new density."""
        dpr = self._current_dpr()
        if abs(dpr - self._dpr) < 1e-3:
            return
        self._dpr = dpr
        # Cached frames were keyed at the old density; rebuild by replaying the
        # current action at the new one (re-decodes and re-fills the cache).
        if self._cur_action is not None:
            self.play(self._cur_action.name)

    # ------------------------------------------------------------------ #
    # Playback                                                             #
    # ------------------------------------------------------------------ #

    def play(self, action_name):
        action = self.char.action(action_name)
        if action is None:
            return
        clip = action.pick_clip()
        if clip is None:
            return
        if self._cap is not None:
            self._cap.release()
        self._cap = cv2.VideoCapture(clip)
        self._cur_action = action
        self._loops_left = action.loop_count
        # Reset the per-clip frame cache. Only sustained loops (idle/sit/sleep/
        # move/drag) are worth caching; short loop_count clips aren't.
        self._frames = []
        self._mem.clear_cache()         # release old clip's budget
        self._compress_timer.stop()     # cancel in-flight compression
        self._compress_i = 0
        self._replay = False
        self._replay_i = 0
        self._caching = action.loop
        self._cache_full = False        # reset budget tracker for this clip
        self._skip_count = 0            # reset frame-skip counter
        # 按视频原生帧率播放（保持原始速度）；QTimer 0ms 未定义且烧 CPU，下限 1ms。
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        if fps and fps > 1:
            interval = round(1000 / fps)
        else:
            interval = action.interval
        self._timer.start(max(1, interval))
        self._schedule_rest(action_name)

    # ------------------------------------------------------------------ #
    # Idle rest cycle (idle -> sit -> sleep)                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _range_ms(cfg, def_lo_s, def_hi_s):
        """Normalise a [min,max] seconds config into a (min_ms, max_ms) pair."""
        lo, hi = def_lo_s, def_hi_s
        if isinstance(cfg, (list, tuple)) and len(cfg) == 2:
            lo, hi = float(cfg[0]), float(cfg[1])
        if hi < lo:
            lo, hi = hi, lo
        return int(lo * 1000), int(hi * 1000)

    def _schedule_rest(self, action_name):
        """Arm/disarm the relaxation timer based on the action just started.

        Each transition waits a fresh random duration inside its configured
        range: she stands (idle) 5-10 min, then sits 1-2 h before lying down.
        """
        self._rest_timer.stop()
        if action_name == "idle":
            self._rest_timer.start(random.randint(*self._idle_to_sit_ms))
        elif action_name == "sit":
            self._rest_timer.start(random.randint(*self._sit_to_sleep_ms))
        # sleep holds; every other action suppresses resting entirely.

    def _rest_step(self):
        """Advance one step down the relaxation chain when time elapses."""
        if self._cur_action is None:
            return
        if self._cur_action.name == "idle":
            self.play("sit")
        elif self._cur_action.name == "sit":
            self.play("sleep")

    def _wake(self):
        """Return to idle if she's currently sitting or sleeping."""
        if self._cur_action and self._cur_action.name in ("sit", "sleep"):
            self.play("idle")
            return True
        return False

    def _tick(self):
        # 隐藏（托盘/最小化）时不渲染：省掉解码/重绘的无效开销。
        if not self.isVisible():
            return
        # ── replay path: serve cached frames from memory ────────────────
        # 缓存里是压缩过的 PNG 字节，重放时解出来显示。
        if self._replay:
            cached = self._frames[self._replay_i]
            if isinstance(cached, bytes):
                import numpy as np
                bgra = cv2.imdecode(np.frombuffer(cached, np.uint8),
                                    cv2.IMREAD_UNCHANGED)
            else:
                bgra = cached
            self._show(bgra)
            self._replay_i = (self._replay_i + 1) % len(self._frames)
            self._mem.tick_gc()
            return
        if self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok:
            # First pass finished.
            if (self._cur_action.loop and self._frames
                    and not self._cache_full):
                self._cap.release()
                self._cap = None
                self._replay = True
                self._replay_i = 1 % len(self._frames)
                cached = self._frames[0]
                if isinstance(cached, bytes):
                    import numpy as np
                    bgra = cv2.imdecode(np.frombuffer(cached, np.uint8),
                                        cv2.IMREAD_UNCHANGED)
                else:
                    bgra = cached
                self._show(bgra)
                # 重放期间后台把原始帧压成 PNG 腾内存（不占热路径）。
                self._compress_i = 0
                self._compress_timer.start(120)
                return
            if self._cur_action.loop:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                if not ok:
                    return
            elif self._loops_left > 0:
                self._loops_left -= 1
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                if not ok:
                    return
            else:
                self._timer.stop()
                next_action = self._cur_action.next or "idle"
                self.play(next_action)
                return
        # ── frame skip: under memory pressure, skip expensive key_frame
        # processing for non-critical frames.  Skip only outside the active
        # caching pass (which needs every frame for a smooth loop) and
        # outside replay (which is already cheap).  Skipped ticks don't
        # re-show: the label already displays the last frame, so there is
        # nothing to repaint.
        div = self._mem.fps_divisor
        can_skip = (not self._caching) or self._cache_full
        if div > 1 and can_skip and self._last_bgra is not None:
            self._skip_count += 1
            if self._skip_count % div != 0:
                self._mem.tick_gc()
                return
        bgra = key_frame(frame, self.char.scale * self._dpr)
        # ── first pass: store raw BGRA (fast, keeps original playback speed) ──
        # 预算按"估算压缩后大小"记账（PNG 约 10-15:1），而不是原始大小——
        # 否则几帧就撑爆预算导致缓存中止、每轮循环全量重抠图。
        # 实际压缩由 _compress_tick 在重放期间后台完成，并把账目修正为真实值。
        if self._caching and not self._cache_full:
            raw_mb = bgra.nbytes / (1024 * 1024)
            est_mb = max(0.05, raw_mb / 12.0)
            if self._mem.can_cache(est_mb):
                self._frames.append(bgra)
                self._mem.add_cached(est_mb)
            else:
                self._cache_full = True
                self._mem.force_collect()
        self._show(bgra)
        self._last_bgra = bgra      # save for potential frame-skip reuse
        self._mem.tick_gc()

    def _compress_tick(self):
        """Lazy background compression: convert one cached raw BGRA frame to
        PNG bytes per call.  Runs during replay so animation stays smooth;
        memory gradually shrinks without any hot-path encoding cost."""
        if self._compress_i >= len(self._frames):
            self._compress_timer.stop()
            return
        cached = self._frames[self._compress_i]
        if isinstance(cached, bytes):
            # Already compressed (shouldn't happen, but guard it).
            self._compress_i += 1
            return
        ok, png = cv2.imencode(".png", cached,
                                [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if ok:
            png_bytes = png.tobytes()
            old_mb = cached.nbytes / (1024 * 1024)
            new_mb = len(png_bytes) / (1024 * 1024)
            self._frames[self._compress_i] = png_bytes
            # 账目从"首遍的估算值"修正为真实压缩大小（对齐 _tick 的记账）。
            est_mb = max(0.05, old_mb / 12.0)
            self._mem.add_cached(new_mb - est_mb)
        self._compress_i += 1

    def _show(self, bgra):
        ph, pw = bgra.shape[:2]                 # physical pixels
        self._alpha = bgra[:, :, 3]
        self._bbox = None                       # frame changed -> recompute lazily
        # OpenCV BGRA byte order (B,G,R,A) == Qt Format_ARGB32 on x86
        # (little-endian 0xAARRGGBB → bytes B,G,R,A).  Skip the cvtColor
        # copy entirely — saves one full-frame allocation per tick.
        self._qimg = QtGui.QImage(bgra.data, pw, ph, 4 * pw,
                                  QtGui.QImage.Format_ARGB32)
        pm = QtGui.QPixmap.fromImage(self._qimg)
        pm.setDevicePixelRatio(self._dpr)       # map physical -> logical 1:1
        self.label.setPixmap(pm)
        # Logical (on-screen) size = physical / dpr.
        lw, lh = round(pw / self._dpr), round(ph / self._dpr)
        if self.size() != QtCore.QSize(lw, lh):
            self.resize(lw, lh)
            self.label.resize(lw, lh)
            # The window has no size until the first frame arrives, so do the
            # initial placement now rather than in __init__（恢复上次位置）。
            if not self._first_frame_shown:
                self._first_frame_shown = True
                self._restore_position()

    # ------------------------------------------------------------------ #
    # Geometry helpers                                                     #
    # ------------------------------------------------------------------ #

    def _place_bottom_center(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2,
                  screen.bottom() - self.height())

    # ── 位置记忆：记住停靠位置，重启/多屏变化时恢复 ─────────────────────

    def _save_pet_position(self):
        """把当前窗口位置写入 prefs（拖拽结束 / 退出时调用）。"""
        g = self.frameGeometry()
        try:
            self.prefs.set("pet_pos", [g.x(), g.y()])
        except Exception:
            pass

    def _position_visible(self, x, y, w, h):
        """窗口矩形是否落在某个屏幕的可用区域内（多显示器 / 拔掉显示器检测）。"""
        rect = QtCore.QRect(x, y, w, h)
        for screen in QtWidgets.QApplication.screens():
            if rect.intersects(screen.availableGeometry()):
                return True
        return False

    def _restore_position(self):
        """恢复上次停靠位置；保存的位置已不在任何屏幕（拔了外接屏）时，
        回退到主屏底部居中。"""
        pos = self.prefs.get("pet_pos")
        if (isinstance(pos, (list, tuple)) and len(pos) == 2
                and self._position_visible(int(pos[0]), int(pos[1]),
                                           self.width(), self.height())):
            self.move(int(pos[0]), int(pos[1]))
            return
        self._place_bottom_center()

    def _body_rect(self):
        """Global-coord QRect of Amiya's visible body (opaque pixels).

        The window frame contains lots of transparent space and she sits
        off-centre, so popups anchor to this rather than the whole frame.
        """
        if self._alpha is None:
            return self.frameGeometry()
        # The opaque-pixel bounds only change when the frame does, so scan the
        # alpha once per frame and cache the result (logical px, window-local).
        # moveEvent (fires densely while dragging) then just re-maps to global.
        if self._bbox is None:
            import numpy as np
            ys, xs = np.where(self._alpha > 40)
            if len(xs) == 0:
                return self.frameGeometry()
            d = self._dpr  # alpha is in physical px; geometry is logical
            self._bbox = (int(xs.min() / d), int(ys.min() / d),
                          int((xs.max() - xs.min()) / d),
                          int((ys.max() - ys.min()) / d))
        x, y, w, h = self._bbox
        return QtCore.QRect(self.mapToGlobal(QtCore.QPoint(x, y)),
                            QtCore.QSize(w, h))

    def _opaque_at(self, pos):
        """True if the pixel under `pos` belongs to the character (not bg)."""
        if self._alpha is None:
            return False
        x, y = int(pos.x() * self._dpr), int(pos.y() * self._dpr)  # -> physical
        if 0 <= y < self._alpha.shape[0] and 0 <= x < self._alpha.shape[1]:
            return self._alpha[y, x] > 40
        return False

    def nativeEvent(self, eventType, message):
        """让透明区域的点击真正穿透到桌面（Windows WM_NCHITTEST 命中测试）。

        mousePressEvent 里的 e.ignore() 只让 Qt 忽略事件，并不会把点击交给
        下层窗口——透明背景会一直挡住桌面图标。对 WM_NCHITTEST 返回
        HTTRANSPARENT，Windows 才会把鼠标消息传给下层窗口；角色本体
        （不透明像素）返回客户端区域，照常响应点击/拖拽。
        """
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
                        return True, -1    # HTTRANSPARENT -> 穿透到下层
                elif msg.message == self._show_request_msg():
                    # 单实例：第二个实例广播的「显示请求」——回到前台
                    self._show_pet()
                    return True, 0
            except Exception:
                pass  # 命中测试失败就按默认行为处理，不让它崩应用
        return super().nativeEvent(eventType, message)

    def _show_request_msg(self):
        """单实例「显示请求」消息 id（惰性注册，跨进程一致）。"""
        if getattr(self, "_show_msg_id", None) is None:
            self._show_msg_id = single_instance.show_message_id()
        return self._show_msg_id or -1

    # ------------------------------------------------------------------ #
    # Interactions                                                         #
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, e):
        # Clicks on transparent area fall through to the desktop.
        if not self._opaque_at(e.pos()):
            e.ignore()
            return
        if e.button() == QtCore.Qt.LeftButton:
            self._drag_offset = e.globalPos() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and e.buttons() & QtCore.Qt.LeftButton:
            self.move(e.globalPos() - self._drag_offset)
            if not self._moved:
                self._moved = True
                self.play(self.char.interaction("on_drag") or "move")

    def mouseReleaseEvent(self, e):
        was_dragging = self._drag_offset is not None
        self._drag_offset = None
        if was_dragging and self._moved:
            self.play("idle")
            self._save_pet_position()   # 记住停靠位置
        elif was_dragging and self._opaque_at(e.pos()):
            self.play(self.char.interaction("on_click") or "click")
            self.voice.play("click")

    def mouseDoubleClickEvent(self, e):
        if self._opaque_at(e.pos()):
            self.open_chat()

    def _menu(self, pos):
        m = QtWidgets.QMenu(self)
        m.setStyleSheet(theme.MENU_QSS)
        # Show the hotkey hint only when it actually registered.
        hint = ("（%s）" % self._hotkey_spec.title()
                if getattr(self, "hotkey", None) and self.hotkey.active else "")
        m.addAction("和%s聊天…" % self.char.display_name + hint, self.open_chat)
        m.addAction("翻译剪贴板（Alt+T）", self._translate_clipboard)
        m.addAction("忘记对话", self._forget_chat)
        m.addAction("模型配置…", self._open_ai_settings)
        m.addAction("应用白名单…", self._open_app_whitelist)
        m.addAction("设置…", self._open_settings)
        if not self.brain.online:
            status = "AI 离线（用内置台词）"
        elif self.brain.cfg.get("allow_actions", True):
            status = "AI 在线 · 可操作电脑"
        else:
            status = "AI 在线"
        act = m.addAction(status)
        act.setEnabled(False)
        m.addSeparator()
        self._add_character_menu(m)
        m.addSeparator()
        self._add_schedule_menu(m)
        m.addSeparator()
        self._add_tasks_menu(m)
        m.addSeparator()
        self._add_ocr_menu(m)
        m.addSeparator()
        self._add_focus_menu(m)
        m.addSeparator()
        m.addAction("打招呼", lambda: self._act_voice("greet", "greet"))
        m.addAction("施放技能", lambda: self._act_voice("skill_begin", "skill"))
        m.addAction("休息一下", lambda: self._act_voice("sit", "sit"))
        m.addSeparator()
        self._add_clone_menu(m)
        m.addSeparator()
        self._add_volume_menu(m)
        m.addAction("退出", self._quit)
        m.exec_(self.mapToGlobal(pos))

    def _open_ai_settings(self):
        dlg = AiSettingsDialog(self.char.dir, self.brain.cfg, self,
                               self.char.display_name)
        dlg.saved.connect(self._apply_ai_settings)
        dlg.exec_()

    def _open_app_whitelist(self):
        """打开应用白名单管理对话框（添加/删除阿米娅可启动的程序）。"""
        AppWhitelistDialog(self).exec_()

    def _open_settings(self):
        """打开统一设置对话框（语音 / 热键 / 通用）。

        热键重注册放在对话框的 exec_() 返回之后（下一轮事件循环）：
        在模态对话框的嵌套事件循环里调用 RegisterHotKey / 安装原生事件
        过滤器是 Qt 原生层的高危操作，可能直接让进程崩溃（绕过 Python
        异常钩子、日志无痕）。
        """
        from .settings_ui import SettingsDialog
        SettingsDialog(self).exec_()
        QtCore.QTimer.singleShot(0, self._apply_hotkey_overrides)

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

    def _forget_chat(self):
        """Clear the remembered conversation (memory + disk)."""
        self.brain.clear_history()
        self.trans_popup.hide()
        self.bubble.say("好的博士，我们重新开始吧。", self._body_rect())

    def _act_voice(self, action, voice_event):
        """Play an animation and its matching voice line together."""
        self.play(action)
        self.voice.play(voice_event)

    def _add_character_menu(self, parent):
        sub = parent.addMenu("切换人物")
        placeholder = sub.addAction("加载中…")
        placeholder.setEnabled(False)
        # Populate lazily when the submenu is actually opened: scanning every
        # character directory on every right-click is wasted work and can stall
        # the menu on slow disks. The scan itself is mtime-cached too.
        sub.aboutToShow.connect(
            lambda s=sub: self._populate_character_menu(s))

    def _populate_character_menu(self, sub):
        sub.clear()
        current = os.path.normcase(self.char.dir)
        chars = self._available_characters()
        if not chars:
            act = sub.addAction("未找到其他人物")
            act.setEnabled(False)
        for char in chars:
            act = sub.addAction(char.display_name)
            act.setCheckable(True)
            act.setChecked(os.path.normcase(char.dir) == current)
            act.triggered.connect(
                lambda checked=False, path=char.dir: self._switch_character(path))
        if chars:
            sub.addSeparator()
        sub.addAction("添加新角色…", self._add_character_entry)

    def _add_character_entry(self):
        """GUI 入口：选素材文件夹 → 自动生成新角色。"""
        src = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择角色素材文件夹（内含动画 webm）",
            os.path.expanduser("~"))
        if not src:
            return
        key, ok = QtWidgets.QInputDialog.getText(
            self, "角色标识", "角色 key（英文小写，如 amiya2）：")
        if not ok or not key.strip():
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "显示名称", "显示名称（如 能天使）：",
            text=key.strip())
        if not ok:
            return
        try:
            from .add_character import add_character
            result = add_character(key.strip(), name.strip(), src)
        except ValueError as e:
            self.raise_()
            self.bubble.say(str(e), self._body_rect())
            return
        except Exception as e:
            self.raise_()
            self.bubble.say("添加失败：%s" % type(e).__name__, self._body_rect())
            return
        # 角色缓存失效，下次打开「切换人物」能看到新角色
        self._chars_cache = None
        self._chars_mtime = None
        voice = "，语音 %d 条" % result["voice_count"] if result["voice_count"] else ""
        self._announce("已添加角色「%s」，动作：%s%s。右键菜单即可切换。"
                       % (result["display_name"], "/".join(result["actions"]),
                          voice), use_tts=False)

    def _add_schedule_menu(self, parent):
        """课程表子菜单：今日课程 / 下一节课 / 本周课表 / 导入。"""
        sub = parent.addMenu("课程表")
        sub.addAction("今天课程", self._show_today)
        sub.addAction("下一节课", self._show_next)
        sub.addAction("本周课表", self._show_week)
        sub.addSeparator()
        sub.addAction("导入课表…", self._import_schedule)

    def _add_focus_menu(self, parent):
        """Submenu: reminder / countdown / pomodoro, plus a stop entry."""
        sub = parent.addMenu("专注小工具")
        sub.addAction("提醒事项…", self._reminder_dialog)
        sub.addAction("倒计时…", self._countdown_dialog)
        sub.addAction("番茄钟…", self._pomodoro_dialog)
        # Offer "stop" only when something is actually running.
        if self._pomo or self._cd_timer.isActive():
            sub.addSeparator()
            running = "番茄钟" if self._pomo else "倒计时"
            sub.addAction("停止%s" % running, self._stop_focus)

    def _add_clone_menu(self, parent):
        """Context-menu control for the (manually started) voice-clone service.

        The clone service loads a 2-4 GB model into GPU memory, so it's only
        started on explicit request — never on first TTS. The label reflects
        the live state so the user can also stop it and free the VRAM.
        """
        if not self._use_clone:
            return  # character configured without a cloned voice
        state = tts.clone_state()
        if state == "running":
            parent.addAction("停止语音克隆服务（释放显存）", self._stop_clone)
        elif state == "starting":
            act = parent.addAction("语音克隆服务加载中…")
            act.setEnabled(False)
        else:
            parent.addAction("启动语音克隆服务（AI 声线）", self._start_clone)

    # ── clone-state background probe ────────────────────────────────────
    # The context menu labels the clone service start/stop control from the
    # cached tts.clone_state(). Probing /ping is a blocking HTTP call (up to
    # 0.6 s while the model loads), so it must never run on the GUI thread —
    # a one-shot QThread refreshes the cache every few seconds instead.

    def _schedule_clone_probe(self):
        probe = self._clone_probe
        if probe is not None and probe.isRunning():
            return  # previous probe still in flight
        probe = CloneStateProbe(self)
        probe.finished.connect(lambda p=probe: self._clone_probe_done(p))
        self._clone_probe = probe
        probe.start()

    def _clone_probe_done(self, probe):
        if self._clone_probe is probe:
            self._clone_probe = None
            state = tts.clone_state()
            self._update_tray_tooltip()   # 托盘提示同步克隆状态
            # 加载完成提醒：starting -> running 时气泡提示一次
            if state == "running":
                if self._clone_was_starting and not self._clone_notified:
                    self._clone_notified = True
                    self._note("语音克隆模型已就绪，博士可以用我的声音了。")
                self._clone_was_starting = False
            elif state == "starting":
                self._clone_was_starting = True
                self._clone_notified = False
            else:   # stopped
                self._clone_was_starting = False
                self._clone_notified = False

    # -- 自动更新检查（启动静默查 GitHub Releases）------------------------

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
        msg = "发现新版本 %s，点击前往下载。" % tag
        if getattr(self, "_tray", None):
            try:
                self._tray.messageClicked.disconnect()
            except Exception:
                pass
            self._tray.messageClicked.connect(
                lambda: webbrowser.open(html))
            self._tray.showMessage("阿米娅桌面宠物 · 发现新版本", msg,
                                   QtWidgets.QSystemTrayIcon.Information, 8000)
        else:
            self._note(msg)

    def _start_clone(self):
        """Manually start the voice-clone service (model load ~30s).

        manual=True：用户主动启动的服务不会被 10 分钟空闲自动停止——
        加载模型要 ~30s，被悄悄停掉会非常恼人；要释放显存请从菜单手动停。
        """
        was_running = tts.clone_state() == "running"
        ok = tts.start_clone_service(
            self._tts_cfg.get("clone_dir"), character=self._clone_character,
            manual=True)
        if ok and not was_running:
            tts.set_clone_state("starting")   # label updates immediately
            self._clone_was_starting = True
            self._clone_notified = False
        self._schedule_clone_probe()          # confirm 'starting' -> 'running'
        if ok:
            self._note("正在加载语音克隆模型，大约 30 秒后博士就能听到我的声音了。")
        else:
            self._note("语音克隆服务启动失败，请检查 voiceclone 部署。")

    def _stop_clone(self):
        """Manually stop the voice-clone service and free GPU memory."""
        tts.stop_clone_service()
        tts.set_clone_state("stopped")        # label updates immediately
        self._clone_was_starting = False
        self._clone_notified = False
        self._schedule_clone_probe()          # confirm the port is really gone
        self._note("语音克隆服务已停止，显存已释放。")

    def _note(self, text):
        """A silent status bubble (no TTS / voice line) for service feedback."""
        self._wake()
        self.raise_()
        self.trans_popup.hide()
        self.bubble.say(text, self._body_rect(),
                        auto_ms=max(READ_MS_MIN, READ_MS_MAX // 2))

    def _add_volume_menu(self, parent):
        """A submenu with a mute toggle and a 0-100 volume slider."""
        sub = parent.addMenu("语音音量")
        mute = sub.addAction("静音")
        mute.setCheckable(True)
        mute.setChecked(not self.voice.enabled)
        mute.toggled.connect(self._toggle_mute)
        sub.addSeparator()

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, sub)
        slider.setMinimum(0)
        slider.setMaximum(100)
        slider.setValue(int(round(self.voice.volume * 100)))
        slider.setFixedWidth(300)
        slider.valueChanged.connect(self._on_volume_slider)
        wa = QtWidgets.QWidgetAction(sub)
        wa.setDefaultWidget(slider)
        sub.addAction(wa)

        sub.addSeparator()
        tts_act = sub.addAction("朗读回答（语音合成）")
        tts_act.setCheckable(True)
        tts_act.setEnabled(self._tts_supported and tts.available())
        tts_act.setChecked(self._tts_on)
        tts_act.toggled.connect(self._set_tts)

    def _set_tts(self, on):
        self._tts_on = bool(on) and self._tts_supported and tts.available()
        self.prefs.set("tts_on", bool(on))

    def _toggle_mute(self, muted):
        self.voice.set_enabled(not muted)
        self.prefs.set("voice_enabled", not muted)

    def _on_volume_slider(self, value):
        self.voice.set_volume(value / 100.0)
        self._save_vol_timer.start(400)  # persist ~0.4s after the last drag

    def _quit(self):
        self._quitting = True   # 后续 closeEvent 直接放行，不再隐藏到托盘
        petlog.log("exit")
        self._save_pet_position()   # 退出前记住当前位置
        self._unregister_hotkeys()
        self.voice.stop()
        # Stop the clone-state probe (short-lived /ping thread) so it never
        # outlives the window; it is at most one /ping timeout long.
        self._clone_probe_timer.stop()
        probe = self._clone_probe
        if probe is not None and probe.isRunning():
            probe.wait(1500)
        # Stop in-flight worker threads so they don't keep HTTP connections
        # alive after the window is gone. requestInterruption() flags the
        # worker to bail out of blocking I/O early; terminate() is the
        # last-resort fallback when the thread is stuck anyway.
        for w in (self._worker, self._tts_worker, self._trans_worker,
                  self._ocr_worker):
            if w is not None and w.isRunning():
                w.requestInterruption()
                if not w.wait(3000):
                    w.terminate()
                    w.wait(1000)
        # 语音克隆服务必须随桌宠退出而退出：无论当前角色的 use_clone 是
        # 什么（切换角色后可能变成 False，但服务可能是之前角色/手动启动的），
        # 只要在跑就要停掉，否则残留 python 进程继续占显存。
        tts.stop_clone_service()
        # Release the audio file the player holds open, then delete the temp
        # speech files so conversation audio isn't left behind in %TEMP%.
        self.voice.stop()
        tts.cleanup_temp_files()
        self.bubble.close()
        self.input.close()
        self.trans_popup.close()
        if self.badge:
            self.badge.close()
        if getattr(self, "_exam_badge", None):
            self._exam_badge.close()
        if self._info_panel_widget is not None:
            self._info_panel_widget.close()
        QtWidgets.QApplication.quit()

    def closeEvent(self, event):
        """关闭窗口：隐藏到托盘而不是退出（Windows 关机/会话结束时才真退出）。

        语音克隆服务跟随进程生命周期：只要桌宠还驻留托盘，服务就一直可管理；
        真正退出（托盘「退出」/ 系统关机）时 _quit 会停掉克隆服务并清理。
        """
        app = QtWidgets.QApplication.instance()
        saving = bool(getattr(app, "isSavingSession", lambda: False)()) if app else False
        if (not getattr(self, "_tray", None) or self._quitting or saving):
            self._quit()
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self._tray.showMessage(
                "阿米娅还在",
                "桌宠已最小化到托盘。右键托盘图标可退出，或从托盘菜单快速开关语音。",
                QtWidgets.QSystemTrayIcon.Information, 4000)
