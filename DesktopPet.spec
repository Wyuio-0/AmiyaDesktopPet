# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.datastruct import Tree

# edge-tts + its async HTTP stack need their submodules pulled in explicitly.
_tts_imports = (collect_submodules('edge_tts')
                + collect_submodules('aiohttp')
                + ['certifi'])

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app.ico', '.')],
    hiddenimports=['cv2', 'PyQt5.QtMultimedia'] + _tts_imports + ['psutil', 'PIL.ImageGrab', 'pet.memory', 'pet.ai_settings', 'pet.theme', 'pet.timers'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 角色资源随包发布，但**排除敏感/本地文件**：ai_config.json 可能含有 API key，
# .claude 等本地工具状态也不该进发布物（exe 可被反解提取内部文件，打进去=公开）。
# Tree 是 (src, dst) 二元组的迭代器，不能直接作为 Analysis(datas=...) 的元素，
# 必须在 Analysis 构造后追加（PyInstaller 官方用法）。
a.datas += Tree('characters', prefix='characters',
                excludes=['ai_config.json', '.claude'])

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DesktopPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
