"""check_secrets rules tests: pure functions (content + filename scan)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from check_secrets import PATTERNS, BANNED, scan_content, scan_names


class TestScanContent:
    def test_detects_api_key(self):
        # 假 key 用拼接避免误触发扫描器自身
        fake = "sk-" + "abcDEFgh1234567890XYZabcdefghij"
        problems = scan_content('api_key = "%s"' % fake)
        assert problems and "API key" in problems[0]

    def test_detects_nonempty_api_key(self):
        problems = scan_content('{"api_key": "' + "mysecretvalue123" + '"}')
        assert any("api_key" in p for p in problems)

    def test_empty_api_key_ok(self):
        assert scan_content('"api_key": "",') == []

    def test_hex_token_detected(self):
        token = "abcdef0123456789" + "abcdef0123456789"   # 32 hex
        assert scan_content("token=" + token)

    def test_plain_text_ok(self):
        assert scan_content("正常代码 print('hello')") == []

    def test_readme_placeholder_ignored(self):
        # README 示例 "api_key": "sk-你的key" 是占位符，不应误报
        assert scan_content('"api_key": "sk-你的key",') == []
        assert scan_content('api_key="sk-xxx"') == []

    def test_real_key_still_detected(self):
        fake = "sk-" + "AbCdef0123456789XYZabcdefghi"   # 无占位特征
        assert scan_content('api_key="%s"' % fake)


class TestScanNames:
    def test_banned_basename(self):
        assert scan_names(["characters/amiya/ai_config.json"])
        assert scan_names(["kebiao.json"])

    def test_benign_names_ok(self):
        assert scan_names(["pet/window.py", "config.json"]) == []


class TestRulesSanity:
    def test_patterns_are_compilable(self):
        import re
        for pat, _ in PATTERNS:
            re.compile(pat)

    def test_banned_are_lowercase(self):
        assert all(b == b.lower() for b in BANNED)
