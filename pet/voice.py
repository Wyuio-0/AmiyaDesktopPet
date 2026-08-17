"""Voice playback for the pet: play a character's Arknights voice lines.

The clips under `<char>/voice/*.wav` or `<char>/*.wav` are fixed in-game voice
lines (not a
text-to-speech voice), so we can't narrate an arbitrary AI answer word for
word. Instead we map interaction events to fitting groups of lines and play a
random one, which reads as the character "speaking" when she reacts or replies.

Volume is adjustable at runtime (0.0-1.0); 0 mutes. One clip plays at a time.
"""

import glob
import os
import random

from PyQt5 import QtCore, QtMultimedia

# Event -> substrings matched against a voice file's base name. First group
# with any match wins; order matters (most specific first).
_GROUPS = {
    "reply":  ["交谈", "信赖提升后交谈", "晋升后交谈"],
    "greet":  ["问候", "干员报到", "任命助理", "任命队长", "标题"],
    "click":  ["戳一下", "信赖触摸", "选中干员", "编入队伍"],
    "idle":   ["闲置"],
    "skill":  ["部署", "行动开始", "行动出发", "作战中", "观看作战记录"],
    "sit":    ["进驻设施"],
}


class VoicePlayer:
    """Plays random voice clips per event, with adjustable volume."""

    def __init__(self, char_dir, volume=0.7, enabled=True):
        self.enabled = enabled
        self._volume = max(0.0, min(float(volume), 1.0))
        self._player = QtMultimedia.QMediaPlayer()
        self._apply_volume()
        self._groups = self._scan(char_dir)

    def _scan(self, char_dir):
        """Return {event: [file, ...]} plus an 'all' bucket of every clip."""
        patterns = [
            os.path.join(char_dir, "voice", "*.wav"),
            os.path.join(char_dir, "*.wav"),
        ]
        files = sorted({path for pattern in patterns for path in glob.glob(pattern)})
        groups = {k: [] for k in _GROUPS}
        for path in files:
            base = os.path.splitext(os.path.basename(path))[0]
            for event, keys in _GROUPS.items():
                if any(k in base for k in keys):
                    groups[event].append(path)
                    break
        groups["all"] = files
        return groups

    def _apply_volume(self):
        # QMediaPlayer volume is an int 0-100.
        self._player.setVolume(int(round(self._volume * 100)))

    @property
    def volume(self):
        return self._volume

    def set_volume(self, value):
        self._volume = max(0.0, min(float(value), 1.0))
        self._apply_volume()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.stop()

    def stop(self):
        self._player.stop()

    def play(self, event):
        """Play a random clip for `event` (falls back to any clip)."""
        if not self.enabled or self._volume <= 0:
            return
        clips = self._groups.get(event) or []
        if not clips:
            return
        self.play_file(random.choice(clips))

    def play_file(self, path):
        """Play a specific audio file (e.g. TTS output) at current volume."""
        if not self.enabled or self._volume <= 0 or not path:
            return
        self._player.stop()
        self._player.setMedia(
            QtMultimedia.QMediaContent(QtCore.QUrl.fromLocalFile(path)))
        self._apply_volume()
        self._player.play()

    def has(self, event):
        return bool(self._groups.get(event))
