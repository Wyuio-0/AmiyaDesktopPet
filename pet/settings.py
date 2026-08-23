"""Persisted user preferences (volume, mute, read-aloud toggle).

Kept OUTSIDE the character bundle so they survive app rebuilds and don't get
mixed into the version-controlled character definition (config.json). Path:
  Windows: %APPDATA%\\AmiyaPet\\settings.json
  else:    ~/.config/amiya_pet/settings.json
"""

import json
import os
import sys


def config_dir():
    """User-level config directory (created lazily by writers)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "AmiyaPet")
    base = (os.environ.get("XDG_CONFIG_HOME")
            or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "amiya_pet")


def _settings_path():
    return os.path.join(config_dir(), "settings.json")


def history_path(character_key=None):
    if not character_key:
        return os.path.join(config_dir(), "history.json")
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_"
                   for c in str(character_key))
    return os.path.join(config_dir(), "history_%s.json" % safe)


def characters_dirs():
    """Ordered list of directories that may contain character configs.

    Source runs: the project ``characters/`` folder only.
    Frozen builds: the ``characters/`` folder next to the .exe (so users can
    drop in new characters), then the user-data directory (where the
    "add character" action writes — the bundle itself is read-only), then the
    copy bundled inside the exe as a last resort.
    """
    if getattr(sys, "frozen", False):
        dirs = []
        external = os.path.join(os.path.dirname(sys.executable), "characters")
        if os.path.isdir(external):
            dirs.append(external)
        dirs.append(os.path.join(config_dir(), "characters"))
        try:
            bundled = os.path.join(sys._MEIPASS, "characters")
        except AttributeError:
            bundled = None
        if bundled and os.path.isdir(bundled):
            dirs.append(bundled)
        return dirs
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [os.path.join(root, "characters")]


class Settings:
    """Tiny JSON-backed key/value store; writes are best-effort and atomic."""

    def __init__(self):
        self.path = _settings_path()
        self.data = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        if self.data.get(key) == value:
            return  # no change -> skip the disk write
        self.data[key] = value
        self._save()

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # atomic on same volume
        except Exception:
            pass  # preferences are best-effort; never crash on save failure
