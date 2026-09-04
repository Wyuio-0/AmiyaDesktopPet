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
    hiddenimports=['cv2', 'PyQt5.QtMultimedia'] + _tts_imports + ['psutil', 'PIL.ImageGrab', 'pet.memory', 'pet.ai_settings', 'pet.theme', 'pet.timers', 'pet.tray', 'pet.menu', 'pet.focus', 'pet.input_controller'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# 角色素材**不**打进 _internal：onedir 发布时角色放在 exe 旁的 characters\，
# 由 build.ps1（本地）或 CI 的 "Sync characters" 步骤同步——全链路只保留
# 一份，安装包/zip 不再重复携带两倍素材。ai_config.json / .claude 由同步
# 步骤一并剔除。

# onedir 打包：DLL 就地加载，规避 onefile 解压后 Qt5Core.dll 加载崩溃
# （0xc0000409）。发布时把整个 dist/DesktopPet/ 目录打成 zip。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DesktopPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DesktopPet',
)
