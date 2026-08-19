"""信息面板：课程表 / 待办与考试 / OCR 结果 的集中展示窗口。

把原来挤在气泡/浮窗里的长文本改为独立、可缩放、可滚动的置顶面板，
信息分层清晰，待办可直接在行内完成/删除。

入口：PetWindow 右键菜单（课程表/待办与考试/OCR 的查看类动作都指向本面板）。
"""

from datetime import datetime

from PyQt5 import QtCore, QtGui, QtWidgets

from . import theme

PAGE_SCHEDULE = "schedule"
PAGE_TASKS = "tasks"
PAGE_OCR = "ocr"

_QSS = """
QWidget#PanelRoot { background:%s; color:%s; }
QWidget#TitleBar { background:%s; }
QLabel#TitleText { color:%s; font-size:20px; font-weight:700; }
QLabel#TitleSub { color:%s; font-size:13px; }
QPushButton#CloseBtn { color:%s; border:none; font-size:22px; }
QPushButton#CloseBtn:hover { color:%s; }
QListWidget#Nav { background:%s; border:none; font-size:18px; padding-top:10px; }
QListWidget#Nav::item { padding:16px 18px; border-radius:4px; margin:2px 8px; }
QListWidget#Nav::item:selected { background:%s; color:%s; }
QTextBrowser, QPlainTextEdit {
    background:%s; color:%s; border:1px solid %s; border-radius:4px;
    font-size:18px; padding:10px; line-height:1.5;
}
QTableWidget {
    background:%s; color:%s; border:1px solid %s; gridline-color:%s;
    font-size:16px; selection-background-color:%s;
}
QHeaderView::section { background:%s; color:%s; border:none; padding:8px; font-size:16px; }
QPushButton {
    background:%s; color:%s; border:1px solid %s; border-radius:4px;
    padding:8px 16px; font-size:16px;
}
QPushButton:hover { background:%s; }
QPushButton:disabled { color:%s; }
""" % (
    theme.DLG_BG, theme.FLOAT_TEXT,
    theme.PANEL_SOLID,
    theme.FLOAT_GOLD, theme.FLOAT_TEXT_DIM,
    theme.FLOAT_TEXT_DIM, theme.FLOAT_ACCENT,
    theme.FLOAT_FIELD,
    theme.FLOAT_SELECT_BG, theme.FLOAT_SELECT_TEXT,
    theme.FLOAT_FIELD, theme.FLOAT_TEXT, theme.FLOAT_GRID,
    theme.FLOAT_FIELD, theme.FLOAT_TEXT, theme.FLOAT_GRID,
    theme.FLOAT_GRID, theme.FLOAT_SELECT_BG,
    theme.PANEL_SOLID, theme.FLOAT_TEXT_DIM,
    theme.FLOAT_FIELD, theme.FLOAT_TEXT, theme.FLOAT_GRID,
    theme.DLG_HOVER,
    theme.FLOAT_TEXT_DIM,
)

_SCHED_LABELS = {"today": "今天课程", "week": "本周课表", "next": "下一节课"}


