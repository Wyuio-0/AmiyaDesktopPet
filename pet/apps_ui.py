"""应用白名单管理对话框：图形化添加/删除阿米娅可打开的程序。

白名单数据存在 %APPDATA%\\AmiyaPet\\apps.json（{"名字": "程序路径或 exe 名"}），
由 actions 模块负责读写；本对话框只是它的图形界面。添加的程序通过
「open_app」工具让 AI 启动，走白名单校验，无法启动任意可执行文件。
"""

import os

from PyQt5 import QtCore, QtWidgets

from . import actions, theme


class AppWhitelistDialog(QtWidgets.QDialog):
    """列出白名单；添加应用（选 .exe + 起名字）/ 删除选中。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("应用白名单")
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setStyleSheet(theme.DIALOG_QSS)
        self._build()

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        head = QtWidgets.QLabel("APP WHITELIST", self)
        head.setObjectName("TerminalTitle")
        root.addWidget(head)
        sub = QtWidgets.QLabel(
            "白名单里的程序，阿米娅可以用「打开 xxx」帮你启动。", self)
        sub.setObjectName("TerminalSubTitle")
        root.addWidget(sub)

        self.list = QtWidgets.QListWidget(self)
        self.list.setAlternatingRowColors(True)
        root.addWidget(self.list, 1)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.add_btn = QtWidgets.QPushButton("添加应用…", self)
        self.del_btn = QtWidgets.QPushButton("删除选中", self)
        close_btn = QtWidgets.QPushButton("关闭", self)
        self.add_btn.clicked.connect(self._add_app)
        self.del_btn.clicked.connect(self._del_app)
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.add_btn)
        row.addWidget(self.del_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        root.addLayout(row)

        self._refresh()

    def _refresh(self):
        self.list.clear()
        apps = actions.list_custom_apps()
        if not apps:
            item = QtWidgets.QListWidgetItem(
                "（还没有自定义应用，点「添加应用…」选择程序即可）")
            item.setFlags(QtCore.Qt.NoItemFlags)
            self.list.addItem(item)
            return
        for name, target in sorted(apps.items()):
            self.list.addItem(QtWidgets.QListWidgetItem(
                "%s  →  %s" % (name, target)))

    def _add_app(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择要加入白名单的程序", "",
            "程序 (*.exe);;所有文件 (*)")
        if not path:
            return
        default = os.path.splitext(os.path.basename(path))[0]
        name, ok = QtWidgets.QInputDialog.getText(
            self, "应用名称", "阿米娅怎么称呼这个程序？", text=default)
        if not ok:
            return
        name = (name or "").strip() or default
        ok, msg = actions.add_custom_app(name, path)
        QtWidgets.QMessageBox.information(self, "应用白名单", msg)
        if ok:
            self._refresh()

    def _del_app(self):
        item = self.list.currentItem()
        if item is None or not (item.flags() & QtCore.Qt.ItemIsEnabled):
            return
        name = item.text().split("  →  ")[0].strip()
        ok, msg = actions.remove_custom_app(name)
        QtWidgets.QMessageBox.information(self, "应用白名单", msg)
        if ok:
            self._refresh()
