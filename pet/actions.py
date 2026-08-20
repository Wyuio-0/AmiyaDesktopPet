"""Safe, whitelisted computer-control actions Amiya can perform.

Only a fixed set of low-risk, reversible operations is exposed to the LLM:
no arbitrary command execution, no file deletion, no shutdown. Every call
returns a short human-readable result the model relays back to the user.
"""

import ctypes
import os
import subprocess
import sys
import urllib.parse
import webbrowser
from datetime import datetime

_IS_WIN = sys.platform == "win32"

# Friendly name (zh/en) -> launch target. Whitelist only.
APPS = {
    "记事本": "notepad", "notepad": "notepad",
    "计算器": "calc", "calc": "calc", "calculator": "calc",
    "画图": "mspaint", "paint": "mspaint",
    "文件管理器": "explorer", "资源管理器": "explorer", "explorer": "explorer",
    "任务管理器": "taskmgr", "task manager": "taskmgr", "taskmgr": "taskmgr",
    "设置": "ms-settings:", "settings": "ms-settings:",
}

# Virtual-key codes for media / volume keys.
_VK = {"mute": 0xAD, "voldown": 0xAE, "volup": 0xAF,
       "playpause": 0xB3, "next": 0xB0, "prev": 0xB1}


def _tap(vk, times=1):
    if not _IS_WIN:
        return
    u = ctypes.windll.user32
    for _ in range(times):
        u.keybd_event(vk, 0, 0, 0)
        u.keybd_event(vk, 0, 2, 0)  # 2 = KEYEVENTF_KEYUP


def open_app(name):
    key = (name or "").strip().lower()
    target = APPS.get(name) or APPS.get(key)
    if not target:
        allowed = "、".join(sorted(set(APPS.values())))
        return f"我只能打开这些程序：{allowed}"
    try:
        if target.endswith(":"):            # URI scheme, e.g. ms-settings:
            os.startfile(target)
        else:
            subprocess.Popen([target])
        return f"已经为博士打开{name}了。"
    except Exception as e:
        return f"打开{name}失败了：{type(e).__name__}"


