"""课程表周视图：按节次画等宽色块（高度∝课程持续节数，宽度一致）。

每列是一个星期（列序 日一二三四五六），左侧是节次/时间轴；每门课画成
一个矩形色块，课程名 + 老师 + 教室标在块上。空白节次留白。本周不上
（周次/单双周不匹配）的课用半透明 + 虚线框弱化显示。
"""

from PyQt5 import QtCore, QtGui, QtWidgets

from . import theme

ROW_H = 30           # 每节课的高度（px，仅作注释参考）
COL_W = 104          # 每列宽度（px，仅作注释参考）
RULER_W = 52         # 左侧节次/时间轴宽度（固定）
HEADER_H = 26        # 顶部星期标题高度（固定）
MARGIN = 10
GAP = 3              # 课程块之间的垂直间隙
MAX_SECTIONS = 13    # 一天最多 13 节课

# 列序：周日 -> 周一 -> ... -> 周六（weekday 7,1,2,3,4,5,6）
_COL_WEEKDAYS = [7, 1, 2, 3, 4, 5, 6]
_DAY_LABELS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}

# 可区分色板（深色背景上的亮色块）
_COLORS = [
    QtGui.QColor(66, 133, 244),    # 蓝
    QtGui.QColor(52, 168, 83),     # 绿
    QtGui.QColor(234, 67, 53),     # 红
    QtGui.QColor(255, 167, 38),    # 橙
    QtGui.QColor(171, 71, 188),    # 紫
    QtGui.QColor(0, 172, 193),     # 青
    QtGui.QColor(121, 85, 72),     # 棕
    QtGui.QColor(255, 112, 67),    # 橘红
    QtGui.QColor(26, 188, 156),    # 青绿
    QtGui.QColor(149, 117, 205),   # 浅紫
]


