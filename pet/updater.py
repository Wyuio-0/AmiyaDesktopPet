"""自动更新检查：启动时静默查询 GitHub Releases，发现新版本提示下载。

版本号 APP_VERSION 需与发布 tag 保持一致（发版时一起改）。
查询失败（离线 / 限流 / 网络错误）一律静默忽略，绝不影响正常启动。
"""

import json
import re
import urllib.request

# 与仓库发布 tag 保持一致（如发 v1.4.0 时这里就是 "1.4.0"）。
APP_VERSION = "1.4.0"

REPO = "Wyuio-0/AmiyaDesktopPet"
_LATEST_API = "https://api.github.com/repos/%s/releases/latest" % REPO


def latest_release(timeout=5):
    """查询最新 Release。返回 (tag_name, html_url, installer_url) 或 None。

    installer_url 取第一个 .exe 资产（安装包），没有则为空串。
    """
    try:
        req = urllib.request.Request(
            _LATEST_API,
            headers={"User-Agent": "AmiyaDesktopPet",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        tag = str(data.get("tag_name", "")).strip()
        html = str(data.get("html_url", "")).strip()
        installer = ""
        for a in data.get("assets", []) or []:
            name = str(a.get("name", ""))
            if name.lower().endswith(".exe"):
                installer = str(a.get("browser_download_url", "")).strip()
                break
        return (tag, html, installer) if tag else None
    except Exception:
        return None


def is_newer(tag, current=APP_VERSION):
    """'v1.4.0' / '1.4.0' 语义比较：tag 是否比 current 新。"""
    def norm(v):
        nums = re.findall(r"\d+", str(v))
        return [int(x) for x in nums[:3]] + [0] * (3 - len(nums[:3]))
    return norm(tag) > norm(current)
