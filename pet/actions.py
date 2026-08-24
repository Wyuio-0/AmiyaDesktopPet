"""Safe, whitelisted computer-control actions Amiya can perform.

Only a fixed set of low-risk, reversible operations is exposed to the LLM:
no arbitrary command execution, no file deletion, no shutdown/power-off.
Newer groups (system status, typing, clipboard, window management) stay
user-visible and reversible — typing is undoable via Ctrl+Z, closed windows
can be reopened, clipboard read is length-capped. Every call returns a short
human-readable result the model relays back to the user.
"""

import ctypes
import json
import os
import subprocess
import sys
import urllib.parse
import webbrowser
from datetime import datetime

_IS_WIN = sys.platform == "win32"

# Friendly name (zh/en) -> launch target. Whitelist only.
# 内置程序：系统自带走 PATH / URI 方案；常用软件按 exe 名走 App Paths 注册表解析。
# 自定义程序：编辑 %APPDATA%\AmiyaPet\apps.json（{"名字": "程序路径或 exe 名"}）。
APPS = {
    "记事本": "notepad", "notepad": "notepad",
    "计算器": "calc", "calc": "calc", "calculator": "calc",
    "画图": "mspaint", "paint": "mspaint",
    "文件管理器": "explorer", "资源管理器": "explorer", "explorer": "explorer",
    "任务管理器": "taskmgr", "task manager": "taskmgr", "taskmgr": "taskmgr",
    "设置": "ms-settings:", "settings": "ms-settings:",
    "命令行": "cmd", "命令提示符": "cmd", "cmd": "cmd",
    "powershell": "powershell", "终端": "wt", "windows terminal": "wt",
    "控制面板": "control", "control panel": "control",
    "浏览器": "msedge", "edge": "msedge", "microsoft edge": "msedge",
    "chrome": "chrome", "谷歌浏览器": "chrome",
    "firefox": "firefox", "火狐": "firefox",
    "微信": "wechat", "wechat": "wechat",
    "qq": "QQ", "QQ": "QQ",
    "网易云音乐": "cloudmusic", "网易云": "cloudmusic", "cloudmusic": "cloudmusic",
    "steam": "Steam", "Steam": "Steam",
}

_CUSTOM_APPS_CACHE = {}          # path -> (mtime, {name: target})


def _custom_apps_path():
    """apps.json 位置：环境变量可覆盖（测试用），默认 %APPDATA%\\AmiyaPet\\apps.json。"""
    return os.environ.get("PET_APPS_FILE") or os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "AmiyaPet", "apps.json")


def _load_custom_apps():
    """读取用户自定义程序白名单（按 mtime 缓存）。"""
    path = _custom_apps_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        _CUSTOM_APPS_CACHE[path] = (None, {})
        return {}
    entry = _CUSTOM_APPS_CACHE.get(path)
    if entry and entry[0] == mtime:
        return entry[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        custom = {str(k).strip(): str(v).strip()
                  for k, v in data.items() if str(v).strip()}
    except Exception:
        custom = {}
    _CUSTOM_APPS_CACHE[path] = (mtime, custom)
    return custom


def list_custom_apps():
    """当前白名单 {名字: 目标} 的副本（可安全修改，不影响缓存）。"""
    return dict(_load_custom_apps())


def _save_custom_apps(apps):
    """把整个白名单原子写回 apps.json 并刷新缓存；成功返回 True。"""
    path = _custom_apps_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        _CUSTOM_APPS_CACHE[path] = (os.path.getmtime(path), dict(apps))
        return True
    except Exception:
        return False


def add_custom_app(name, target):
    """添加/更新一个自定义程序到白名单。返回 (ok, message)。"""
    name = (name or "").strip()
    target = (target or "").strip()
    if not name or not target:
        return False, "名字和程序路径都不能为空。"
    if len(name) > 30:
        return False, "名字太长啦，最多 30 个字。"
    apps = _load_custom_apps()
    existed = name in apps
    apps[name] = target
    if not _save_custom_apps(apps):
        return False, "写入白名单失败，请检查 %APPDATA%\\AmiyaPet 目录权限。"
    return (True, "已更新「%s」的程序路径。" % name if existed
            else "已把「%s」加入白名单，阿米娅现在可以打开它了。" % name)


def remove_custom_app(name):
    """从白名单删除一个程序。返回 (ok, message)。"""
    name = (name or "").strip()
    apps = _load_custom_apps()
    if name not in apps:
        return False, "白名单里没有「%s」。" % name
    del apps[name]
    if not _save_custom_apps(apps):
        return False, "写入白名单失败。"
    return True, "已从白名单移除「%s」。" % name


def _resolve_app_paths(exe):
    """按 Windows「App Paths」注册表解析 exe 名 -> 完整路径（未安装返回 None）。"""
    if not _IS_WIN or not exe:
        return None
    try:
        import winreg
    except ImportError:
        return None
    if not exe.lower().endswith(".exe"):
        exe += ".exe"
    key_path = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
                + "\\" + exe)
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, key_path) as k:
                path, _ = winreg.QueryValueEx(k, None)
            if path and os.path.isfile(path):
                return path
        except OSError:
            continue
    return None


