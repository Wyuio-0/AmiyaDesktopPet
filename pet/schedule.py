"""课程表：解析强智教务课表 JSON，提供查询与上课提醒。

数据链路
--------
用户从教务系统浏览器 Network 面板复制课表 JSON（xskbcx_cxXsksxxlist 响应），
本模块把它解析成内部 Course 列表并缓存，供菜单展示、上课提醒、AI 查询使用。

存储（均在用户数据目录，%APPDATA%\\AmiyaPet\\，不进仓库）：
  schedule_raw.json   强智原始 JSON（用户粘贴，留档便于每学期重新导入）
  schedule.json       解析后的内部格式（含 term_start / sections 等配置）

解析要点（强智字段 → 内部字段）：
  kcmc 课程名 | xqj 星期(1-7) | jc 节次("1-2") | zcd 周次("1-14周"/"8-12周(双)")
  cdmc 教室 | xm 教师 | xqmc 校区
特殊记录：pkbj=0 且 cdmc="未排地点" 的课（如实验课），教室从 xkbz 备注里捞。
sjkList 里的"无时间无地点"课（网课）不参与提醒，仅作展示。

节次时刻表（sections）与学期开始日期（term_start）都在 schedule.json 里，
可按本校作息修改。
"""

import json
import os
import re
from datetime import date, datetime, timedelta

from .settings import config_dir

# 常见作息（仅作默认展示，具体以 schedule.json 的 sections 为准）。
DEFAULT_SECTIONS = {
    "1": "08:00", "2": "08:50", "3": "09:50", "4": "10:40", "5": "11:30",
    "6": "14:00", "7": "14:50", "8": "15:40", "9": "16:30",
    "10": "18:30", "11": "19:20", "12": "20:10", "13": "21:00",
}
WEEKDAY_NAMES = {1: "周一", 2: "周二", 3: "周三", 4: "周四",
                 5: "周五", 6: "周六", 7: "周日"}
_PARITY_LABEL = {"all": "", "odd": "单", "even": "双"}


def _raw_path():
    return os.path.join(config_dir(), "schedule_raw.json")


def _data_path():
    return os.path.join(config_dir(), "schedule.json")


def parse_weeks(zcd):
    """'1-14周' -> (1, 14, 'all'); '8-12周(双)' -> (8, 12, 'even'); '单' 同理。

    返回 (start, end, parity) 或 None（解析失败）。
    """
    m = re.search(r"(\d+)\s*-\s*(\d+)", zcd or "")
    if not m:
        return None
    start, end = int(m.group(1)), int(m.group(2))
    parity = "even" if "双" in zcd else ("odd" if "单" in zcd else "all")
    return (start, end, parity)


