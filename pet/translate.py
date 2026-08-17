"""Quick translation: clipboard → translate → floating popup.

Two backends, tried in order:
  1. AI — uses the configured LLM (DeepSeek / OpenAI) for high-quality translation.
  2. Google Translate — free fallback when offline or no API key configured.

The TranslationPopup shows source + translated text above the pet, auto-hides
after a reading-time delay proportional to content length, and dismisses on click.

Usage:
    from .translate import TranslationPopup, TranslateWorker, translate_text
"""

import json
import urllib.parse
import urllib.request

from PyQt5 import QtCore, QtWidgets

from . import theme

# ── Popup styling ──────────────────────────────────────────────────────

_POPUP_QSS = (
    "QLabel{background:%s;color:%s;"
    "border:1px solid %s;border-left:4px solid %s;border-radius:6px;"
    "padding:14px 22px;font-family:%s;}"
) % (theme.FLOAT_PANEL, theme.FLOAT_TEXT, theme.FLOAT_GRID,
     theme.FLOAT_GOLD, theme.FONT)

# Reading time scales with content length so longer translations stay visible
# long enough to read, while short ones don't linger.
READ_MS_PER_CHAR = 100
READ_MS_MIN = 4000
READ_MS_MAX = 25000


def _escape(text):
    """Escape HTML entities for safe QLabel rich-text rendering."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TranslationPopup(QtWidgets.QLabel):
    """A floating always-on-top popup showing source + translated text.

    Anchored above the pet's body; click anywhere to dismiss early, or let the
    auto-hide timer fire after a reading-time delay.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setWordWrap(True)
        self.setMaximumWidth(560)
        self.setContentsMargins(12, 8, 12, 8)
        self.setStyleSheet(_POPUP_QSS)
        self._hide = QtCore.QTimer(self, singleShot=True)
        self._hide.timeout.connect(self.hide)

    def show_translation(self, source, translated, near, auto_ms=None):
        """Display source + translated text, auto-hide after *auto_ms*.

        If *auto_ms* is None it is computed from the translation length so
        longer texts stay visible proportionally longer.
        """
        self._hide.stop()
        text = (
            '<div style="font-size:21px;color:%s;margin-bottom:5px;'
            'line-height:1.4;">%s</div>'
            '<div style="font-size:21px;color:%s;font-weight:600;'
            'line-height:1.5;">%s</div>'
        ) % (theme.FLOAT_TEXT_DIM, _escape(source), theme.FLOAT_TEXT,
             _escape(translated))
        self.setText(text)
        self.setMinimumWidth(0)          # allow shrinking to fit short text
        self.adjustSize()
        # adjustSize() is unreliable with rich-text QLabel + word wrap:
        # for long content the height often lags behind the actual line count.
        # heightForWidth() returns the true pixel height needed at a given
        # width, so we use it to correct the label height.
        needed = self.heightForWidth(self.width())
        if needed > 0 and needed > self.height():
            self.resize(self.width(), needed)
        self.reposition(near)
        self.show()
        if auto_ms is None:
            auto_ms = max(READ_MS_MIN,
                          min(READ_MS_MAX,
                              len(translated) * READ_MS_PER_CHAR))
        if auto_ms:
            self._hide.start(auto_ms)

    def reposition(self, near):
        """Anchor bottom-centered above *near* (QRect in global coords)."""
        x = near.center().x() - self.width() // 2
        y = near.top() - self.height() - 6
        self.move(max(0, x), max(0, y))

    def mousePressEvent(self, e):
        """Click anywhere on the popup to dismiss it early."""
        self._hide.stop()
        self.hide()


# ── Translation backends ────────────────────────────────────────────────

def _translate_via_ai(brain, text, target="中文"):
    """Use the configured LLM for translation.  Returns translated text or None.

    Makes a **stateless** call — the translation prompt never enters the
    conversation history, so translating won't pollute Amiya's memory.
    """
    if not brain.online:
        return None
    try:
        cfg = brain.cfg
        msgs = [
            {"role": "system",
             "content": (
                 f"你是一个专业的翻译助手。把用户输入翻译成{target}，"
                 "只输出翻译结果，不要添加任何解释、注释或额外文字。"
                 "保持原文的格式和换行。"
             )},
            {"role": "user", "content": text},
        ]
        payload = {
            "model": cfg["model"],
            "messages": msgs,
            "temperature": 0.3,          # low temp → consistent translations
            "stream": False,
        }
        body = json.dumps(payload).encode("utf-8")
        url = cfg["base_url"].rstrip("/") + "/v1/chat/completions"
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cfg["api_key"],
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result = data["choices"][0]["message"].get("content", "").strip()
        return result or None
    except Exception:
        return None


def _translate_via_google(text, target="zh-CN"):
    """Free Google Translate fallback (no API key needed).

    Uses the same endpoint as the Google Translate web widget.  Auto-detects
    the source language and translates to *target*.
    """
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = urllib.parse.urlencode({
            "client": "gtx",
            "sl": "auto",
            "tl": target,
            "dt": "t",
            "q": text,
        })
        req = urllib.request.Request(url + "?" + params, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # The response is [[["sentence1",...],...,"src_lang"],...]; collect all
        # translated fragments.
        parts = []
        for block in data[0]:
            if block[0]:
                parts.append(block[0])
        result = "".join(parts).strip()
        return result or None
    except Exception:
        return None


# Human-readable language name → Google Translate language code.
_LANG_MAP = {
    "中文": "zh-CN", "英文": "en", "日文": "ja", "韩文": "ko",
    "法文": "fr", "德文": "de", "俄文": "ru", "西班牙文": "es",
    "葡萄牙文": "pt", "意大利文": "it",
}


def translate_text(brain, text, target="中文"):
    """Translate *text* to *target* language.

    Tries the AI backend first (high quality, uses the configured LLM), then
    falls back to Google Translate.  Returns the translated string, or an
    error message on total failure.

    *brain* is an AmiyaBrain instance (only its ``.online`` and ``.cfg``
    properties are read — the conversation history is never touched).
    """
    if not text or not text.strip():
        return "没有可翻译的文字。"

    text = text.strip()

    # 1) AI backend — stateless, high quality, uses configured API key
    result = _translate_via_ai(brain, text, target)
    if result:
        return result

    # 2) Google Translate — free, no key required
    gt_target = _LANG_MAP.get(target, "zh-CN")
    result = _translate_via_google(text, gt_target)
    if result:
        return result

    return "翻译失败，请检查网络连接。"


# ── Background worker ───────────────────────────────────────────────────

class TranslateWorker(QtCore.QThread):
    """Runs :func:`translate_text` off the UI thread so the pet never freezes.

    Emits ``done(source_text, translated_text_or_error)`` when finished.
    """

    done = QtCore.pyqtSignal(str, str)

    def __init__(self, brain, text, target="中文", parent=None):
        super().__init__(parent)
        self.brain = brain
        self.text = text
        self.target = target

    def run(self):
        if self.isInterruptionRequested():
            return
        result = translate_text(self.brain, self.text, self.target)
        self.done.emit(self.text, result)
