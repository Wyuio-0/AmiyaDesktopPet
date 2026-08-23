"""区域框选：全屏显示截图，拖拽选择要 OCR 的区域。

用法：RegionSelect(全屏截图 PIL Image, 屏幕 QRect)
  - 拖拽画矩形，松手 emit selected(裁剪后的 PIL Image)
  - 按 Esc 或鼠标右键取消，emit cancelled()
选区外半透明遮罩、选区内原图，便于看清框的是什么。
"""

from PyQt5 import QtCore, QtGui, QtWidgets


class RegionSelect(QtWidgets.QWidget):
    selected = QtCore.pyqtSignal(object)   # PIL Image（裁剪区域）
    cancelled = QtCore.pyqtSignal()

    def __init__(self, screen_image, screen_geom, dpr=1.0, parent=None):
        super().__init__(parent)
        # screen_image 是目标屏幕的**物理像素**截图；窗口用逻辑尺寸
        # （screen_geom），绘制时按 dpr 缩放，裁剪时再换算回物理像素，
        # 保证 HiDPI / 多显示器下截图与遮罩对齐、选区内容正确。
        self._img = screen_image            # PIL Image（全屏）
        self._dpr = max(1e-3, float(dpr or 1.0))
        self._qimg = self._to_qimage(screen_image)
        self._start = None                  # 拖拽起点（窗口坐标）
        self._rect = None                   # 当前选区 QRect
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setGeometry(screen_geom)
        self.setMouseTracking(True)

    @staticmethod
    def _to_qimage(pil_img):
        img = pil_img.convert("RGBA")
        data = img.tobytes("raw", "RGBA")
        return QtGui.QImage(data, img.width, img.height,
                            QtGui.QImage.Format_RGBA8888).copy()

    # ── 交互 ─────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._start = e.pos()
            self._rect = QtCore.QRect(self._start, self._start)
            self.update()
        elif e.button() == QtCore.Qt.RightButton:
            self.cancelled.emit()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self._rect = QtCore.QRect(self._start, e.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton and self._start is not None:
            self._start = None
            if self._rect is not None and self._rect.width() >= 8 \
                    and self._rect.height() >= 8:
                self._emit_selection(self._rect)
            else:
                self.cancelled.emit()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self.cancelled.emit()

    def _emit_selection(self, rect):
        d = self._dpr
        x = int(rect.x() * d)
        y = int(rect.y() * d)
        w = int(rect.width() * d)
        h = int(rect.height() * d)
        iw, ih = self._img.size
        x = min(max(x, 0), iw)
        y = min(max(y, 0), ih)
        w = min(w, iw - x)
        h = min(h, ih - y)
        crop = self._img.crop((x, y, x + w, y + h))
        self.selected.emit(crop)
        # 选完之后立即关掉全屏遮罩，否则它会一直悬浮在桌面上挡住一切。
        # （取消路径在 window.py 里已连接 cancelled -> sel.close。）
        self.close()

    # ── 绘制 ─────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        iw, ih = self._img.width, self._img.height
        # 整张物理像素截图缩放绘制到逻辑尺寸的窗口
        p.drawImage(self.rect(), self._qimg,
                    QtCore.QRect(0, 0, iw, ih))
        if self._rect is None:
            return
        # 选区外遮罩
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 90))
        # 把选区内对应的物理像素部分重新画出来（还原为原图）
        d = self._dpr
        src = QtCore.QRect(int(self._rect.x() * d), int(self._rect.y() * d),
                           int(self._rect.width() * d),
                           int(self._rect.height() * d))
        p.drawImage(self._rect, self._qimg, src)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 215, 0), 2))
        p.drawRect(self._rect)
        # 尺寸提示
        p.setPen(QtGui.QColor(255, 255, 255))
        p.drawText(self._rect.x() + 6, self._rect.y() - 6,
                   "%d × %d" % (self._rect.width(), self._rect.height()))
