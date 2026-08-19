#!/usr/bin/env python
"""提交前/CI 安全检查：扫描密钥/个人信息，发现即拒绝。

模式：
  默认（pre-commit 钩子）：扫描暂存区 git diff --cached
  --all（CI / 手动）：扫描整个工作区文本文件与文件名

退出码 0 = 干净；1 = 发现风险。
规则见 PATTERNS / BANNED，可在文件内扩展。
"""

import os
import re
import subprocess
import sys

# 内容模式：(正则, 说明)。命中即拒绝。
PATTERNS = [
    (r"sk-[A-Za-z0-9]{16,}", "OpenAI/Moonshot 风格 API key"),
    (r"[\"']?api_key[\"']?\s*[:=]\s*[\"'][^\"']{8,}",
     "非空 api_key（密钥不应入库，兼容 JSON 键带引号）"),
    (r"Bearer\s+[A-Za-z0-9._-]{16,}", "Bearer token"),
    (r"AMIYA_TTS_TOKEN\s*=\s*\S{16,}", "TTS 共享密钥"),
    (r"\b[0-9A-Fa-f]{32,}\b", "疑似令牌/哈希（32+ 位十六进制）"),
]

# 文件名黑名单（与 basename 精确匹配，避免子串误伤）。命中即拒绝。
BANNED = (
    "ai_config.json",      # 本地 AI 密钥配置
    "kebiao.json", "schedule_raw.json", "schedule.json",  # 课表数据（含姓名学号）
    "tts_token",           # 语音克隆共享密钥
    ".env", "secrets.json",  # 环境变量/密钥文件
    "history.json",        # 聊天历史（个人数据）
)

# --all 模式跳过的大目录
_SKIP_DIRS = (".git", "voiceclone", "installer_staging", "dist", "build",
              "__pycache__", ".claude", ".agents", ".pytest_cache", "node_modules")
_BINARY_EXTS = (".webm", ".wav", ".png", ".jpg", ".jpeg", ".ico", ".pyc",
                ".exe", ".7z", ".gz", ".pdf")


def scan_content(diff_text):
    """对文本内容做密钥模式扫描，返回问题列表。纯函数，可单测。"""
    problems = []
    for pat, desc in PATTERNS:
        for m in re.finditer(pat, diff_text):
            snip = diff_text[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")
            problems.append("内容 [%s]: ...%s..." % (desc, snip[:120]))
    return problems


def scan_names(name_list):
    """对文件名列表做黑名单扫描（basename 精确匹配）。纯函数。"""
    problems = []
    for name in name_list:
        base = name.rsplit("/", 1)[-1].lower()
        for b in BANNED:
            if base == b:
                problems.append("文件名：%s（匹配 %s）" % (name, b))
    return problems


def scan_staged():
    """扫描暂存区（git diff --cached）。"""
    diff = subprocess.run(["git", "diff", "--cached", "--no-color"],
                          capture_output=True, text=True).stdout
    names = subprocess.run(["git", "diff", "--cached", "--name-only"],
                           capture_output=True, text=True).stdout.splitlines()
    return scan_content(diff) + scan_names(names)


def scan_tree(root="."):
    """扫描整个工作区的文本文件与文件名。"""
    problems = []
    for dp, dirs, fns in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in fns:
            rel = os.path.join(dp, fn).replace("\\", "/")
            if fn.lower().endswith(_BINARY_EXTS):
                continue
            if fn.lower() in BANNED:
                problems.append("文件名：%s" % rel)
            try:
                with open(os.path.join(dp, fn), "r", encoding="utf-8",
                          errors="ignore") as f:
                    problems += scan_content(f.read())
            except OSError:
                pass
    return problems


def report(problems):
    if not problems:
        return 0
    print("!! 发现可能泄露的信息：", file=sys.stderr)
    for p in problems:
        print("   - " + p, file=sys.stderr)
    print("请移除敏感内容。若确属误报，可在 tools/check_secrets.py 调整规则。",
          file=sys.stderr)
    return 1


def main():
    if "--all" in sys.argv:
        return report(scan_tree())
    return report(scan_staged())


if __name__ == "__main__":
    sys.exit(main())
