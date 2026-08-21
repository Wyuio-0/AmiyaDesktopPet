"""add_character module tests: classification, config, end-to-end add."""
import json
import os

import pytest

from pet.add_character import (
    ACTIONS, add_character, build_config, classify)


@pytest.fixture()
def chars_root(tmp_path):
    return tmp_path / "chars"


def _make_flat_src(tmp_path):
    """平铺素材：文件名带动作关键词。"""
    for fn in ("test-Idle-x1.webm", "test-Click-x1.webm",
               "test-Move-x1.webm", "test-Sit-x1.webm",
               "test-Sleep-x1.webm", "test-Greet-x1.webm",
               "unknown-clip.webm"):
        (tmp_path / fn).write_bytes(b"v")
    return tmp_path


def _make_dir_src(tmp_path):
    """按动作分子目录的素材。"""
    for a in ("idle", "click", "move"):
        d = tmp_path / a
        d.mkdir()
        (d / ("a-%s-x1.webm" % a)).write_bytes(b"v")
    v = tmp_path / "voice"
    v.mkdir()
    (v / "交谈1.wav").write_bytes(b"w")
    return tmp_path


class TestClassify:
    def test_flat_keywords(self, tmp_path):
        src = _make_flat_src(tmp_path)
        plan = classify(str(src))
        assert "idle" in plan and "click" in plan and "move" in plan
        assert "greet" in plan and "sleep" in plan
        # 无法识别的进 idle
        idle_names = [os.path.basename(p) for p in plan["idle"]]
        assert "unknown-clip.webm" in idle_names

    def test_subdir_precedence(self, tmp_path):
        src = _make_dir_src(tmp_path)
        plan = classify(str(src))
        # 子目录精确匹配优先
        assert len(plan["idle"]) == 1
        assert os.path.basename(plan["idle"][0]).startswith("a-idle")
        # 语音目录不参与动作分类
        assert not any("voice" in os.path.basename(p)
                       for files in plan.values() for p in files)


class TestBuildConfig:
    def test_only_existing_actions(self):
        cfg = build_config("k", "名字", {"idle", "click"})
        assert "idle" in cfg["actions"] and "click" in cfg["actions"]
        assert "sleep" not in cfg["actions"]
        assert cfg["interactions"]["on_click"] == "click"

    def test_skill_chain(self):
        cfg = build_config("k", "n", {"idle", "skill_begin", "skill_loop"})
        assert cfg["actions"]["skill_begin"]["next"] == "skill_loop"


class TestAddCharacter:
    def test_add_flat(self, tmp_path, chars_root):
        src = _make_flat_src(tmp_path / "src")
        res = add_character("testchar", "测试角色", str(src),
                            chars_root=str(chars_root))
        assert res["key"] == "testchar"
        assert "idle" in res["actions"]
        cfg_path = os.path.join(str(chars_root), "testchar", "config.json")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["display_name"] == "测试角色"
        assert os.path.isfile(os.path.join(
            str(chars_root), "testchar", "idle", "test-Idle-x1.webm"))

    def test_add_with_voice(self, tmp_path, chars_root):
        src = _make_dir_src(tmp_path / "src")
        res = add_character("vchar", "语音角色", str(src),
                            chars_root=str(chars_root))
        assert res["voice_count"] == 1
        assert os.path.isfile(os.path.join(
            str(chars_root), "vchar", "voice", "交谈1.wav"))

    def test_duplicate_key(self, tmp_path, chars_root):
        src = _make_flat_src(tmp_path / "src")
        add_character("dup", "d", str(src), chars_root=str(chars_root))
        with pytest.raises(ValueError):
            add_character("dup", "d2", str(src), chars_root=str(chars_root))

    def test_empty_src(self, tmp_path, chars_root):
        with pytest.raises(ValueError):
            add_character("empty", "e", str(tmp_path / "nosrc"),
                          chars_root=str(chars_root))