class InfoPanel(QtWidgets.QWidget):
    """课程表 / 待办与考试 / OCR 结果的集中面板（置顶、可缩放、可拖动）。"""

    def __init__(self, owner):
        super().__init__(None)
        self.owner = owner          # PetWindow（数据源：schedule / tasks）
        self._drag = None
        self.setWindowTitle("信息面板")
        self.setWindowFlags(
            QtCore.Qt.Window
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setMinimumSize(720, 480)
        self.resize(860, 580)
        self.setStyleSheet(_QSS)
        self.setObjectName("PanelRoot")
        self._build()

    # ── UI ─────────────────────────────────────────────────────────

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 自定义标题栏（可拖动）
        bar = QtWidgets.QWidget(self)
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(48)
        bar_layout = QtWidgets.QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 0, 8, 0)
        title = QtWidgets.QLabel("信息面板", bar)
        title.setObjectName("TitleText")
        sub = QtWidgets.QLabel("RHODES ISLAND · DESKTOP", bar)
        sub.setObjectName("TitleSub")
        close = QtWidgets.QPushButton("✕", bar)
        close.setObjectName("CloseBtn")
        close.setFixedSize(36, 36)
        close.setCursor(QtCore.Qt.PointingHandCursor)
        close.clicked.connect(self.hide)
        bar_layout.addWidget(title)
        bar_layout.addSpacing(10)
        bar_layout.addWidget(sub)
        bar_layout.addStretch(1)
        bar_layout.addWidget(close)
        root.addWidget(bar)

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(10, 10, 10, 10)
        body.setSpacing(10)
        root.addLayout(body, 1)

        # 左侧导航
        self.nav = QtWidgets.QListWidget(self)
        self.nav.setObjectName("Nav")
        self.nav.setFixedWidth(150)
        self.nav.addItem("课程表")
        self.nav.addItem("待办与考试")
        self.nav.addItem("OCR 结果")
        self.nav.currentRowChanged.connect(self._switch_page)
        body.addWidget(self.nav)

        # 右侧页面
        self.stack = QtWidgets.QStackedWidget(self)
        self.stack.addWidget(self._build_schedule_page())
        self.stack.addWidget(self._build_tasks_page())
        self.stack.addWidget(self._build_ocr_page())
        body.addWidget(self.stack, 1)

        self.nav.setCurrentRow(0)

    def _build_schedule_page(self):
        page = QtWidgets.QWidget(self)
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        btns = QtWidgets.QHBoxLayout()
        self.btn_today = QtWidgets.QPushButton("今天课程", page)
        self.btn_week = QtWidgets.QPushButton("本周课表", page)
        self.btn_next = QtWidgets.QPushButton("下一节课", page)
        self.btn_today.clicked.connect(lambda: self.show_schedule("today"))
        self.btn_week.clicked.connect(lambda: self.show_schedule("week"))
        self.btn_next.clicked.connect(lambda: self.show_schedule("next"))
        for b in (self.btn_today, self.btn_week, self.btn_next):
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.sched_view = QtWidgets.QTextBrowser(page)
        self.sched_view.setOpenExternalLinks(False)
        lay.addWidget(self.sched_view, 1)
        return page

    def _build_tasks_page(self):
        page = QtWidgets.QWidget(self)
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        tip = QtWidgets.QLabel("双击任务可标记完成；选中后可用下方按钮操作。", page)
        tip.setStyleSheet("color:%s;font-size:15px;" % theme.FLOAT_TEXT_DIM)
        lay.addWidget(tip)

        self.task_table = QtWidgets.QTableWidget(0, 5, page)
        self.task_table.setHorizontalHeaderLabels(
            ["状态", "事项", "课程", "截止时间", "剩余"])
        self.task_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows)
        self.task_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection)
        self.task_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self.task_table.verticalHeader().setVisible(False)
        header = self.task_table.horizontalHeader()
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for col in (0, 2, 3, 4):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        self.task_table.itemDoubleClicked.connect(lambda *_: self._toggle_done())
        lay.addWidget(self.task_table, 1)

        btns = QtWidgets.QHBoxLayout()
        self.btn_done = QtWidgets.QPushButton("标记完成", page)
        self.btn_del = QtWidgets.QPushButton("删除", page)
        self.btn_refresh = QtWidgets.QPushButton("刷新", page)
        self.btn_done.clicked.connect(self._toggle_done)
        self.btn_del.clicked.connect(self._remove_task)
        self.btn_refresh.clicked.connect(self.refresh_tasks)
        for b in (self.btn_done, self.btn_del):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(self.btn_refresh)
        lay.addLayout(btns)
        return page

    def _build_ocr_page(self):
        page = QtWidgets.QWidget(self)
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.ocr_status = QtWidgets.QLabel("暂无 OCR 结果。", page)
        self.ocr_status.setStyleSheet(
            "color:%s;font-size:16px;" % theme.FLOAT_TEXT_DIM)
        lay.addWidget(self.ocr_status)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, page)
        self.ocr_source = QtWidgets.QPlainTextEdit(page)
        self.ocr_result = QtWidgets.QPlainTextEdit(page)
        for w in (self.ocr_source, self.ocr_result):
            w.setReadOnly(True)
            w.setPlaceholderText("")
        self.ocr_source.setPlaceholderText("原文（识别结果）")
        self.ocr_result.setPlaceholderText("译文 / 总结")
        split.addWidget(self.ocr_source)
        split.addWidget(self.ocr_result)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        lay.addWidget(split, 1)
        return page

    # ── 行为 ───────────────────────────────────────────────────────

    def _switch_page(self, row):
        self.stack.setCurrentIndex(row)
        if row == 0:
            self.show_schedule("week")
        elif row == 1:
            self.refresh_tasks()

    def show_schedule(self, which):
        """展示课程表：'today' / 'week' / 'next'。"""
        s = self.owner.schedule
        self.nav.setCurrentRow(0)
        self.stack.setCurrentIndex(0)
        if not s.courses:
            self.sched_view.setPlainText(
                "还没有导入课表。右键菜单 → 课程表 → 导入课表。")
            return
        week_no = s.week_no()
        if which == "today":
            courses = s.today(week_no)
            if not courses:
                text = "今天没有课，博士可以自由安排。"
            else:
                parts = []
                for c in courses:
                    line = c.display(s.sections)
                    if week_no and not c.active_on(week_no):
                        line += "（本周不上）"
                    parts.append(line)
                text = "今天有 %d 节课：\n\n%s" % (len(courses), "\n".join(parts))
        elif which == "next":
            nxt = s.next_class()
            if not nxt:
                text = "本周没有剩下的课了，博士可以休息。"
            else:
                c, _, _, start = nxt
                mins = int((start - datetime.now()).total_seconds() // 60)
                where = " @%s" % c.room if c.room else ""
                text = "下一节：%d-%d节 %s  %s%s（%d 分钟后）" % (
                    c.sec_start, c.sec_end, c.name, start.strftime("%H:%M"),
                    where, mins)
        else:
            text = s.dump_text(week_no=week_no)
        self.sched_view.setPlainText(text)
        self.sched_view.moveCursor(QtGui.QTextCursor.Start)

    def refresh_tasks(self):
        """从 owner.tasks 重建待办表格。"""
        self.nav.setCurrentRow(1)
        self.stack.setCurrentIndex(1)
        tasks = self.owner.tasks
        now = datetime.now()
        rows = sorted(tasks.items, key=lambda t: (t.done, t.due))
        self.task_table.setRowCount(len(rows))
        for i, t in enumerate(rows):
            tag = "考试" if t.kind == "exam" else "作业"
            title = "%s · %s" % (tag, t.title)
            if t.done:
                state, left = "✓ 完成", "—"
                color = theme.FLOAT_TEXT_DIM
            elif t.expired(now):
                state, left = "已过期", "—"
                color = theme.RED
            else:
                state = "待办"
                d = t.due - now
                if d.days >= 1:
                    left = "%d 天" % d.days
                elif d.seconds >= 3600:
                    left = "%d 小时" % (d.seconds // 3600)
                else:
                    left = "%d 分钟" % max(1, d.seconds // 60)
                color = theme.FLOAT_TEXT
            items = [QtWidgets.QTableWidgetItem(state),
                     QtWidgets.QTableWidgetItem(title),
                     QtWidgets.QTableWidgetItem(t.course),
                     QtWidgets.QTableWidgetItem(
                         t.due.strftime("%m-%d %H:%M")),
                     QtWidgets.QTableWidgetItem(left)]
            for it in items:
                it.setForeground(QtGui.QColor(color))
                it.setTextAlignment(QtCore.Qt.AlignCenter)
            items[1].setTextAlignment(QtCore.Qt.AlignLeft
                                      | QtCore.Qt.AlignVCenter)
            self.task_table.setItem(i, 0, items[0])
            self.task_table.setItem(i, 1, items[1])
            self.task_table.setItem(i, 2, items[2])
            self.task_table.setItem(i, 3, items[3])
            self.task_table.setItem(i, 4, items[4])
            self.task_table.item(i, 0).setData(QtCore.Qt.UserRole, t.id)

    def _selected_task_id(self):
        row = self.task_table.currentRow()
        if row < 0:
            return None
        return self.task_table.item(row, 0).data(QtCore.Qt.UserRole)

    def _toggle_done(self):
        tid = self._selected_task_id()
        if not tid:
            return
        for t in self.owner.tasks.items:
            if t.id == tid:
                self.owner.tasks.set_done(tid, not t.done)
                break
        self.refresh_tasks()

    def _remove_task(self):
        tid = self._selected_task_id()
        if not tid:
            return
        self.owner.tasks.remove(tid)
        self.refresh_tasks()

    def show_ocr(self, mode, text, result):
        """展示 OCR 结果（mode: 'translate' / 'summarize'）。"""
        self.nav.setCurrentRow(2)
        self.stack.setCurrentIndex(2)
        label = "截图翻译" if mode == "translate" else "截图总结"
        self.ocr_status.setText("%s · %s 字符" % (label, len(text)))
        self.ocr_source.setPlainText(text)
        self.ocr_result.setPlainText(result)

    # ── 窗口行为（拖动 / Esc 关闭）─────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and e.y() <= 48:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPos() - self._drag)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def present(self):
        """显示并置前面板（页面切换由各 show_* / refresh_* 方法负责）。"""
        if not self.isVisible():
            self._center()
        self.show()
        self.raise_()
        self.activateWindow()

    def _center(self):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())