def _launch(target):
    """启动一个目标：URI 方案 / 绝对路径 / App Paths 解析 / PATH。"""
    if not target:
        return False
    if target.endswith(":"):            # URI scheme，如 ms-settings:
        os.startfile(target)
        return True
    resolved = target
    if (not os.path.isabs(target) and "\\" not in target
            and "/" not in target):
        resolved = _resolve_app_paths(target) or target
    try:
        subprocess.Popen([resolved])
        return True
    except Exception:
        try:
            os.startfile(resolved)
            return True
        except Exception:
            return False


def open_app(name):
    key = (name or "").strip().lower()
    all_apps = dict(APPS)
    all_apps.update(_load_custom_apps())
    target = all_apps.get(name) or all_apps.get(key)
    if not target:
        builtin = "、".join(sorted(set(all_apps.values())))
        return ("我只能打开这些程序：%s。想要更多，可以在右键菜单 → "
                "应用白名单… 里添加自定义程序。" % builtin)
    try:
        if _launch(target):
            return f"已经为博士打开{name}了。"
        return f"没找到 {name}，可能没安装，或在 apps.json 里配置了错误的路径。"
    except Exception as e:
        return f"打开{name}失败了：{type(e).__name__}"

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


# ── 电脑状态查询（只读）──────────────────────────────────────────

def _active_window_title():
    if not _IS_WIN:
        return ""
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return ""
    length = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    u.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def system_status():
    """只读电脑状态：前台窗口、电量、CPU/内存/磁盘占用、开机时长。"""
    parts = []
    title = _active_window_title()
    parts.append("前台窗口：" + (title or "（桌面）"))
    try:
        import psutil
        bat = psutil.sensors_battery()
        if bat is not None:
            charge = "充电中" if bat.power_plugged else "使用电池"
            parts.append(f"电量 {int(bat.percent)}%（{charge}）")
        parts.append(f"CPU {psutil.cpu_percent(interval=0.1):.0f}%")
        mem = psutil.virtual_memory()
        parts.append("内存 %.0f%%（已用 %dGB / %dGB）" % (
            mem.percent, mem.used // 2**30, mem.total // 2**30))
        try:
            disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:"))
            parts.append(f"磁盘 {disk.percent:.0f}%")
        except OSError:
            pass
        up = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        h, m = divmod(int(up.total_seconds()), 3600)
        parts.append(f"已开机 {h}小时{m}分钟")
    except Exception:
        pass
    return "；".join(parts)


# ── 键盘打字（SendInput Unicode，中文可用）────────────────────────

def _send_unicode(text):
    """逐字符模拟键盘输入到当前焦点窗口；成功返回 True。"""
    if not _IS_WIN:
        return False
    import time
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("_i",)
        _fields_ = [("type", wintypes.DWORD), ("_i", _I)]

    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    for ch in text:
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=1)          # INPUT_KEYBOARD
            inp.ki.wVk = 0
            inp.ki.wScan = ord(ch)
            inp.ki.dwFlags = flags
            inp.ki.time = 0
            inp.ki.dwExtraInfo = None
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp),
                                           ctypes.sizeof(INPUT))
        time.sleep(0.008)
    return True


