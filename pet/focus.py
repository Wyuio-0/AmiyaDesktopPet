"""专注工具与日程提醒管理器：番茄钟、倒计时、课程表、待办/考试与问候调度。"""

import json
import os
import random
from datetime import date, datetime, timedelta

from PyQt5 import QtCore, QtWidgets

from . import actions, schedule
from .schedule import Schedule
from .tasks import Tasks
from .tasks_ui import TaskDialog, TaskListDialog
from .timers import CountdownBadge, DurationDialog, PomodoroDialog


class PetFocusToolsManager(QtCore.QObject):
    """协调倒计时、番茄钟、AI提醒、课程表预警、待办/考试倒计时及早晚自动问候。"""

    def __init__(self, window):
        parent = window if isinstance(window, QtCore.QObject) else None
        super().__init__(parent)
        self.window = window

        # ── 1. 专注工具（倒计时 / 番茄钟）────────────────────────
        self.badge = CountdownBadge()
        self._cd_timer = QtCore.QTimer(self)
        self._cd_timer.timeout.connect(self._cd_tick)
        self._cd_left = 0
        self._cd_label = ""
        self._cd_done = None
        self._pomo = None   # None 或 dict(phase, round, rounds, work, brk)

        # ── 2. AI 动态提醒 ─────────────────────────────────────────
        self._reminders = []  # 保持 QTimer 引用

        # ── 3. 课程表 ──────────────────────────────────────────────
        self.schedule = Schedule()
        self._sched_reminded = set()
        self._sched_timer = QtCore.QTimer(self)
        self._sched_timer.timeout.connect(self.sched_tick)
        self._sched_timer.start(30 * 1000)

        # ── 4. 待办与考试 ──────────────────────────────────────────
        self.tasks = Tasks()
        self._task_reminded = set()
        self._tasks_timer = QtCore.QTimer(self)
        self._tasks_timer.timeout.connect(self.tasks_tick)
        self._tasks_timer.start(30 * 1000)

        self._exam_badge = CountdownBadge()
        self._exam_timer = QtCore.QTimer(self)
        self._exam_timer.timeout.connect(self.refresh_exam_badge)
        self._exam_timer.start(60 * 60 * 1000)  # 每小时刷新

        # ── 5. 时间段问候 ──────────────────────────────────────────
        self._greet_windows = []
        self._greet_timer = QtCore.QTimer(self)
        self._greet_timer.timeout.connect(self.check_greetings)

        self.setup_greetings()
        self.refresh_exam_badge()

    # ------------------------------------------------------------------ #
    # 专注小工具 (Countdown & Pomodoro)                                    #
    # ------------------------------------------------------------------ #

    def is_focus_active(self):
        """是否有正在运行的倒计时或番茄钟。"""
        return bool(self._pomo or self._cd_timer.isActive())

    def has_active_pomodoro(self):
        return bool(self._pomo)

    def cancel_countdown(self):
        """停止当前显示的倒计时徽章（不重置番茄钟状态机）。"""
        self._cd_timer.stop()
        self._cd_left = 0
        self._cd_done = None
        if self.badge:
            self.badge.hide()

    def start_countdown(self, seconds, label, on_done):
        """显示倒计时徽章并在归零时触发回调。"""
        self._cd_left = int(seconds)
        self._cd_label = label
        self._cd_done = on_done
        self._cd_tick()
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
                                 self.window._body_rect())
        self._cd_left -= 1

    def reminder_dialog(self):
        """弹出设置提醒对话框。"""
        dlg = DurationDialog("提醒事项", "SET A REMINDER", "该休息一下了", 10, self.window)
        dlg.confirmed.connect(self.start_reminder)
        dlg.exec_()

    def start_reminder(self, total, message):
        """启动普通定时提醒（无常驻徽章，到期后语音弹气泡）。"""
        self.schedule_reminder(total, message)
        self.window._announce("好的博士，%s后我会提醒您：%s"
                             % (actions._fmt_delay(total), message), use_tts=True)

    def countdown_dialog(self):
        """弹出设置倒计时对话框。"""
        dlg = DurationDialog("倒计时", "SET A COUNTDOWN", "倒计时结束", 5, self.window)
        dlg.confirmed.connect(self.start_manual_countdown)
        dlg.exec_()

    def start_manual_countdown(self, total, message):
        """启动手动倒计时（覆盖番茄钟）。"""
        self._pomo = None
        self.window._announce("倒计时开始，%s。博士加油！"
                             % actions._fmt_delay(total), use_tts=True)
        self.start_countdown(
            total, "⏳", lambda: self.window._announce("博士，%s" % message, use_tts=True))

    def pomodoro_dialog(self):
        """弹出番茄钟设置对话框。"""
        dlg = PomodoroDialog(self.window)
        dlg.confirmed.connect(self.start_pomodoro)
        dlg.exec_()

    def start_pomodoro(self, work, brk, rounds):
        """启动多轮番茄钟。"""
        self._pomo = {"phase": "work", "round": 1, "rounds": rounds,
                      "work": work, "brk": brk}
        self.window._announce("番茄钟开始咯，博士。第 1 轮，专注 %d 分钟，加油！" % work, use_tts=True)
        self.start_countdown(work * 60, "🍅专注", self._pomo_next)

    def _pomo_next(self):
        """番茄钟阶段推进。"""
        p = self._pomo
        if not p:
            return
        if p["phase"] == "work":
            if p["round"] >= p["rounds"]:
                self._pomo = None
                self.window._announce("博士，%d 轮番茄钟全部完成，辛苦了！好好休息吧。"
                                     % p["rounds"], use_tts=True)
                return
            p["phase"] = "break"
            self.window._announce("第 %d 轮专注结束，休息 %d 分钟，博士放松一下。"
                                 % (p["round"], p["brk"]), use_tts=True)
            self.start_countdown(p["brk"] * 60, "☕休息", self._pomo_next)
        else:
            p["phase"] = "work"
            p["round"] += 1
            self.window._announce("休息结束，第 %d 轮开始，继续专注 %d 分钟！"
                                 % (p["round"], p["work"]), use_tts=True)
            self.start_countdown(p["work"] * 60, "🍅专注", self._pomo_next)

    def stop_focus(self):
        """停止当前所有专注计时。"""
        self._pomo = None
        self.cancel_countdown()
        self.window._announce("好的博士，已经停下计时了。", use_tts=True)

    # ------------------------------------------------------------------ #
    # AI 定时提醒 (Reminders)                                              #
    # ------------------------------------------------------------------ #

    def schedule_reminder(self, seconds, message):
        """AI 调用的提醒调度：seconds 秒后在 UI 线程唤醒。"""
        t = QtCore.QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda: self._fire_reminder(t, message))
        t.start(seconds * 1000)
        self._reminders.append(t)

    def _fire_reminder(self, timer, message):
        if timer in self._reminders:
            self._reminders.remove(timer)
        self.window._announce("博士，%s" % message, use_tts=True)

    # ------------------------------------------------------------------ #
    # 课程表管理与提醒 (Schedule)                                          #
    # ------------------------------------------------------------------ #

    def sched_tick(self):
        """上课前 remind_minutes 分钟提醒一次（防重复）。"""
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
            key = (s.term_start.isoformat(), week_no, today, c.sec_start, c.name)
            if key in self._sched_reminded:
                continue
            self._sched_reminded.add(key)
            where = "在%s" % c.room if c.room else "地点待定"
            self.window._announce(
                "博士，还有%d分钟要上%s了，%s。" % (remind, c.name, where),
                use_tts=True)

    def show_today(self):
        """信息面板展示今天的课程。"""
        if not self.schedule.courses:
            self.window.bubble.say("还没有导入课表，右键菜单 → 课程表 → 导入课表。",
                                   self.window._body_rect())
            return
        p = self.window._info_panel()
        p.show_schedule("today")
        p.present()

    def show_next(self):
        """信息面板展示下一节课。"""
        if not self.schedule.courses:
            self.window.bubble.say("还没有导入课表，右键菜单 → 课程表 → 导入课表。",
                                   self.window._body_rect())
            return
        p = self.window._info_panel()
        p.show_schedule("next")
        p.present()

    def show_week(self):
        """信息面板展示本周完整课表。"""
        if not self.schedule.courses:
            self.window.bubble.say("还没有导入课表，右键菜单 → 课程表 → 导入课表。",
                                   self.window._body_rect())
            return
        p = self.window._info_panel()
        p.show_schedule("week")
        p.present()

    def import_schedule(self):
        """导入强智课表 JSON 文件。"""
        w = self.window
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            w, "选择强智课表 JSON", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            w.bubble.say("课表文件读取失败：%s" % type(e).__name__, w._body_rect())
            return
        if not raw.get("kbList") and not raw.get("sjkList"):
            w.bubble.say("这看起来不是强智课表 JSON（缺少 kbList）。", w._body_rect())
            return

        default = date.today() - timedelta(days=date.today().isoweekday() - 1)
        term_start = default
        text, ok = QtWidgets.QInputDialog.getText(
            w, "开学日期", "第 1 周周一的日期（YYYY-MM-DD）：", text=default.isoformat())
        if ok and text.strip():
            try:
                term_start = date.fromisoformat(text.strip())
            except ValueError:
                pass
        courses, notes, skipped = schedule.import_strongzhi(raw, term_start)
        if not courses:
            w.bubble.say("没有解析出课程，请检查 JSON 内容。", w._body_rect())
            return

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
        w._announce("课表导入完成，共 %d 门课%s。开学日期已设为 %s。"
                    % (len(courses), skipped_note, term_start.isoformat()),
                    use_tts=False)

    # ------------------------------------------------------------------ #
    # 待办与考试倒计时 (Tasks)                                             #
    # ------------------------------------------------------------------ #

    def tasks_tick(self):
        """检查作业/考试到期前提醒。"""
        now = datetime.now()
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
            self.window._announce("博士，%s《%s》还有 %s 到期，别忘了。"
                                 % (verb, t.title, when), use_tts=True)

    def refresh_exam_badge(self):
        """刷新常驻考试倒计时徽章。"""
        b = self._exam_badge
        if not b:
            return
        if not self.window.prefs.get("exam_badge", True):
            b.hide()
            return
        exams = self.tasks.exams()
        if not exams:
            b.hide()
            return
        t = exams[0]
        days = max((t.due - datetime.now()).days, 0)
        b.show_text("距%s\n还有 %d 天" % (t.title, days), self.window._body_rect())
        self.place_exam_badge()

    def place_exam_badge(self):
        """考试徽章定位到桌宠左上角（专注徽章在右上角）。"""
        b = self._exam_badge
        if not b:
            return
        rect = self.window._body_rect()
        x = rect.left() - b.width() // 2
        y = rect.top() - b.height() // 2
        b.move(max(0, x), max(0, y))

    def toggle_exam_badge(self, checked):
        """开关考试倒计时徽章。"""
        self.window.prefs.set("exam_badge", bool(checked))
        if checked:
            self.refresh_exam_badge()
        elif self._exam_badge:
            self._exam_badge.hide()

    def course_names(self):
        """返回课表里的去重课程名。"""
        return sorted({c.name for c in self.schedule.courses})

    def add_task(self, kind):
        """打开添加待办/考试对话框。"""
        dlg = TaskDialog(kind, courses=self.course_names(), parent=self.window)
        dlg.confirmed.connect(
            lambda title, course, due, remind: self._on_task_added(
                kind, title, course, due, remind))
        dlg.exec_()

    def _on_task_added(self, kind, title, course, due, remind_min):
        self.tasks.add(title, kind=kind, due=due, course=course,
                       remind_min=remind_min)
        when = due.strftime("%m-%d %H:%M")
        self.window._announce("已添加%s：《%s》%s到期，阿米娅会提前提醒博士。"
                             % ("考试" if kind == "exam" else "作业", title, when),
                             use_tts=False)

    def show_tasks(self):
        """信息面板展示待办/考试列表。"""
        p = self.window._info_panel()
        p.refresh_tasks()
        p.present()

    def show_exam_countdown(self):
        """信息面板展示待办/考试（含倒计时）。"""
        p = self.window._info_panel()
        p.refresh_tasks()
        p.present()

    def manage_tasks(self):
        """打开管理待办对话框。"""
        dlg = TaskListDialog(self.tasks, parent=self.window)
        dlg.exec_()

    # ------------------------------------------------------------------ #
    # 时间段问候 (Greetings)                                              #
    # ------------------------------------------------------------------ #

    def setup_greetings(self):
        """初始化早安/午休/深夜问候时间窗口。"""
        gcfg = self.window.char.cfg.get("greetings", {})
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
                    "inside": None,
                })
        self._greet_timer.stop()
        if self._greet_windows:
            QtCore.QTimer.singleShot(4000, self.check_greetings)
            self._greet_timer.start(60 * 1000)

    @staticmethod
    def _parse_hhmm(text):
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
        if start <= end:
            return start <= now_min < end
        return now_min >= start or now_min < end

    def check_greetings(self):
        """跨区间跳变时触发一次问候。"""
        now = datetime.now()
        now_min = now.hour * 60 + now.minute
        for w in self._greet_windows:
            inside = self._in_window(now_min, w["start"], w["end"])
            was_inside = w["inside"]
            w["inside"] = inside
            if inside and not was_inside:
                self.window._say_greeting(random.choice(w["lines"]))
                break

    # ------------------------------------------------------------------ #
    # 徽章重定位与资源释放                                                 #
    # ------------------------------------------------------------------ #

    def reposition_badges(self, body_rect):
        """窗口拖动或缩放时重新定位专注徽章与考试徽章。"""
        if self.badge and self.badge.isVisible():
            self.badge.reposition(body_rect)
        if self._exam_badge and self._exam_badge.isVisible():
            self.place_exam_badge()

    def close(self):
        """停止所有定时器并关闭徽章子窗口。"""
        self._cd_timer.stop()
        self._sched_timer.stop()
        self._tasks_timer.stop()
        self._exam_timer.stop()
        self._greet_timer.stop()
        for t in self._reminders:
            try:
                t.stop()
            except Exception:
                pass
        self._reminders.clear()

        if self.badge:
            self.badge.close()
        if self._exam_badge:
            self._exam_badge.close()
