#!/usr/bin/env python
"""提交前安全检查：扫描暂存区（git diff --cached），发现密钥/个人信息即拒绝提交。

作为 pre-commit 钩子运行（.githooks/pre-commit），也可手动执行：
    python tools/check_secrets.py
扫描两类风险：
  1. 内容：API key（sk-*）、非空 api_key、Bearer token、TTS token 等
  2. 文件名：课表数据、ai_config.json、token 文件、.env 等

发现风险时退出码为 1，阻止提交；没有风险退出 0。
如需增加规则，直接在 PATTERNS / BANNED 里追加即可。
"""

import re
import subprocess
import sys

# 内容模式：(正则, 说明)。命中即拒绝。
PATTERNS = [
    (r"sk-[A-Za-z0-9]{16,}", "OpenAI/Moonshot 风格 API key"),
    (r"api_key\s*[:=]\s*[\"'][^\"']{8,}", "非空 api_key（密钥不应入库）"),
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


def scan():
    problems = []

    # 1) 内容扫描：暂存区的增删改 diff（含新文件全文）
    diff = subprocess.run(["git", "diff", "--cached", "--no-color"],
                          capture_output=True, text=True).stdout
    for pat, desc in PATTERNS:
        for m in re.finditer(pat, diff):
            snip = diff[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")
            problems.append("内容 [%s]: ...%s..." % (desc, snip[:120]))

    # 2) 文件名扫描（basename 精确匹配）
    names = subprocess.run(["git", "diff", "--cached", "--name-only"],
                           capture_output=True, text=True).stdout
    for name in names.splitlines():
        base = name.rsplit("/", 1)[-1].lower()
        for b in BANNED:
            if base == b:
                problems.append("文件名：%s（匹配 %s）" % (name, b))
    return problems


def main():
    problems = scan()
    if not problems:
        return 0
    print("!! 提交被阻止：暂存区包含可能泄露的信息：", file=sys.stderr)
    for p in problems:
        print("   - " + p, file=sys.stderr)
    print("请移除敏感内容后再提交。若确属误报，可在 tools/check_secrets.py 调整规则。",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
