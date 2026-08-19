"""作业 DDL / 考试倒计时：中文日期解析、任务管理与到期检查。

数据保存在用户数据目录（%APPDATA%\\AmiyaPet\\tasks.json，Windows），
与课程表、聊天历史一样不随打包分发。每个任务：
  {id, title, kind: 'homework'|'exam', course, due: 'YYYY-MM-DD HH:MM',
   remind_before_min: int, done: bool, created}

提醒逻辑：Schedule 负责"上课前提醒"，本模块负责"作业/考试到期提醒"，
两者都由窗口的周期定时器驱动（见 window._tasks_tick）。
"""

import json
import os
import re
import uuid
from datetime import date, datetime, timedelta

from .settings import config_dir

WEEKDAY_NAMES = {1: "周一", 2: "周二", 3: "周三", 4: "周四",
                 5: "周五", 6: "周六", 7: "周日"}


def _data_path():
    return os.path.join(config_dir(), "tasks.json")


# ── 中文日期/时间解析（纯函数，便于测试）────────────────────────────

_RE_WEEK = re.compile(r"(下?)(周|星期)([一二三四五六日天])")
_RE_MONTH_DAY = re.compile(r"(\d{1,2})月(\d{1,2})日?")
_RE_YEAR = re.compile(r"(\d{4})年")
_RE_DATE_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_RE_TIME_HM = re.compile(r"(\d{1,2}):(\d{2})")          # 23:59
_RE_TIME_HHMM = re.compile(r"(\d{1,2})点(\d{1,2})分")    # 9点30分
_RE_TIME_HH = re.compile(r"(\d{1,2})点(半)?")            # 9点 / 9点半


def _weekday_num(ch):
    return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7,
            "天": 7}[ch]


