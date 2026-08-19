"""待办/考试 对话框：自然语言截止时间 + 任务列表管理。

TaskDialog    添加作业/考试（标题、课程、截止时间支持"明天/周五/9月20日 14:00"）
TaskListDialog 管理已有任务（标记完成 / 删除）
"""

from datetime import datetime

from PyQt5 import QtCore, QtWidgets

from . import theme
from .tasks import parse_datetime

_REMIND_CHOICES = [
    ("不提醒", 0),
    ("提前 1 小时", 60),
    ("提前 1 天", 60 * 24),
    ("提前 2 天", 60 * 48),
    ("提前 1 周", 60 * 24 * 7),
]


class TaskDialog(QtWidgets.QDialog):
    """添加一个作业/考试。confirmed(title, kind, due, remind_min)。"""

    confirmed = QtCore.pyqtSignal(str, str, object, int)

    def __init__(self, kind, default_course="", courses=None, parent=None):
        super().__init__(parent)
        self.kind = kind  # 'homework' | 'exam'
        self.setWindowTitle("添加考试" if kind == "exam" else "添加作业 DDL")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(theme.DIALOG_QSS)
        self._build(default_course, courses or [])

    def _build(self, default_course, courses):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QtWidgets.QLabel("RHODES ISLAND", self)
        head.setObjectName("TerminalTitle")
        root.addWidget(head)
        sub = QtWidgets.QLabel(
            "记录作业截止或考试时间，阿米娅会提前提醒博士。", self)
        sub.setObjectName("TerminalSubTitle")
        root.addWidget(sub)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        root.addLayout(form)

        self.title = QtWidgets.QLineEdit(self)
        self.title.setPlaceholderText(
            "例如：高数第三章作业" if self.kind == "homework" else "例如：高数期末考试")
        form.addRow("事项", self.title)

        self.course = QtWidgets.QComboBox(self)
        self.course.setEditable(True)
        self.course.addItem("")
        self.course.addItems(sorted(courses))
        if default_course and default_course in courses:
            self.course.setCurrentText(default_course)
        form.addRow("课程（可选）", self.course)

        self.due = QtWidgets.QLineEdit(self)
        self.due.setPlaceholderText("例如：周五 23:59 / 9月20日 / 明天")
        form.addRow("截止时间", self.due)
        self.preview = QtWidgets.QLabel("", self)
        self.preview.setObjectName("TerminalNote")
        form.addRow("", self.preview)
        self.due.textChanged.connect(self._preview)

        self.remind = QtWidgets.QComboBox(self)
        default_idx = 2 if self.kind == "homework" else 4  # 作业提前1天 / 考试提前1周
        for i, (label, _) in enumerate(_REMIND_CHOICES):
            self.remind.addItem(label)
        self.remind.setCurrentIndex(default_idx)
        form.addRow("提醒", self.remind)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("添加")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _preview(self):
        text = self.due.text().strip()
        if not text:
            self.preview.setText("")
            return
        dt, ok = parse_datetime(text)
        self.preview.setText(
            ("将设为 %s" % dt.strftime("%Y-%m-%d %H:%M")) if ok
            else "无法识别日期，试试：明天 / 周五 / 9月20日 14:00")
        self.preview.setStyleSheet(
            "color:%s;" % (theme.FLOAT_TEXT if ok else theme.FLOAT_TEXT_DIM))

    def _ok(self):
        title = self.title.text().strip()
        due_text = self.due.text().strip()
        dt, ok = parse_datetime(due_text)
        if not title:
            QtWidgets.QMessageBox.warning(self, "事项", "请填写事项内容。")
            return
        if not ok:
            QtWidgets.QMessageBox.warning(
                self, "截止时间",
                "无法识别截止时间，试试：明天 / 周五 / 9月20日 14:00")
            return
        remind_min = _REMIND_CHOICES[self.remind.currentIndex()][1]
        self.confirmed.emit(title, self.course.currentText().strip(),
                            dt, remind_min)
        self.accept()


class TaskListDialog(QtWidgets.QDialog):
    """列出未完成任务：标记完成 / 删除。操作直接写入 tasks。"""

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.setWindowTitle("待办与考试")
        self.setModal(True)
        self.setMinimumWidth(680)
        self.setMinimumHeight(380)
        self.setStyleSheet(theme.DIALOG_QSS)
        self._build()

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QtWidgets.QLabel("RHODES ISLAND", self)
        head.setObjectName("TerminalTitle")
        root.addWidget(head)
        sub = QtWidgets.QLabel("双击任务标记完成，选中后可用下方按钮操作。", self)
        sub.setObjectName("TerminalSubTitle")
        root.addWidget(sub)

        self.list = QtWidgets.QListWidget(self)
        self.list.itemDoubleClicked.connect(self._toggle_done)
        root.addWidget(self.list, 1)

        btns = QtWidgets.QHBoxLayout()
        done = QtWidgets.QPushButton("标记完成", self)
        done.clicked.connect(self._toggle_done)
        delete = QtWidgets.QPushButton("删除", self)
        delete.clicked.connect(self._remove)
        close = QtWidgets.QPushButton("关闭", self)
        close.clicked.connect(self.accept)
        for b in (done, delete, close):
            btns.addWidget(b)
        root.addLayout(btns)

        self._reload()

    def _reload(self):
        self.list.clear()
        now = datetime.now()
        items = sorted(self.tasks.items, key=lambda t: (t.done, t.due))
        for t in items:
            tag = "考试" if t.kind == "exam" else "作业"
            left = t.due - now
            if t.done:
                when = "已完成"
            elif left.days >= 1:
                when = "剩%d天" % left.days
            elif left.total_seconds() >= 0:
                when = "剩%d小时" % (left.seconds // 3600)
            else:
                when = "已过期"
            course = "·%s" % t.course if t.course else ""
            it = QtWidgets.QListWidgetItem(
                "%s %s%s  %s（%s）" % (
                    tag, t.title, course,
                    t.due.strftime("%m-%d %H:%M"), when))
            if t.done:
                it.setForeground(QtCore.Qt.gray)
            it.setData(QtCore.Qt.UserRole, t.id)
            self.list.addItem(it)

    def _current_id(self):
        it = self.list.currentItem()
        return it.data(QtCore.Qt.UserRole) if it else None

    def _toggle_done(self, *_):
        tid = self._current_id()
        if not tid:
            return
        for t in self.tasks.items:
            if t.id == tid:
                self.tasks.set_done(tid, not t.done)
                break
        self._reload()

    def _remove(self):
        tid = self._current_id()
        if not tid:
            return
        self.tasks.remove(tid)
        self._reload()
