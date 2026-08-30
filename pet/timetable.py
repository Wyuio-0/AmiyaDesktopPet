"""课程表周视图：按节次画等宽色块（高度∝课程持续节数，宽度一致）。

每列是一个星期（列序 日一二三四五六），左侧是节次/时间轴；每门课画成
一个矩形色块，课程名 + 老师 + 教室标在块上。空白节次留白。本周不上
（周次/单双周不匹配）的课用半透明 + 虚线框弱化显示。
"""

from PyQt5 import QtCore, QtGui, QtWidgets

from . import theme

ROW_H = 30           # 每节课的高度（px）
COL_W = 104          # 每列宽度（px）
RULER_W = 60         # 左侧节次/时间轴宽度
HEADER_H = 30        # 顶部星期标题高度
MARGIN = 12
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
    """可滚动的周课表色块视图（数据来自 Schedule）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._schedule = None
        self._week_no = None
        self._courses = {}          # weekday -> [Course]
        self._notes = []
        self._color_of = {}         # 课程名 -> QColor（稳定配色）
        self.setAutoFillBackground(True)

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

    # ── 尺寸 ─────────────────────────────────────────────────────────

    def sizeHint(self):
        w = MARGIN * 2 + RULER_W + len(_COL_WEEKDAYS) * COL_W
        h = (MARGIN * 2 + HEADER_H + MAX_SECTIONS * ROW_H
             + (34 if self._notes else 6))
        return QtCore.QSize(w, h)

    def _grid_rect(self):
        """网格区域（不含左侧时间轴与顶部标题）。"""
        x = MARGIN + RULER_W
        y = MARGIN + HEADER_H
        return QtCore.QRect(x, y, len(_COL_WEEKDAYS) * COL_W,
                            MAX_SECTIONS * ROW_H)

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
        for r in range(MAX_SECTIONS + 1):
            y = g.top() + r * ROW_H
            p.drawLine(g.left(), y, g.right(), y)
        # 列线
        for c in range(len(_COL_WEEKDAYS) + 1):
            x = g.left() + c * COL_W
            p.drawLine(x, g.top(), x, g.bottom())

    def _paint_header(self, p):
        font = QtGui.QFont(theme.FONT, 14, QtGui.QFont.Bold)
        p.setFont(font)
        p.setPen(QtGui.QColor(theme.FLOAT_TEXT))
        for i, wd in enumerate(_COL_WEEKDAYS):
            x = MARGIN + RULER_W + i * COL_W
            rect = QtCore.QRect(x, MARGIN, COL_W, HEADER_H)
            p.drawText(rect, QtCore.Qt.AlignCenter,
                       "周%s" % _DAY_LABELS[wd])

    def _paint_ruler(self, p):
        # 节次/时间轴：显示起始时刻（若有 sections）
        p.setFont(QtGui.QFont(theme.FONT, 10))
        p.setPen(QtGui.QColor(theme.FLOAT_TEXT_DIM))
        secs = getattr(self._schedule, "sections", None) or {}
        for r in range(MAX_SECTIONS):
            sec = r + 1
            label = str(sec)
            t = secs.get(str(sec))
            if t:
                label = "%d %s" % (sec, t)
            y = MARGIN + HEADER_H + r * ROW_H
            rect = QtCore.QRect(MARGIN, y, RULER_W - 6, ROW_H)
            p.drawText(rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                       label)

    def _paint_courses(self, p):
        if self._schedule is None:
            return
        for i, wd in enumerate(_COL_WEEKDAYS):
            col_x = MARGIN + RULER_W + i * COL_W
            for c in self._courses[wd]:
                x = col_x + 2
                y = MARGIN + HEADER_H + (c.sec_start - 1) * ROW_H
                h = (c.sec_end - c.sec_start + 1) * ROW_H - GAP
                rect = QtCore.QRect(x, y, COL_W - 4, h)
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
        """课程名 + 老师 @教室 画在块内（块太矮时只画课程名）。"""
        text_color = QtGui.QColor(255, 255, 255)
        p.setPen(text_color)
        inner = rect.adjusted(6, 2, -6, -2)
        if rect.height() >= 2 * 16:
            p.setFont(QtGui.QFont(theme.FONT, 12, QtGui.QFont.Bold))
            p.drawText(inner, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
                       _clip(c.name, inner.width(), p.font()))
            detail = " ".join(x for x in (c.teacher, c.room) if x)
            if detail:
                p.setFont(QtGui.QFont(theme.FONT, 10))
                p.setPen(QtGui.QColor(235, 235, 235))
                drect = QtCore.QRect(inner)
                drect.setTop(inner.top() + 16)
                p.drawText(drect,
                           QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
                           _clip(detail, inner.width(), p.font()))
        else:
            p.setFont(QtGui.QFont(theme.FONT, 11, QtGui.QFont.Bold))
            p.drawText(inner, QtCore.Qt.AlignCenter,
                       _clip(c.name, inner.width(), p.font()))

    def _paint_notes(self, p):
        if not self._notes:
            return
        p.setFont(QtGui.QFont(theme.FONT, 11))
        p.setPen(QtGui.QColor(theme.FLOAT_TEXT_DIM))
        y = MARGIN + HEADER_H + MAX_SECTIONS * ROW_H + 8
        p.drawText(QtCore.QRect(MARGIN, y, self.width() - 2 * MARGIN, 24),
                   QtCore.Qt.AlignLeft, "网课（无固定时间）：" + "；".join(self._notes))


def _clip(text, width, font):
    """按像素宽度截断文本并加省略号。"""
    m = QtGui.QFontMetrics(font)
    if m.horizontalAdvance(text) <= width:
        return text
    ell = "…"
    while text and m.horizontalAdvance(text + ell) > width:
        text = text[:-1]
    return text + ell