def type_text(text, enter=False):
    """在当前处于焦点的窗口输入文字；enter=True 输入后按回车。"""
    text = (text or "").strip()
    if not text:
        return "博士想让我输入什么内容呢？"
    if len(text) > 500:
        return "内容太长了，我一次最多输入 500 个字。"
    if not _send_unicode(text):
        return "键盘输入仅支持 Windows。"
    if enter:
        _tap(0x0D)                       # VK_RETURN
    shown = text if len(text) <= 20 else text[:20] + "…"
    return f"已经在当前窗口输入了：{shown}"


# ── 剪贴板读写（长度受限，防止内容爆炸）──────────────────────────

def _clipboard_get():
    if not _IS_WIN:
        return None
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    u.OpenClipboard.restype = ctypes.c_bool
    u.IsClipboardFormatAvailable.restype = ctypes.c_bool
    u.GetClipboardData.restype = ctypes.c_void_p
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    CF_UNICODETEXT = 13
    if not u.OpenClipboard(None):
        return None
    try:
        if not u.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = u.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = k.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr).rstrip("\x00")
        finally:
            k.GlobalUnlock(handle)
    finally:
        u.CloseClipboard()


def _clipboard_set(text):
    if not _IS_WIN:
        return False
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    u.OpenClipboard.restype = ctypes.c_bool
    u.EmptyClipboard.restype = ctypes.c_bool
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    u.SetClipboardData.restype = ctypes.c_void_p
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k.GlobalFree.argtypes = [ctypes.c_void_p]
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    if not u.OpenClipboard(None):
        return False
    try:
        u.EmptyClipboard()
        data = (text + "\x00").encode("utf-16-le")
        handle = k.GlobalAlloc(GMEM_MOVEABLE, len(data) + 2)
        if not handle:
            return False
        ptr = k.GlobalLock(handle)
        ctypes.memmove(ptr, data, len(data))
        k.GlobalUnlock(handle)
        if not u.SetClipboardData(CF_UNICODETEXT, handle):
            k.GlobalFree(handle)
            return False
        return True
    finally:
        u.CloseClipboard()


def clipboard(action, text=""):
    """读写系统剪贴板文本：action ∈ get / set。"""
    action = (action or "").strip().lower()
    if action == "get":
        content = _clipboard_get()
        if content is None:
            return "剪贴板里没有文本内容。"
        if len(content) > 2000:
            content = content[:2000] + "…（内容过长，已截断）"
        return f"剪贴板内容：\n{content}"
    if action == "set":
        text = str(text or "")
        if not text.strip():
            return "博士想让我把什么内容放进剪贴板呢？"
        if len(text) > 10000:
            return "内容太长了，我一次最多复制 10000 个字。"
        if _clipboard_set(text):
            return "已经复制到剪贴板了。"
        return "写入剪贴板失败。"
    return "剪贴板操作只支持 get / set。"


# ── 窗口管理（列出/切换/最小化/最大化/关闭/聚焦/置顶）────────────

_WND_ACTIONS = ("list", "switch", "minimize", "maximize", "close",
                "focus", "topmost_on", "topmost_off")


def _top_windows():
    """返回 [(标题, hwnd)] 的可见顶层窗口列表。"""
    if not _IS_WIN:
        return []
    out = []
    user32 = ctypes.windll.user32
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                              ctypes.c_void_p)

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if title:
            out.append((title, hwnd))
        return True

    user32.EnumWindows(proc(cb), 0)
    return out


def _find_window(name):
    key = (name or "").strip().lower()
    for title, hwnd in _top_windows():
        if key and key in title.lower():
            return title, hwnd
    return None, None


def _activate_window(hwnd):
    """聚焦窗口；前台锁被触发时模拟一次 ALT 让系统放行后重试。"""
    user32 = ctypes.windll.user32
    if user32.SetForegroundWindow(hwnd):
        return True
    _tap(0x12)                           # VK_MENU
    return bool(user32.SetForegroundWindow(hwnd))


def _alt_tab():
    u = ctypes.windll.user32
    u.keybd_event(0x12, 0, 0, 0)         # ALT down
    _tap(0x09)                           # TAB
    u.keybd_event(0x12, 0, 2, 0)         # ALT up


