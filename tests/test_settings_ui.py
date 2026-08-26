"""settings_ui 热键格式转换测试（纯函数，无需 GUI 事件循环）。"""
from PyQt5 import QtGui

from pet.hotkey import parse_hotkey
from pet.settings_ui import _ks_to_spec, _spec_to_ks


def _parts(spec):
    return set(p.strip().lower() for p in str(spec).split("+"))


def test_spec_ks_roundtrip():
    for spec in ("alt+a", "ctrl+shift+f", "alt+t", "ctrl+alt+s",
                 "alt+q", "win+shift+1"):
        back = _ks_to_spec(_spec_to_ks(spec))
        assert _parts(back) == _parts(spec), (spec, back)


def test_specs_valid_for_global_hotkey():
    for spec in ("alt+a", "ctrl+shift+f", "alt+t", "ctrl+alt+s"):
        ks = _spec_to_ks(spec)
        assert parse_hotkey(_ks_to_spec(ks)) is not None, spec


def test_empty_spec():
    assert _spec_to_ks("") == QtGui.QKeySequence()
    assert _ks_to_spec(QtGui.QKeySequence()) == ""