def _is_public_web_url(url):
    """True if `url` is an ordinary public http(s) page.

    The model's tool calls are influenced by text it was given (chat input,
    clipboard content), so a prompt injection can choose this URL.  Two things
    are worth refusing even though normal browsing never needs them:

      * non-web schemes — `file:`, `javascript:`, `\\\\host\\share`.  A UNC path
        leaks NTLM credentials to whoever hosts the share.
      * loopback and private ranges — the browser runs with the user's cookies,
        so `127.0.0.1`/`192.168.x` targets a router admin page or some other
        local service's authenticated endpoints.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        parts.port                      # raises on a malformed port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower().rstrip(".")
    if host in ("localhost",) or host.endswith(".localhost"):
        return False
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True          # a normal domain name
    return not (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def open_url(url):
    if not url:
        return "博士想让我打开哪个网址呢？"
    url = str(url).strip()
    if "://" not in url:
        url = "https://" + url
    if not _is_public_web_url(url):
        return "这个地址我不能打开，只支持普通的公网网页。"
    webbrowser.open(url)
    return f"已经打开网页：{url}"


def web_search(query):
    if not query:
        return "博士想搜索什么？"
    url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
    webbrowser.open(url)
    return f"已经帮博士搜索「{query}」了。"


def set_volume(action, amount=4):
    amount = max(1, min(int(amount or 4), 10))
    if action == "mute":
        _tap(_VK["mute"]); return "已切换静音。"
    if action == "up":
        _tap(_VK["volup"], amount); return "音量调高了。"
    if action == "down":
        _tap(_VK["voldown"], amount); return "音量调低了。"
    return "音量操作只支持 up / down / mute。"


def media_control(action):
    vk = {"playpause": "playpause", "next": "next", "prev": "prev"}.get(action)
    if not vk:
        return "媒体操作只支持 playpause / next / prev。"
    _tap(_VK[vk])
    return {"playpause": "已切换播放/暂停。", "next": "已切到下一首。",
            "prev": "已切到上一首。"}[action]


def lock_screen():
    if _IS_WIN:
        ctypes.windll.user32.LockWorkStation()
        return "已锁定屏幕，博士慢走。"
    return "锁屏仅支持 Windows。"


def screenshot():
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        folder = os.path.join(os.path.expanduser("~"), "Pictures")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "pet_shot_" +
                            datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
        img.save(path)
        return f"截图已保存到：{path}"
    except Exception as e:
        return f"截图失败：{type(e).__name__}"


def get_datetime():
    wd = "一二三四五六日"[datetime.now().weekday()]
    return datetime.now().strftime(f"现在是 %Y年%m月%d日 星期{wd} %H:%M。")


# Scheduler hook, injected by the UI layer (runs on the main thread). Kept as a
# module global so the pure action handlers stay decoupled from Qt.
_scheduler = None


def set_scheduler(fn):
    """Register a callback fn(delay_seconds, message) used by set_reminder."""
    global _scheduler
    _scheduler = fn


def _fmt_delay(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}小时{m}分钟" if m else f"{h}小时"
    if m:
        return f"{m}分钟{s}秒" if s else f"{m}分钟"
    return f"{s}秒"


def set_reminder(delay_minutes=None, delay_seconds=None, message="时间到了"):
    """Schedule a one-off reminder after a relative delay."""
    total = 0.0
    if delay_minutes:
        total += float(delay_minutes) * 60
    if delay_seconds:
        total += float(delay_seconds)
    total = int(round(total))
    if total <= 0:
        return "博士，请告诉我多久之后提醒您呢？"
    if total > 24 * 3600:
        return "提醒最长只能设定 24 小时以内哦，博士。"
    if _scheduler is None:
        return "抱歉博士，现在无法设置提醒。"
    _scheduler(total, message or "时间到了")
    return f"好的博士，{_fmt_delay(total)}后我会提醒您：{message}"


# ── 课表 / 待办数据源（由 UI 层注入，保持本模块与 Qt 解耦）────────────

_schedule_provider = None
_tasks_provider = None


def set_schedule_provider(fn):
    """注册回调 fn() -> Schedule 实例（或 None），供查课表工具使用。"""
    global _schedule_provider
    _schedule_provider = fn


def set_tasks_provider(fn):
    """注册回调 fn() -> Tasks 实例（或 None），供待办工具使用。"""
    global _tasks_provider
    _tasks_provider = fn


def _fmt_courses(label, courses, sched, week_no):
    if not courses:
        return "%s没有课。" % label
    parts = []
    for c in courses:
        line = c.display(sched.sections)
        if week_no and not c.active_on(week_no):
            line += "（本周不上）"
        parts.append(line)
    return "%s有 %d 节课：\n%s" % (label, len(courses), "\n".join(parts))


def query_schedule(scope="today"):
    """查课表：scope ∈ today / tomorrow / week / next。"""
    sched = _schedule_provider() if _schedule_provider else None
    if sched is None or not sched.courses:
        return "还没有导入课表，请右键菜单 → 课程表 → 导入课表。"
    week_no = sched.week_no()
    if scope == "week":
        return sched.dump_text(week_no=week_no)
    if scope == "tomorrow":
        weekday = datetime.now().isoweekday() % 7 + 1
        return _fmt_courses("明天", sched.courses_on(weekday, week_no),
                            sched, week_no)
    if scope == "next":
        nxt = sched.next_class()
        if not nxt:
            return "本周没有剩下的课了，博士可以休息。"
        c, _, _, start = nxt
        where = " @%s" % c.room if c.room else ""
        return "下一节：%d-%d节 %s %s%s" % (c.sec_start, c.sec_end, c.name,
                                            start.strftime("%H:%M"), where)
    return _fmt_courses("今天", sched.today(week_no), sched, week_no)


def query_tasks():
    """列出未完成的作业/考试及剩余时间。"""
    tasks = _tasks_provider() if _tasks_provider else None
    if tasks is None:
        return "待办功能暂不可用。"
    if not tasks.items:
        return "当前没有待办任务，博士可以休息一下。"
    return tasks.dump_text(limit=15)


def today_summary():
    """一键汇总今日安排：今天的课程 + 待办/考试 + 最近考试倒计时。"""
    sched = _schedule_provider() if _schedule_provider else None
    tasks = _tasks_provider() if _tasks_provider else None
    parts = []

    # 今天的课程
    if sched is not None and sched.courses:
        week_no = sched.week_no()
        courses = sched.today(week_no)
        parts.append(_fmt_courses("今天", courses, sched, week_no)
                     if courses else "今天没有课。")

    # 待办（未完成的作业/考试）
    if tasks is not None:
        upcoming = tasks.upcoming(limit=8)
        if upcoming:
            lines = ["今日待办："]
            for t in upcoming:
                tag = "考试" if t.kind == "exam" else "作业"
                lines.append("  %s《%s》%s 截止" % (
                    tag, t.title, t.due.strftime("%m-%d %H:%M")))
            parts.append("\n".join(lines))
        exams = tasks.exams()
        if exams:
            t = exams[0]
            days = max((t.due - datetime.now()).days, 0)
            parts.append("最近的考试：%s，还有 %d 天。" % (t.title, days))

    if not parts:
        return "今天没有安排，博士可以自由安排。"
    return "\n\n".join(parts)


def add_task(title, due, course="", kind="homework"):
    """添加作业/考试待办；due 支持自然语言（明天/周五 23:59/9月20日）。"""
    from .tasks import parse_datetime
    tasks = _tasks_provider() if _tasks_provider else None
    if tasks is None:
        return "待办功能暂不可用。"
    if not title or not due:
        return "请告诉我要添加的事项和截止时间。"
    dt, ok = parse_datetime(due)
    if not ok:
        return ("我没能理解截止时间「%s」，请用例如「明天」「周五 23:59」"
                "「9月20日」这样的说法。" % due)
    kind = "exam" if str(kind).lower() in ("exam", "考试") else "homework"
    remind = 7 * 24 * 60 if kind == "exam" else 24 * 60
    tasks.add(title, kind=kind, due=dt, course=course, remind_min=remind)
    label = "考试" if kind == "exam" else "作业"
    return "已添加%s「%s」，%s 截止，阿米娅会提前提醒博士。" % (
        label, title, dt.strftime("%Y-%m-%d %H:%M"))


# name -> handler
_HANDLERS = {
    "open_app": open_app, "open_url": open_url, "web_search": web_search,
    "set_volume": set_volume, "media_control": media_control,
    "lock_screen": lock_screen, "screenshot": screenshot,
    "get_datetime": get_datetime, "set_reminder": set_reminder,
    "query_schedule": query_schedule, "query_tasks": query_tasks,
    "add_task": add_task, "today_summary": today_summary,
}


def run_action(name, args):
    """Dispatch a tool call. Returns a short result string."""
    fn = _HANDLERS.get(name)
    if not fn:
        return f"我还不会「{name}」这个操作。"
    try:
        return fn(**(args or {}))
    except TypeError:
        return fn()
    except Exception as e:
        return f"操作出错了：{type(e).__name__}"


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {},
                       "required": required or []}}}


# OpenAI/DeepSeek tools schema advertised to the model.
TOOLS = [
    _fn("open_app", "打开电脑上的一个常用程序",
        {"name": {"type": "string", "description": "程序名，如 记事本/计算器/画图/资源管理器/任务管理器/设置"}},
        ["name"]),
    _fn("open_url", "在默认浏览器打开一个网址",
        {"url": {"type": "string"}}, ["url"]),
    _fn("web_search", "用必应搜索关键词",
        {"query": {"type": "string"}}, ["query"]),
    _fn("set_volume", "调节系统音量",
        {"action": {"type": "string", "enum": ["up", "down", "mute"]},
         "amount": {"type": "integer", "description": "调节档位1-10，默认4"}},
        ["action"]),
    _fn("media_control", "控制媒体播放",
        {"action": {"type": "string", "enum": ["playpause", "next", "prev"]}},
        ["action"]),
    _fn("lock_screen", "锁定电脑屏幕"),
    _fn("screenshot", "全屏截图并保存到图片文件夹"),
    _fn("get_datetime", "获取当前日期和时间"),
    _fn("set_reminder",
        "设置一个定时提醒/闹钟/番茄钟，到时间后阿米娅会提醒博士",
        {"delay_minutes": {"type": "number", "description": "多少分钟后提醒"},
         "delay_seconds": {"type": "number", "description": "多少秒后提醒（可与分钟叠加）"},
         "message": {"type": "string", "description": "提醒内容，如「该休息了」「开会」"}},
        []),
    _fn("query_schedule", "查询课表（今天的课/明天的课/本周课表/下一节课）",
        {"scope": {"type": "string",
                   "enum": ["today", "tomorrow", "week", "next"],
                   "description": "today=今天, tomorrow=明天, week=本周, next=下一节课"}},
        []),
    _fn("query_tasks", "查询未完成的作业/考试及剩余时间"),
    _fn("add_task", "添加一个作业或考试的截止提醒（待办）",
        {"title": {"type": "string", "description": "事项名称，如 高数作业"},
         "due": {"type": "string",
                 "description": "截止时间（自然语言），如 明天 / 周五 23:59 / 9月20日 / 下周一"},
         "course": {"type": "string", "description": "所属课程（可选）"},
         "kind": {"type": "string", "enum": ["homework", "exam"],
                  "description": "作业或考试，默认作业"}},
        ["title", "due"]),
    _fn("today_summary",
        "一键汇总博士今天的安排：今天的课程、待办作业/考试、最近考试倒计时"),
]
