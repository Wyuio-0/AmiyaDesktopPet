"""AI provider settings dialog."""

import json
import os

from PyQt5 import QtCore, QtWidgets

from . import theme


PROVIDERS = [
    ("DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
    ("Kimi", "https://api.moonshot.cn", "moonshot-v1-8k"),
    ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("OpenAI", "https://api.openai.com", "gpt-4o-mini"),
    ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4"),
    ("本地 Ollama", "http://localhost:11434/v1", "qwen2.5:7b"),
    ("自定义", "", ""),
]


def config_path(char_dir):
    return os.path.join(char_dir, "ai_config.json")


def read_raw_config(char_dir):
    """Read ai_config.json, falling back to ai_config.example.json.

    On a fresh clone only the .example.json template exists (the real config is
    gitignored to prevent API-key leaks).  When the user opens AI settings for
    the first time, the .example.json values pre-fill the dialog and get saved
    to the local-only ai_config.json on confirm.
    """
    path = config_path(char_dir)
    example = os.path.join(char_dir, "ai_config.example.json")
    candidates = [path, example]
    for p in candidates:
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        return data if isinstance(data, dict) else {}
    return {}


def save_config(char_dir, cfg):
    path = config_path(char_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


class AiSettingsDialog(QtWidgets.QDialog):
    """Small editor for OpenAI-compatible chat endpoint settings."""

    saved = QtCore.pyqtSignal(dict)

    def __init__(self, char_dir, effective_cfg=None, parent=None,
                 character_name="阿米娅"):
        super().__init__(parent)
        self.char_dir = char_dir
        self.character_name = character_name
        self.setWindowTitle("模型配置")
        self.setModal(True)
        self.setMinimumWidth(720)
        self.setStyleSheet(theme.DIALOG_QSS)

        raw = read_raw_config(char_dir)
        self.cfg = {
            "base_url": raw.get("base_url", "https://api.deepseek.com"),
            "model": raw.get("model", "deepseek-chat"),
            "api_key": raw.get("api_key", ""),
            "temperature": raw.get("temperature", 0.8),
            "allow_actions": raw.get("allow_actions", True),
        }
        # Show the values that are actually in use when environment variables
        # override the file, but save back into the character config.
        if effective_cfg:
            for key in ("base_url", "model", "api_key", "temperature",
                        "allow_actions"):
                if key in effective_cfg:
                    self.cfg[key] = effective_cfg[key]

        self._build_ui()
        self._load_values()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QtWidgets.QLabel("RHODES ISLAND", self)
        title.setObjectName("TerminalTitle")
        root.addWidget(title)

        subtitle = QtWidgets.QLabel("%s MODEL CONFIGURATION" % self.character_name, self)
        subtitle.setObjectName("TerminalSubTitle")
        root.addWidget(subtitle)

        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        root.addLayout(form)

        self.provider = QtWidgets.QComboBox(self)
        for name, _, _ in PROVIDERS:
            self.provider.addItem(name)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        form.addRow("服务商", self.provider)

        self.base_url = QtWidgets.QLineEdit(self)
        self.base_url.setPlaceholderText("https://... 或 http://localhost:11434/v1")
        form.addRow("接口地址", self.base_url)

        self.model = QtWidgets.QLineEdit(self)
        self.model.setPlaceholderText("例如 moonshot-v1-8k / qwen-plus")
        form.addRow("模型", self.model)

        self.api_key = QtWidgets.QLineEdit(self)
        self.api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.api_key.setPlaceholderText("不填则离线使用内置台词")
        form.addRow("API Key", self.api_key)

        self.temperature = QtWidgets.QDoubleSpinBox(self)
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setDecimals(1)
        form.addRow("灵活度", self.temperature)

        self.allow_actions = QtWidgets.QCheckBox(
            "允许%s操作电脑" % self.character_name, self)
        form.addRow("", self.allow_actions)

        self.note = QtWidgets.QLabel(
            "支持兼容 /v1/chat/completions 的接口。若设置了 PET_AI_* 环境变量，"
            "运行时会优先使用环境变量。",
            self,
        )
        self.note.setObjectName("TerminalNote")
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel,
            self,
        )
        buttons.button(QtWidgets.QDialogButtonBox.Save).setText("保存")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_values(self):
        self.base_url.setText(str(self.cfg.get("base_url") or ""))
        self.model.setText(str(self.cfg.get("model") or ""))
        self.api_key.setText(str(self.cfg.get("api_key") or ""))
        self.temperature.setValue(float(self.cfg.get("temperature", 0.8)))
        self.allow_actions.setChecked(bool(self.cfg.get("allow_actions", True)))
        self.provider.setCurrentIndex(self._provider_index(self.base_url.text()))

    def _provider_index(self, base_url):
        base_url = (base_url or "").rstrip("/")
        for i, (_, url, _) in enumerate(PROVIDERS[:-1]):
            if base_url == url.rstrip("/"):
                return i
        return len(PROVIDERS) - 1

    def _provider_changed(self, index):
        _, url, model = PROVIDERS[index]
        if not url:
            return
        self.base_url.setText(url)
        self.model.setText(model)

    def _save(self):
        base_url = self.base_url.text().strip().rstrip("/")
        model = self.model.text().strip()
        api_key = self.api_key.text().strip()
        if not base_url:
            QtWidgets.QMessageBox.warning(self, "模型配置", "请填写接口地址。")
            return
        if not model:
            QtWidgets.QMessageBox.warning(self, "模型配置", "请填写模型名称。")
            return

        cfg = {
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "temperature": self.temperature.value(),
            "allow_actions": self.allow_actions.isChecked(),
        }
        try:
            save_config(self.char_dir, cfg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "模型配置", "保存失败：%s" % type(e).__name__)
            return
        self.saved.emit(cfg)
        self.accept()