def window_control(action, name=""):
    """管理窗口。action 见 _WND_ACTIONS；name 为窗口标题关键词。"""
    action = (action or "").strip().lower()
    if action not in _WND_ACTIONS:
        return "窗口操作只支持：" + " / ".join(_WND_ACTIONS)
    if not _IS_WIN:
        return "窗口管理仅支持 Windows。"
    user32 = ctypes.windll.user32
    if action == "list":
        wins = _top_windows()[:15]
        if not wins:
            return "当前没有可见窗口。"
        return "当前打开的窗口：\n" + "\n".join(
            "- " + t for t, _ in wins)
    if action == "switch":
        _alt_tab()
        return "已切换窗口。"
    title, hwnd = _find_window(name)
    if not hwnd:
        return f"没找到标题包含「{name}」的窗口，可以先列出窗口看看。"
    if action == "minimize":
        user32.ShowWindow(hwnd, 6)       # SW_MINIMIZE
        return f"已最小化窗口「{title}」。"
    if action == "maximize":
        user32.ShowWindow(hwnd, 3)       # SW_MAXIMIZE
        return f"已最大化窗口「{title}」。"
    if action == "close":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
        return f"已发送关闭请求给「{title}」。"
    if action == "focus":
        if _activate_window(hwnd):
            return f"已切换到「{title}」。"
        return f"切换「{title}」被系统前台锁拦截，请手动点一下。"
    if action in ("topmost_on", "topmost_off"):
        flag = -1 if action == "topmost_on" else -2
        user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0040)   # NOMOVE|NOSIZE|SHOWWINDOW
        return f"已{'置顶' if flag == -1 else '取消置顶'}「{title}」。"
    return "未知操作。"


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
    "system_status": system_status, "type_text": type_text,
    "clipboard": clipboard, "window_control": window_control,
}


def run_action(name, args):
    """Dispatch a tool call. Returns a short result string.

    Never raises: a TypeError from a bad parameter set must not escape — the
    caller (ai._record_tool_round) runs on a worker thread and an uncaught
    exception there surfaces to the user as a bogus "连接出错了" network error.
    """
    fn = _HANDLERS.get(name)
    if not fn:
        return f"我还不会「{name}」这个操作。"
    try:
        return fn(**(args or {}))
    except TypeError:
        # 模型可能漏传/多传参数：先退化为无参调用（部分工具可选参数，
        # 如 open_url / query_schedule），仍失败则给友好提示，不向上抛。
        try:
            return fn()
        except TypeError:
            return f"「{name}」的参数不对，我再确认一下。"
    except Exception as e:
        return f"操作出错了：{type(e).__name__}"


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {},
                       "required": required or []}}}


# OpenAI/DeepSeek tools schema advertised to the model.
TOOLS = [
    _fn("open_app", "打开电脑上的一个程序（内置常用程序；用户可在 apps.json 自定义）",
        {"name": {"type": "string", "description": "程序名，如 记事本/计算器/画图/资源管理器/任务管理器/设置/浏览器/微信/QQ/网易云音乐"}},
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
    _fn("system_status",
        "获取电脑当前状态（只读，安全）：前台窗口、电量、CPU/内存/磁盘占用、开机时长"),
    _fn("type_text",
        "在当前处于焦点的窗口输入文字（模拟键盘，中文英文都可以）。"
        "注意：调用前先确保输入焦点在目标输入框里，例如先请博士点击输入框",
        {"text": {"type": "string", "description": "要输入的文字"},
         "enter": {"type": "boolean",
                   "description": "输入完后是否按回车（发送/确认），默认否"}},
        ["text"]),
    _fn("clipboard", "读取或写入系统剪贴板文本",
        {"action": {"type": "string", "enum": ["get", "set"],
                    "description": "get=读取剪贴板内容, set=把 text 写入剪贴板"},
         "text": {"type": "string", "description": "action=set 时要写入的内容"}},
        ["action"]),
    _fn("window_control", "管理窗口：列出当前窗口、切换窗口、最小化/最大化/关闭/聚焦指定窗口、置顶",
        {"action": {"type": "string",
                    "enum": ["list", "switch", "minimize", "maximize",
                             "close", "focus", "topmost_on", "topmost_off"],
                    "description": "list=列出窗口; switch=Alt+Tab 切换; "
                                   "minimize/maximize/close/focus/topmost_on/"
                                   "topmost_off 需要 name 指定窗口标题关键词"},
         "name": {"type": "string", "description": "窗口标题关键词（list/switch 不需要）"}},
        ["action"]),
]
