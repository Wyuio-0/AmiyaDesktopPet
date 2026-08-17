"""Chat UI: input box + speech bubble, with a background reply worker."""

from PyQt5 import QtCore, QtWidgets

from . import theme

_BUBBLE_QSS = (
    "QLabel{background:%s;color:%s;"
    "border:1px solid %s;border-left:4px solid %s;border-radius:6px;"
    "padding:15px 24px;"
    "font-family:%s;font-size:21px;font-weight:600;}"
) % (theme.FLOAT_PANEL, theme.FLOAT_TEXT, theme.FLOAT_GRID,
     theme.FLOAT_ACCENT_SOFT, theme.FONT)

_INPUT_QSS = (
    "QLineEdit{background:%s;color:%s;"
    "border:1px solid %s;border-bottom:2px solid %s;border-radius:6px;"
    "padding:12px 18px;font-family:%s;font-size:21px;}"
    "QLineEdit:focus{border:1px solid %s;border-bottom:2px solid %s;"
    "background:%s;}"
    "QLineEdit::placeholder{color:%s;}"
) % (theme.FLOAT_PANEL, theme.FLOAT_TEXT, theme.FLOAT_GRID,
     theme.FLOAT_ACCENT_SOFT, theme.FONT,
     theme.FLOAT_ACCENT, theme.FLOAT_ACCENT, theme.FLOAT_FIELD,
     theme.FLOAT_TEXT_DIM)


class ReplyWorker(QtCore.QThread):
    """Runs brain.reply_stream() off the UI thread.

    `delta` fires with the accumulated text as tokens arrive (live typing);
    `done` fires once with the final text when generation completes.
    """

    delta = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(str)

    def __init__(self, brain, text, parent=None):
        super().__init__(parent)
        self.brain = brain
        self.text = text

    def run(self):
        if self.isInterruptionRequested():
            return
        # emit() is thread-safe (queued to the UI thread) for cross-thread use.
        text = self.brain.reply_stream(self.text, self.delta.emit)
        self.done.emit(text)


class SpeechBubble(QtWidgets.QLabel):
    """A rounded translucent bubble shown above the pet."""

    # Safety timeout: if streaming never completes (network hang, etc.), the
    # bubble auto-hides after this many ms so it doesn't stick forever.
    STREAM_SAFETY_MS = 20000

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
        self.setMaximumWidth(480)
        self.setContentsMargins(12, 8, 12, 8)
        self.setStyleSheet(_BUBBLE_QSS)
        self._hide = QtCore.QTimer(self, singleShot=True)
        self._hide.timeout.connect(self.hide)
        self._safety = QtCore.QTimer(self, singleShot=True)
        self._safety.timeout.connect(self.hide)

    def say(self, text, near, auto_ms=6000):
        """One-shot bubble that snugly fits `text` (used for short messages)."""
        self._hide.stop()
        self._safety.stop()
        self.setMinimumWidth(0)          # let it shrink to fit
        self.setText(text)
        self.adjustSize()
        self.reposition(near)
        self.show()
        if auto_ms:
            self._hide.start(auto_ms)

    def start_stream(self, near, text=""):
        """Begin a streaming reply: pin the width so the box can only grow
        downward-anchored (vertically), never jitter left/right as text lands.

        A 20-second safety timer ensures the bubble doesn't stick forever if
        the network hangs or the AI never responds.
        """
        self._hide.stop()
        self._safety.stop()
        # Pin to the max width for the whole reply -> stable left/right edges.
        self.setMinimumWidth(self.maximumWidth())
        self.setText(text)
        self.adjustSize()
        self.reposition(near)
        self.show()
        self._safety.start(self.STREAM_SAFETY_MS)

    def update_stream(self, text, near):
        """Grow the streaming bubble with more text, keeping edges stable.

        Each update resets the safety timer — as long as data keeps arriving
        the bubble stays alive.
        """
        self.setText(text)
        self.adjustSize()          # width is pinned; only height changes
        self.reposition(near)
        self._safety.start(self.STREAM_SAFETY_MS)

    def end_stream(self, near, auto_ms=6000):
        """Finish streaming: keep the pinned width, arm the auto-hide.

        Cancels the safety timer and switches to a reading-time-based hide
        so the user has time to read the full reply.
        """
        self._safety.stop()
        self.reposition(near)
        if auto_ms:
            self._hide.start(auto_ms)

    def reposition(self, near):
        """Anchor bottom-centered above `near` (a QRect in global coords).

        The bottom edge sits a fixed gap above `near.top()`, so as height grows
        the box extends *upward* from a stable baseline instead of shifting.
        """
        x = near.center().x() - self.width() // 2
        y = near.top() - self.height() - 6
        self.move(max(0, x), max(0, y))

    def mousePressEvent(self, e):
        """Click the bubble to dismiss it early (e.g. done reading a long one)."""
        self._hide.stop()
        self._safety.stop()
        self.hide()


class InputBar(QtWidgets.QLineEdit):
    """A small floating text field for talking to the pet.

    Auto-hides after 20 seconds of inactivity so it doesn't linger on screen
    when the user changes their mind.
    """

    IDLE_TIMEOUT_MS = 20000
    submitted = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setPlaceholderText("和阿米娅说点什么…（回车发送，Esc 关闭）")
        self.setFixedSize(480, 63)
        self.setStyleSheet(_INPUT_QSS)
        self.returnPressed.connect(self._submit)
        self._idle = QtCore.QTimer(self, singleShot=True)
        self._idle.timeout.connect(self.hide)
        self.textChanged.connect(self._reset_idle)

    def _submit(self):
        text = self.text().strip()
        if text:
            self.submitted.emit(text)
        self.clear()
        self.hide()

    def _reset_idle(self):
        """Reset the auto-hide countdown whenever the text changes.

        Connected to textChanged so the timer resets reliably for ALL forms of
        input — keyboard, IME composition (Chinese pinyin, etc.), paste — not
        just raw key presses.  Without this, an active IME session can consume
        key events before keyPressEvent fires and the input box closes
        mid-typing.
        """
        if self.isVisible():
            self._idle.start(self.IDLE_TIMEOUT_MS)

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.hide()
        else:
            self._idle.start(self.IDLE_TIMEOUT_MS)  # reset idle timer on any input
            super().keyPressEvent(e)

    def inputMethodEvent(self, e):
        """Reset the idle timer during IME composition (e.g. Chinese pinyin)."""
        self._idle.start(self.IDLE_TIMEOUT_MS)
        super().inputMethodEvent(e)

    def pop_up(self, near):
        self.reposition(near)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._idle.start(self.IDLE_TIMEOUT_MS)

    def hide(self):
        self._idle.stop()
        super().hide()

    def reposition(self, near):
        """Re-place centered directly above `near` (global coords)."""
        x = near.center().x() - self.width() // 2
        y = near.top() - self.height() - 6
        self.move(max(0, x), max(0, y))
