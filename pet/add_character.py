"""添加新角色：把素材文件夹一键转成桌宠角色。

素材文件夹结构（两种都支持）：
  方式 1（推荐）：按动作分子目录
    mychar/
      idle/    *.webm
      click/   *.webm
      move/    *.webm
      ...
      voice/   *.wav（可选，语音）
  方式 2：平铺文件，脚本按文件名关键词自动分类
    mychar/xxx-Idle-x1.webm、xxx-Click-x1.webm、...

会自动：
  - 在 characters/<key>/ 下创建动作子目录并复制视频
  - 复制可选 voice/*.wav
  - 生成 config.json（仅包含实际存在的动作）

纯逻辑、可测试；GUI 入口在桌宠右键菜单「添加新角色…」。
"""

import json
import os
import shutil

# 项目根（pet/ 的上级）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 标准动作集（与 amiya config.json 对齐）
ACTIONS = ["start", "idle", "click", "drag", "greet", "move",
           "sit", "sleep", "skill_begin", "skill_loop"]

# 文件名关键词 -> 动作（子串匹配，子目录名优先精确匹配）
_ACTION_ALIASES = {
    "idle": ("idle", "stand", "待机", "默认"),
    "click": ("click", "interact", "点击", "交互"),
    "drag": ("drag", "拖拽", "拖"),
    "greet": ("greet", "special", "问候", "打招呼"),
    "move": ("move", "移动", "走路", "walk"),
    "sit": ("sit", "坐下"),
    "sleep": ("sleep", "睡觉"),
    "start": ("start", "进入", "出现"),
    "skill_begin": ("skill_begin", "skill", "技能", "begin", "attack", "spell"),
    "skill_loop": ("skill_loop", "loop"),
}

_VIDEO_EXTS = (".webm", ".mp4", ".gif", ".avi", ".mov")


def _match_action(name, subdir=""):
    """子目录名精确匹配优先，其次文件名关键词子串匹配。"""
    if subdir:
        low = subdir.lower().strip()
        if low == "voice":
            return None
        if low in ACTIONS:
            return low
    low = name.lower()
    for action, aliases in _ACTION_ALIASES.items():
        for al in aliases:
            if al in low:
                return action
    return None


def classify(source_dir):
    """扫描素材目录，返回 {action: [文件绝对路径]}。未识别文件进 'idle'。"""
    plan = {}
    for root, dirs, files in os.walk(source_dir):
        sub = os.path.relpath(root, source_dir)
        for fn in sorted(files):
            if not fn.lower().endswith(_VIDEO_EXTS):
                continue
            action = _match_action(fn, sub)
            plan.setdefault(action or "idle", []).append(
                os.path.join(root, fn))
    return plan


def build_config(key, display_name, actions):
    """根据实际存在的动作生成 config.json。"""
    action_cfg = {}
    defaults = {
        "idle": {"interval": 40, "loop": True, "random": True},
        "start": {"interval": 25, "loop": False, "next": "idle"},
        "click": {"interval": 20, "loop": False, "random": True, "next": "idle"},
        "drag": {"interval": 25, "loop": True},
        "greet": {"interval": 25, "loop": False, "random": True, "next": "idle"},
        "move": {"interval": 30, "loop": True},
        "sit": {"interval": 25, "loop": True},
        "sleep": {"interval": 30, "loop": True},
        "skill_begin": {"interval": 20, "loop": False, "next": "skill_loop"
                        if "skill_loop" in actions else "idle"},
        "skill_loop": {"interval": 20, "loop": False, "loop_count": 2,
                       "next": "idle"},
    }
    for a in ACTIONS:
        if a in actions:
            action_cfg[a] = dict(defaults[a])
            action_cfg[a]["folder"] = a

    interactions = {}
    if "click" in actions:
        interactions["on_click"] = "click"
    if "move" in actions or "drag" in actions:
        interactions["on_drag"] = "move" if "move" in actions else "drag"
    if "greet" in actions:
        interactions["on_double_click"] = "greet"

    return {
        "name": key,
        "display_name": display_name or key,
        "description": "%s from Arknights" % display_name or key,
        "scale": 1.0,
        "transparent_color": "#FF00FF",
        "actions": action_cfg,
        "interactions": interactions,
        "rest": {"idle_to_sit": [300, 600], "sit_to_sleep": [3600, 7200]},
        "greetings": {
            "enabled": True,
            "morning": {"start": "06:00", "end": "10:00",
                        "lines": ["早安，博士。"]},
            "noon": {"start": "12:00", "end": "14:00",
                     "lines": ["中午了，博士记得吃饭。"]},
            "late_night": {"start": "23:00", "end": "03:00",
                           "lines": ["已经很晚了，博士早点休息。"]},
        },
        "voice": {
            "enabled": True,
            "volume": 0.7,
            "tts": {"enabled": True, "use_clone": False,
                    "voice": "zh-CN-XiaoyiNeural"},
        },
        "persona": (
            "你是《明日方舟》中的%s。你温柔、坚定、富有责任感，称呼对方为"
            "「博士」，自称「我」。回答简洁自然，一到三句话，只用中文，"
            "不使用括号动作描写或表情符号。" % (display_name or key)),
        "fallback": ["博士，你好。", "有什么我能帮上忙的吗？",
                     "请不要太勉强自己，博士。"],
    }


def add_character(key, display_name, source_dir, chars_root=None):
    """把 source_dir 素材转成 characters/<key> 角色。

    返回结果 dict；角色已存在或素材为空时抛 ValueError。
    """
    key = key.strip()
    if not key:
        raise ValueError("角色 key 不能为空")
    if not os.path.isdir(source_dir):
        raise ValueError("素材目录不存在：%s" % source_dir)

    chars_root = chars_root or os.path.join(ROOT, "characters")
    target = os.path.join(chars_root, key)
    if os.path.exists(target):
        raise ValueError("角色「%s」已存在，请换一个 key。" % key)

    plan = classify(source_dir)
    copied = {}
    for action, files in plan.items():
        if not files:
            continue
        d = os.path.join(target, action)
        os.makedirs(d, exist_ok=True)
        copied[action] = []
        for f in files:
            dst = os.path.join(d, os.path.basename(f))
            shutil.copy2(f, dst)
            copied[action].append(dst)

    if not copied:
        raise ValueError("素材目录里没有找到视频文件（.webm/.mp4 等）。")

    # 语音（可选）
    voice_count = 0
    voice_src = os.path.join(source_dir, "voice")
    if os.path.isdir(voice_src):
        vd = os.path.join(target, "voice")
        os.makedirs(vd, exist_ok=True)
        for fn in sorted(os.listdir(voice_src)):
            if fn.lower().endswith(".wav"):
                shutil.copy2(os.path.join(voice_src, fn),
                             os.path.join(vd, fn))
                voice_count += 1

    config = build_config(key, display_name, copied)
    cfg_path = os.path.join(target, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    return {"key": key, "display_name": config["display_name"],
            "actions": sorted(copied), "voice_count": voice_count,
            "dir": target, "config": cfg_path}