def parse_sections(jc):
    """'1-2节' 或 '1-2' -> (1, 2)，返回 (start, end) 或 None。"""
    m = re.search(r"(\d+)\s*-\s*(\d+)", jc or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _room_of(rec):
    """教室：正常记录直接取 cdmc；'未排地点' 时从选课备注（xkbz）里捞，
    例如 '8,10,12周日2-5节A204' -> 'A204'。"""
    cdmc = (rec.get("cdmc") or "").strip()
    if cdmc and cdmc != "未排地点":
        return cdmc
    m = re.search(r"([A-Za-z]?\d{2,4}[A-Za-z]?\d*)$", (rec.get("xkbz") or "").strip())
    return m.group(1) if m else cdmc or "待定"


class Course:
    """一条上课安排。parity: 'all' / 'odd' / 'even'。"""

    __slots__ = ("name", "weekday", "sec_start", "sec_end",
                 "week_start", "week_end", "parity",
                 "room", "teacher", "campus", "note")

    def __init__(self, name, weekday, sec_start, sec_end,
                 week_start, week_end, parity, room="", teacher="",
                 campus="", note=""):
        self.name = name
        self.weekday = int(weekday)          # 1=周一 ... 7=周日
        self.sec_start = int(sec_start)
        self.sec_end = int(sec_end)
        self.week_start = int(week_start)
        self.week_end = int(week_end)
        self.parity = parity                 # 'all' / 'odd' / 'even'
        self.room = room
        self.teacher = teacher
        self.campus = campus
        self.note = note

    def active_on(self, week_no):
        """第 week_no 周是否上课（含单双周规则）。"""
        if not (self.week_start <= week_no <= self.week_end):
            return False
        if self.parity == "even":
            return week_no % 2 == 0
        if self.parity == "odd":
            return week_no % 2 == 1
        return True

    def start_time(self, week_no, sections):
        """第 week_no 周本节课的开始时刻 (hour, minute)，或 None（不在表内/本周不上）。"""
        if not self.active_on(week_no):
            return None
        hhmm = sections.get(str(self.sec_start))
        if not hhmm:
            return None
        try:
            hh, mm = hhmm.split(":")
            return (int(hh), int(mm))
        except (ValueError, TypeError):
            return None

    def display(self, sections=None, show_weeks=True):
        """一行展示文本，例如「1-2节 计算机组成与体系结构A @3区2-217」。
        节次区间换算时刻（若有 sections 且两端都在表内）。"""
        secs = "%d-%d节" % (self.sec_start, self.sec_end)
        when = ""
        if sections:
            a = sections.get(str(self.sec_start))
            b = sections.get(str(self.sec_end))
            if a and b:
                when = " (%s-%s)" % (a, b)
        weeks = ""
        if show_weeks:
            weeks = " %d-%d周%s" % (self.week_start, self.week_end,
                                    _PARITY_LABEL[self.parity])
        room = " @%s" % self.room if self.room else ""
        return "%s%s %s%s%s" % (secs, when, self.name, room, weeks)


def import_strongzhi(raw, term_start):
    """把强智课表 JSON（dict）解析成 Course 列表 + 无时间课列表。

    term_start: date，第 1 周周一。返回 (courses, note_courses)。
    解析失败的条目会被跳过并记录原因，不影响其余课程。
    """
    courses, notes, skipped = [], [], []
    for rec in raw.get("kbList", []):
        weeks = parse_weeks(rec.get("zcd"))
        secs = parse_sections(rec.get("jc"))
        name = (rec.get("kcmc") or "").strip()
        if not weeks or not secs or not name:
            skipped.append((name or "?", rec.get("zcd"), rec.get("jc")))
            continue
        try:
            weekday = int(rec.get("xqj", 0))
            if not 1 <= weekday <= 7:
                raise ValueError("xqj=%s" % rec.get("xqj"))
        except (TypeError, ValueError):
            skipped.append((name, rec.get("zcd"), "xqj=" + str(rec.get("xqj"))))
            continue
        w1, w2, parity = weeks
        courses.append(Course(
            name=name, weekday=weekday,
            sec_start=secs[0], sec_end=secs[1],
            week_start=w1, week_end=w2, parity=parity,
            room=_room_of(rec),
            teacher=(rec.get("xm") or "").strip(),
            campus=(rec.get("xqmc") or "").strip(),
            note="实验" if str(rec.get("pkbj")) == "0" else "",
        ))
    for rec in raw.get("sjkList", []):
        name = (rec.get("kcmc") or "").strip()
        if name:
            notes.append("%s / %s / %s" % (name, rec.get("jsxm", ""),
                                           rec.get("qsjsz", "")))
    return courses, notes, skipped


class Schedule:
    """加载/保存内部格式，提供按天/按周查询与"下一节课"。

    内部格式（schedule.json）：
    {
      "term": "2026-2027-1",
      "term_start": "2026-09-07",        # 第 1 周周一
      "sections": {"1": "08:00", ...},   # 节次时刻表，可按校作息修改
      "courses": [ {...}, ... ]
    }
    """

    def __init__(self, path=None):
        self.path = path or _data_path()
        self.term = ""
        self.term_start = None            # date
        self.sections = dict(DEFAULT_SECTIONS)
        self.remind_minutes = 10          # 上课前多少分钟提醒
        self.courses = []
        self.notes = []                   # 无时间课说明文本
        self.load()

    # ── 持久化 ─────────────────────────────────────────────────────

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        self.term = str(data.get("term", ""))
        try:
            self.term_start = date.fromisoformat(str(data["term_start"]))
        except Exception:
            self.term_start = None
        sections = data.get("sections") or {}
        self.sections = {str(k): str(v) for k, v in sections.items()}
        self.remind_minutes = max(1, int(data.get("remind_minutes", 10) or 10))
        self.courses = []
        for c in data.get("courses", []):
            try:
                self.courses.append(Course(
                    name=c["name"], weekday=c["weekday"],
                    sec_start=c["sec_start"], sec_end=c["sec_end"],
                    week_start=c["week_start"], week_end=c["week_end"],
                    parity=c.get("parity", "all"),
                    room=c.get("room", ""), teacher=c.get("teacher", ""),
                    campus=c.get("campus", ""), note=c.get("note", "")))
            except (KeyError, TypeError, ValueError):
                continue
        self.notes = list(data.get("notes", []))

    def save(self, term="", term_start=None, courses=None, notes=None,
             sections=None):
        if courses is not None:
            self.courses = courses
        if notes is not None:
            self.notes = notes
        if term:
            self.term = term
        if term_start:
            self.term_start = term_start
        if sections:
            self.sections = sections
        payload = {
            "term": self.term,
            "term_start": self.term_start.isoformat() if self.term_start else "",
            "sections": self.sections,
            "remind_minutes": self.remind_minutes,
            "courses": [self._course_dict(c) for c in self.courses],
            "notes": self.notes,
        }
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

    @staticmethod
    def _course_dict(c):
        return {"name": c.name, "weekday": c.weekday,
                "sec_start": c.sec_start, "sec_end": c.sec_end,
                "week_start": c.week_start, "week_end": c.week_end,
                "parity": c.parity, "room": c.room, "teacher": c.teacher,
                "campus": c.campus, "note": c.note}

    # ── 查询 ───────────────────────────────────────────────────────

    def week_no(self, day=None):
        """今天（或给定日期）是第几周（1 起）。term_start 未配置时返回 None。"""
        day = day or date.today()
        if not self.term_start:
            return None
        delta = day - self.term_start
        if delta.days < 0:
            return 0
        return delta.days // 7 + 1

    def courses_on(self, weekday, week_no=None):
        """某天（weekday 1-7）的课程；week_no 为 None 时不做周次过滤。"""
        out = [c for c in self.courses if c.weekday == weekday]
        if week_no is not None:
            out = [c for c in out if c.active_on(week_no)]
        return sorted(out, key=lambda c: c.sec_start)

    def today(self, week_no=None):
        return self.courses_on(date.today().isoweekday(), week_no)

    def next_class(self, now=None, week_no=None):
        """从 now 起最近的下一节课（含当前周），返回 (course, weekday, week_no,
        start_datetime) 或 None（本周没有后续课）。"""
        now = now or datetime.now()
        if week_no is None:
            week_no = self.week_no(now.date())
        if not week_no or week_no <= 0:
            return None
        today_idx = now.isoweekday()
        for offset in range(0, 7 - today_idx + 1):
            weekday = today_idx + offset
            if weekday > 7:
                continue
            day = now.date() + timedelta(days=offset)
            for c in self.courses_on(weekday, week_no):
                hm = c.start_time(week_no, self.sections)
                if hm is None:
                    continue
                target = datetime.combine(day, datetime.min.time()) \
                    .replace(hour=hm[0], minute=hm[1])
                if target > now:
                    return (c, weekday, week_no, target)
        return None

    def dump_text(self, week_no=None):
        """整张课表文本（按星期排），week_no 用于标注单双周实际是否上课。"""
        lines = []
        for wd in range(1, 8):
            courses = self.courses_on(wd, None)   # 不过滤周次，才能标出"本周不上"
            if not courses:
                continue
            lines.append(WEEKDAY_NAMES[wd])
            for c in courses:
                mark = ""
                if week_no and not c.active_on(week_no):
                    mark = "  [本周不上]"
                lines.append("  " + c.display(self.sections) + mark)
        if self.notes:
            lines.append("无时间课程（网课）：")
            lines.extend("  - " + n for n in self.notes)
        return "\n".join(lines)
