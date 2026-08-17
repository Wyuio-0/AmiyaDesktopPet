# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules

# edge-tts + its async HTTP stack need their submodules pulled in explicitly.
_tts_imports = (collect_submodules('edge_tts')
                + collect_submodules('aiohttp')
                + ['certifi'])

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('characters', 'characters'), ('app.ico', '.')],
    hiddenimports=['cv2', 'PyQt5.QtMultimedia'] + _tts_imports + ['psutil', 'PIL.ImageGrab', 'pet.memory', 'pet.ai_settings', 'pet.theme', 'pet.timers'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

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
