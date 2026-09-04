"""输入框、语音气泡与打字机流式动效交互控制器。"""

from PyQt5 import QtCore

from .chat import InputBar, ReplyWorker, SpeechBubble

# Typewriter reveal: 匀速平滑展现大模型流式回复（55ms 一步），并在积压较多时自适应追赶
TYPE_INTERVAL_MS = 55
TYPE_STEP = 1

# 气泡自适应阅读停留时长：根据字数计算（250ms/字，限制在 4~20s）
READ_MS_PER_CHAR = 250
READ_MS_MIN = 4000
READ_MS_MAX = 20000


class PetInputController(QtCore.QObject):
    """协调用户输入框（InputBar）、语音气泡（SpeechBubble）、流式打字机动效及后台对话请求。"""

    def __init__(self, window):
        parent = window if isinstance(window, QtCore.QObject) else None
        super().__init__(parent)
        self.window = window

        self.bubble = SpeechBubble()
        self.input = InputBar()
        self.update_placeholder()
        self.input.submitted.connect(self.ask)

        self._worker = None
        self._chat_anchor = None

        # 打字机状态
        self._type_target = ""
        self._type_shown = 0
        self._type_final = False
        self._type_timer = QtCore.QTimer(self)
        self._type_timer.timeout.connect(self.type_tick)

    @property
    def worker(self):
        return self._worker

    @property
    def chat_anchor(self):
        return self._chat_anchor

    def update_placeholder(self):
        """更新输入框占位文本（跟随当前角色名）。"""
        name = getattr(self.window.char, "display_name", "阿米娅")
        self.input.setPlaceholderText(
            "和%s说点什么…（回车发送，Esc 关闭）" % name)

    def open_chat(self):
        """弹出输入框（若动画尚未渲染首帧则暂缓）。"""
        if not getattr(self.window, "_first_frame_shown", True):
            return
        if hasattr(self.window, "_rest_timer"):
            self.window._rest_timer.stop()
        self.window._wake()
        self.window.trans_popup.hide()
        self.input.pop_up(self.window._body_rect())

    def toggle_chat(self):
        """全局热键调用：切换输入框显示/隐藏。"""
        if self.input.isVisible():
            self.input.hide()
        else:
            self.window.raise_()
            self.open_chat()

    def ask(self, text):
        """处理用户发送的文本。"""
        w = self.window
        # 快捷翻译前缀："翻译: xxx" 或 "翻译： xxx"
        if text.startswith("翻译:") or text.startswith("翻译："):
            source = text[3:].strip()
            if source:
                self._chat_anchor = w._body_rect()
                w._do_translate(source)
            return

        # 串行化防重入：如果已有请求在跑，避免大模型历史记录交叉污染
        if self._worker is not None and self._worker.isRunning():
            w.trans_popup.show_translation(
                "", "博士稍等，我还在想上一个问题…", w._body_rect(), auto_ms=2500)
            return

        w.trans_popup.hide()
        self._chat_anchor = w._body_rect()
        self.bubble.start_stream(self._chat_anchor, "……")

        # 重置打字机
        self._type_target = ""
        self._type_shown = 0
        self._type_final = False
        self._type_timer.stop()

        self._worker = ReplyWorker(w.brain, text, self)
        self._worker.delta.connect(self.on_delta)
        self._worker.done.connect(self.on_reply)
        self._worker.start()

    def on_delta(self, text):
        """缓冲流式到来的增量文本，并启动打字机定时器。"""
        self._type_target = text or ""
        if not self._type_timer.isActive():
            self._type_timer.start(TYPE_INTERVAL_MS)

    def type_tick(self):
        """打字机心跳：逐步揭示增量字符。"""
        remaining = len(self._type_target) - self._type_shown
        if remaining <= 0:
            if self._type_final:
                self._type_timer.stop()
                self.finish_reply()
            return
        step = TYPE_STEP + (remaining // 20)
        self._type_shown = min(len(self._type_target), self._type_shown + step)
        self.bubble.update_stream(self._type_target[:self._type_shown],
                                  self._chat_anchor)

    def on_reply(self, text):
        """大模型回复完毕：播放角色反馈动效与语音，等待打字机打完剩余字符。"""
        self._type_target = text or self._type_target
        self._type_final = True
        w = self.window
        w.play(w.char.interaction("on_double_click") or "greet")
        w._speak(text)
        if not self._type_timer.isActive():
            self.type_tick()

    def finish_reply(self):
        """打字机完全展示文本后，设定基于长度的自动关闭定时器。"""
        self.bubble.update_stream(self._type_target, self._chat_anchor)
        hide_ms = max(READ_MS_MIN,
                      min(READ_MS_MAX, len(self._type_target) * READ_MS_PER_CHAR))
        self.bubble.end_stream(self._chat_anchor, auto_ms=hide_ms)

    def reposition(self, body_rect):
        """主窗口移动或拖拽时，刷新气泡和输入框锚点位置。"""
        self._chat_anchor = body_rect
        if self.bubble.isVisible():
            self.bubble.reposition(body_rect)
        if self.input.isVisible():
            self.input.reposition(body_rect)

    def stop_worker(self, timeout_ms=3000):
        """停止正在运行的对话请求线程。"""
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            if not self._worker.wait(timeout_ms):
                self._worker.terminate()
                self._worker.wait(1000)
            self._worker = None

    def close(self):
        """关闭对话输入框与气泡。"""
        self._type_timer.stop()
        self.stop_worker(1000)
        self.bubble.close()
        self.input.close()
