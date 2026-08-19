"""Frames (chroma-key) tests: synthetic images exercise the alpha logic.

无 GUI/无视频依赖：直接构造 BGR numpy 图像验证 key_frame 的透明判定：
  - 边界连通黑色 -> 透明
  - 亮色角色 -> 不透明
  - 带色相的深色（角色内部）-> 保留不透明
  - 被亮色包围的纯黑洞（背景缝）-> 被填充为透明
"""
import numpy as np
import pytest

from pet.frames import key_frame


def _bgr(shape, color):
    return np.full(shape + (3,), color, dtype=np.uint8)


def test_background_cleared_character_kept():
    # 100x100：上半(黑背景) + 下半亮色(角色)
    img = np.zeros((100, 100, 3), np.uint8)
    img[50:, :] = (200, 200, 200)      # BGR 亮灰
    out = key_frame(img, 1.0)
    alpha = out[:, :, 3]
    assert (alpha[:50, :] == 0).all()      # 背景透明
    assert (alpha[55:, :] == 255).all()    # 角色不透明


def test_dark_coloured_artwork_kept():
    # 深色但带色相（紫蓝），应保留不透明
    img = np.zeros((100, 100, 3), np.uint8)
    img[50:] = (200, 200, 200)
    img[70:90, 40:60] = (30, 20, 90)       # 深紫蓝（chroma > 12）
    out = key_frame(img, 1.0)
    assert (out[72:88, 44:56, 3] == 255).all()


def test_enclosed_black_pocket_filled():
    # 黑色背景 + 亮色"回"字环：环内纯黑洞是背景缝，应被填充透明
    img = np.zeros((100, 100, 3), np.uint8)
    img[30:70, 30:70] = (180, 180, 180)    # 亮色方块
    img[34:66, 34:66] = (0, 0, 0)          # 内部纯黑（洞）
    out = key_frame(img, 1.0)
    alpha = out[:, :, 3]
    assert (alpha[40:60, 40:60] == 0).all()     # 洞 -> 透明
    assert (alpha[31:33, 31:33] == 255).all()   # 环壁 -> 不透明


def test_tiny_dark_specks_kept():
    # 小于面积下限的暗点（如眼睛）不被洞填充误删。
    # 注意：100x100 测试图上 min_hole = max(12, 10000*4e-5) = 12，
    # 所以暗点面积须 < 12（真实 1000x1000 帧上为 40）。
    img = np.zeros((100, 100, 3), np.uint8)
    img[50:] = (200, 200, 200)
    img[61:64, 49:52] = (0, 0, 0)          # 3x3 小暗点（面积 9 < 12）
    out = key_frame(img, 1.0)
    assert out[62, 50, 3] == 255           # 暗点中心保留不透明


def test_scale_resize():
    img = np.zeros((100, 100, 3), np.uint8)
    img[50:] = (200, 200, 200)
    out = key_frame(img, 0.5)
    assert out.shape[:2] == (50, 50)