def parse_datetime(text, now=None):
    """从自然语言解析截止时间，返回 (datetime, ok)。

    支持：今天/明天/后天、周X/下周一、X月X日、XXXX年X月X日、YYYY-MM-DD，
    以及可选时间 23:59 / X点 / X点半。解析失败返回 (None, False)。
    默认时间：日期为今天时 23:59，否则 18:00。
    """
    now = now or datetime.now()
    today = now.date()
    text = (text or "").strip()
    if not text:
        return None, False

    day = None

    # 相对日期
    if text.startswith("今天"):
        day = today
    elif text.startswith("明天"):
        day = today + timedelta(days=1)
    elif text.startswith("后天"):
        day = today + timedelta(days=2)

    # 周X / 下周一
    m = _RE_WEEK.search(text)
    if day is None and m:
        wd = _weekday_num(m.group(3))
        days_ahead = (wd - today.isoweekday()) % 7
        if m.group(1) == "下":
            day = today + timedelta(days=7 + days_ahead)  # 下一周的该星期
        else:
            if days_ahead == 0:
                days_ahead = 7   # 今天就是这个星期 -> 下周同一天
            day = today + timedelta(days=days_ahead)

    # X月X日（可带年份）
    m = _RE_MONTH_DAY.search(text)
    if day is None and m:
        month, d = int(m.group(1)), int(m.group(2))
        year = int(_RE_YEAR.search(text).group(1)) if _RE_YEAR.search(text) \
            else today.year
        try:
            day = date(year, month, d)
            if day < today:
                day = date(year + 1, month, d)  # 已过则视为明年
        except ValueError:
            return None, False

    # YYYY-MM-DD
    m = _RE_DATE_ISO.search(text)
    if day is None and m:
        try:
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None, False

    if day is None:
        return None, False

    # 时间：23:59 / 9点 / 9点半 / 9点30分（三分支正则，避免歧义）
    hour, minute = (23, 59) if day == today else (18, 0)
    m = _RE_TIME_HM.search(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = _RE_TIME_HHMM.search(text)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
        else:
            m = _RE_TIME_HH.search(text)
            if m:
                hour = int(m.group(1))
                minute = 30 if m.group(2) else 0
    hour = min(hour, 23)
    minute = min(minute, 59)
    try:
        return datetime.combine(day, datetime.min.time()) \
            .replace(hour=hour, minute=minute), True
    except ValueError:
        return None, False


# ── 任务模型 ─────────────────────────────────────────────────────

class Task:
    __slots__ = ("id", "title", "kind", "course", "due", "remind_min",
                 "done", "created")

    def __init__(self, title, kind, due, course="", remind_min=60 * 24,
                 done=False, task_id=None, created=None):
        self.id = task_id or uuid.uuid4().hex[:12]
        self.title = title
        self.kind = kind            # 'homework' | 'exam'
        self.course = course
        self.due = due              # datetime
        self.remind_min = int(remind_min)   # 到期前多少分钟提醒
        self.done = bool(done)
        self.created = created or datetime.now()

    @property
    def remaining(self):
        return self.due - datetime.now()

    def is_due_soon(self, now=None):
        """进入提醒窗口（到期前 remind_min 内且尚未到期）返回 True。"""
        now = now or datetime.now()
        return timedelta(0) <= (self.due - now) <= timedelta(minutes=self.remind_min)

    def expired(self, now=None):
        now = now or datetime.now()
        return self.due < now and not self.done

    def to_dict(self):
        return {"id": self.id, "title": self.title, "kind": self.kind,
                "course": self.course, "due": self.due.strftime("%Y-%m-%d %H:%M"),
                "remind_min": self.remind_min, "done": self.done,
                "created": self.created.strftime("%Y-%m-%d %H:%M")}

    @classmethod
    def from_dict(cls, d):
        if not d.get("due"):
            return None
        return cls(
            title=d.get("title", ""), kind=d.get("kind", "homework"),
            due=datetime.strptime(d["due"], "%Y-%m-%d %H:%M"),
            course=d.get("course", ""), remind_min=d.get("remind_min", 1440),
            done=d.get("done", False), task_id=d.get("id"))


class Tasks:
    """作业/考试任务集合：加载、保存、增删、到期查询。"""

    def __init__(self, path=None):
        self.path = path or _data_path()
        self.items = []
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return
        self.items = []
        for d in raw.get("tasks", []):
            t = Task.from_dict(d)
            if t is not None:
                self.items.append(t)

    def save(self):
        payload = {"tasks": [t.to_dict() for t in self.items]}
        try:
            d = os.path.dirname(self.path)
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    def add(self, title, kind, due, course="", remind_min=1440):
        t = Task(title=title, kind=kind, due=due, course=course,
                 remind_min=remind_min)
        self.items.append(t)
        self.save()
        return t

    def remove(self, task_id):
        self.items = [t for t in self.items if t.id != task_id]
        self.save()

    def set_done(self, task_id, done=True):
        for t in self.items:
            if t.id == task_id:
                t.done = bool(done)
                break
        self.save()

    def upcoming(self, limit=None, include_done=False):
        """按到期时间升序的未完成任务。"""
        out = [t for t in self.items if (include_done or not t.done)
               and not t.expired()]
        out.sort(key=lambda t: t.due)
        return out[:limit] if limit else out

    def exams(self):
        return sorted([t for t in self.items
                       if t.kind == "exam" and not t.done and not t.expired()],
                      key=lambda t: t.due)

    def due_soon(self, now=None, remind_key=None):
        """进入提醒窗口的任务；remind_key 是 (task_id, 窗口起点) 去重用。"""
        now = now or datetime.now()
        out = []
        for t in self.items:
            if t.done or t.expired(now):
                continue
            if t.is_due_soon(now):
                out.append(t)
        return out

    def dump_text(self, limit=10):
        """即将到期清单文本（浮窗展示）。"""
        lines = []
        now = datetime.now()
        up = self.upcoming(limit=limit)
        if not up:
            return "当前没有待办任务。"
        for t in up:
            left = t.due - now
            if left.days >= 1:
                when = "%d天%d小时" % (left.days, left.seconds // 3600)
            else:
                when = "%d小时%d分" % (left.seconds // 3600,
                                       (left.seconds % 3600) // 60)
            tag = "考试" if t.kind == "exam" else "作业"
            course = "·%s" % t.course if t.course else ""
            lines.append("%s %s%s（剩%s）" % (
                tag, t.title, course, when))
        return "\n".join(lines)
