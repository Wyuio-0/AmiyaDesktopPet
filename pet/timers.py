"""Floating countdown badge and dialogs for reminder / countdown / pomodoro."""

from PyQt5 import QtCore, QtWidgets

from . import theme

_BADGE_QSS = (
    "QLabel{background:%s;color:%s;"
    "border:1px solid %s;border-left:4px solid %s;border-radius:6px;"
    "padding:11px 21px;font-family:%s;font-size:22px;font-weight:700;}"
) % (theme.FLOAT_PANEL, theme.FLOAT_TEXT, theme.FLOAT_GRID,
     theme.FLOAT_GOLD, theme.MONO)


class CountdownBadge(QtWidgets.QLabel):
    """A tiny always-on-top badge that floats by the pet's shoulder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setStyleSheet(_BADGE_QSS)

    def show_text(self, text, near):
        self.setText(text)
        self.adjustSize()
        self.reposition(near)
        if not self.isVisible():
            self.show()

    def reposition(self, near):
        """Float at the pet's top-right so it won't cover the speech bubble."""
        x = near.right() - self.width() // 2
        y = near.top() - self.height() // 2
        self.move(max(0, x), max(0, y))


def _spin(parent, lo, hi, val, suffix):
    s = QtWidgets.QSpinBox(parent)
    s.setRange(lo, hi)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


class DurationDialog(QtWidgets.QDialog):
    """Ask for a message + a minutes/seconds duration.

    Reused for both one-off reminders and visible countdowns. Emits
    `confirmed(total_seconds, message)`.
    """

    confirmed = QtCore.pyqtSignal(int, str)

    def __init__(self, title, subtitle, default_msg, default_min,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(630)
        self.setStyleSheet(theme.DIALOG_QSS)
        self._build(title, subtitle, default_msg, default_min)

    def _build(self, title, subtitle, default_msg, default_min):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QtWidgets.QLabel("RHODES ISLAND", self)
        head.setObjectName("TerminalTitle")
        root.addWidget(head)
        sub = QtWidgets.QLabel(subtitle, self)
        sub.setObjectName("TerminalSubTitle")
        root.addWidget(sub)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        root.addLayout(form)

        self.msg = QtWidgets.QLineEdit(self)
        self.msg.setText(default_msg)
        form.addRow("提醒内容", self.msg)

        row = QtWidgets.QHBoxLayout()
        self.minutes = _spin(self, 0, 1440, default_min, " 分")
        self.seconds = _spin(self, 0, 59, 0, " 秒")
        row.addWidget(self.minutes)
        row.addWidget(self.seconds)
        form.addRow("时长", row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("开始")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _ok(self):
        total = self.minutes.value() * 60 + self.seconds.value()
        if total <= 0:
            QtWidgets.QMessageBox.warning(self, "时长", "请设置一个大于 0 的时长。")
            return
        self.confirmed.emit(total, self.msg.text().strip() or "时间到了")
        self.accept()


class PomodoroDialog(QtWidgets.QDialog):
    """Configure a pomodoro session. Emits `confirmed(work, brk, rounds)`
    with work/break in minutes."""

    confirmed = QtCore.pyqtSignal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("番茄钟")
        self.setModal(True)
        self.setMinimumWidth(630)
        self.setStyleSheet(theme.DIALOG_QSS)
        self._build()

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QtWidgets.QLabel("RHODES ISLAND", self)
        head.setObjectName("TerminalTitle")
        root.addWidget(head)
        sub = QtWidgets.QLabel("POMODORO FOCUS SESSION", self)
        sub.setObjectName("TerminalSubTitle")
        root.addWidget(sub)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        root.addLayout(form)

        self.work = _spin(self, 1, 180, 25, " 分")
        self.brk = _spin(self, 1, 60, 5, " 分")
        self.rounds = _spin(self, 1, 12, 4, " 轮")
        form.addRow("专注时长", self.work)
        form.addRow("休息时长", self.brk)
        form.addRow("循环轮数", self.rounds)

        note = QtWidgets.QLabel(
            "阿米娅会陪博士专注，每一轮结束提醒休息，循环结束后收工。", self)
        note.setObjectName("TerminalNote")
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("开始专注")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _ok(self):
        self.confirmed.emit(
            self.work.value(), self.brk.value(), self.rounds.value())
        self.accept()