class TimetableView(QtWidgets.QWidget):
    """自适应填满窗口的周课表色块视图（无滚动条，文字自动换行）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._schedule = None
        self._week_no = None
        self._courses = {}          # weekday -> [Course]
        self._notes = []
        self._color_of = {}         # 课程名 -> QColor（稳定配色）
        self.setAutoFillBackground(True)
        self.setMinimumSize(560, 400)

    # ── 数据 ─────────────────────────────────────────────────────────

    def set_data(self, sched, week_no):
        """填充课表数据并重绘。week_no 用于标记「本周不上」。"""
        self._schedule = sched
        self._week_no = week_no
        self._notes = list(sched.notes)
        self._courses = {wd: sched.courses_on(wd, None)
                         for wd in range(1, 8)}
        self._color_of = {}
        idx = 0
        for wd in range(1, 8):
            for c in self._courses[wd]:
                if c.name not in self._color_of:
                    self._color_of[c.name] = _COLORS[idx % len(_COLORS)]
                    idx += 1
        self.update()

    # ── 尺寸（自适应填满窗口，无滚动条）──────────────────────────────

    def sizeHint(self):
        """随窗口伸缩：列宽/行高由可用空间均分。"""
        return self.minimumSize()

    def _grid_rect(self):
        """网格区域（不含左侧时间轴与顶部标题）。"""
        x = MARGIN + RULER_W
        y = MARGIN + HEADER_H
        w = max(100, self.width() - x - MARGIN)
        h = max(100, self.height() - y - MARGIN)
        return QtCore.QRect(x, y, w, h)

    def _col_w(self):
        return self._grid_rect().width() / len(_COL_WEEKDAYS)

    def _row_h(self):
        return self._grid_rect().height() / MAX_SECTIONS

    # ── 绘制 ─────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # 背景
        p.fillRect(self.rect(), QtGui.QColor(theme.DLG_BG))
        self._paint_grid(p)
        self._paint_header(p)
        self._paint_ruler(p)
        self._paint_courses(p)
        self._paint_notes(p)
        p.end()

    def _paint_grid(self, p):
        g = self._grid_rect()
        line = QtGui.QPen(QtGui.QColor(theme.FLOAT_GRID), 1)
        p.setPen(line)
        # 行线（每节一条横线）
        row_h = self._row_h()
        for r in range(MAX_SECTIONS + 1):
            y = round(g.top() + r * row_h)
            p.drawLine(g.left(), y, g.right(), y)
        # 列线
        col_w = self._col_w()
        for c in range(len(_COL_WEEKDAYS) + 1):
            x = round(g.left() + c * col_w)
            p.drawLine(x, g.top(), x, g.bottom())

    def _paint_header(self, p):
        font = QtGui.QFont(theme.FONT, 13, QtGui.QFont.Bold)
        p.setFont(font)
        p.setPen(QtGui.QColor(theme.FLOAT_TEXT))
        col_w = self._col_w()
        for i, wd in enumerate(_COL_WEEKDAYS):
            x = round(MARGIN + RULER_W + i * col_w)
            rect = QtCore.QRect(x, MARGIN, round(col_w), HEADER_H)
            p.drawText(rect, QtCore.Qt.AlignCenter,
                       "周%s" % _DAY_LABELS[wd])

    def _paint_ruler(self, p):
        # 节次/时间轴：显示起始时刻（若有 sections）
        p.setFont(QtGui.QFont(theme.FONT, 9))
        p.setPen(QtGui.QColor(theme.FLOAT_TEXT_DIM))
        secs = getattr(self._schedule, "sections", None) or {}
        row_h = self._row_h()
        for r in range(MAX_SECTIONS):
            sec = r + 1
            label = str(sec)
            t = secs.get(str(sec))
            if t:
                label = "%d %s" % (sec, t)
            y = round(MARGIN + HEADER_H + r * row_h)
            rect = QtCore.QRect(MARGIN, y, RULER_W - 6, round(row_h))
            p.drawText(rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                       label)

    def _paint_courses(self, p):
        if self._schedule is None:
            return
        col_w = self._col_w()
        row_h = self._row_h()
        for i, wd in enumerate(_COL_WEEKDAYS):
            col_x = round(MARGIN + RULER_W + i * col_w)
            for c in self._courses[wd]:
                x = col_x + 2
                y = round(MARGIN + HEADER_H + (c.sec_start - 1) * row_h)
                h = round((c.sec_end - c.sec_start + 1) * row_h - GAP)
                rect = QtCore.QRect(x, y, round(col_w) - 4, h)
                active = not (self._week_no and not c.active_on(self._week_no))
                color = self._color_of.get(c.name, _COLORS[0])
                if not active:
                    color = QtGui.QColor(color)
                    color.setAlpha(70)
                p.setPen(QtGui.QPen(QtGui.QColor(color).darker(130), 1))
                p.setBrush(QtGui.QBrush(color))
                p.drawRoundedRect(rect, 4, 4)
                if not active:
                    # 虚线框：本周不上
                    pen = QtGui.QPen(QtGui.QColor(theme.FLOAT_TEXT_DIM), 1,
                                     QtCore.Qt.DashLine)
                    p.setPen(pen)
                    p.setBrush(QtCore.Qt.NoBrush)
                    p.drawRoundedRect(rect, 4, 4)
                self._paint_course_text(p, rect, c)

    def _paint_course_text(self, p, rect, c):
        """课程名（自动换行，最多三行）+ 老师 @教室 画在块内。"""
        inner = rect.adjusted(4, 2, -4, -2)
        if rect.height() >= 44:
            # 上：课程名（最多三行）；下：老师 @教室
            name_h = min(3 * 14, max(14, inner.height() - 14))
            name_rect = QtCore.QRect(inner)
            name_rect.setHeight(max(13, name_h))
            p.setFont(QtGui.QFont(theme.FONT, 11, QtGui.QFont.Bold))
            p.setPen(QtGui.QColor(255, 255, 255))
            p.drawText(name_rect,
                       QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop
                       | QtCore.Qt.TextWordWrap, c.name)
            detail = " ".join(x for x in (c.teacher, c.room) if x)
            if detail:
                drect = QtCore.QRect(inner)
                drect.setTop(inner.top() + name_h)
                p.setFont(QtGui.QFont(theme.FONT, 9))
                p.setPen(QtGui.QColor(240, 240, 240))
                p.drawText(drect,
                           QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop
                           | QtCore.Qt.TextWordWrap, detail)
        else:
            p.setFont(QtGui.QFont(theme.FONT, 10, QtGui.QFont.Bold))
            p.setPen(QtGui.QColor(255, 255, 255))
            p.drawText(inner, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                       c.name)

    def _paint_notes(self, p):
        if not self._notes:
            return
        p.setFont(QtGui.QFont(theme.FONT, 10))
        p.setPen(QtGui.QColor(theme.FLOAT_TEXT_DIM))
        y = self._grid_rect().bottom() + 6
        p.drawText(QtCore.QRect(MARGIN, y, self.width() - 2 * MARGIN, 22),
                   QtCore.Qt.AlignLeft, "网课：" + "；".join(self._notes))
