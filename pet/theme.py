"""Shared Qt theme — dark by default; the UI adapts to the system light/dark
color scheme so text stays readable over either desktop.

The speech bubble, translation popup, input bar, countdown badge, right-click
context menu and settings dialogs all pick their colors from the adaptive
FLOAT_*/DLG_* names which match the system color scheme: light desktop ->
light panels + dark text, dark desktop -> dark panels + light text.
"""

# ── Dark palette (the app's signature look) ──────────────────────────────
BG = "#070707"
PANEL = "rgba(10, 10, 10, 242)"
PANEL_SOLID = "#0B0B0B"
FIELD = "#141414"
FIELD_DARK = "#101010"
TEXT = "#F1F1F1"
TEXT_DIM = "#A4A4A4"
ACCENT = "#C7C7C7"
ACCENT_SOFT = "#6E6E6E"
GOLD = "#B99A5B"
RED = "#C76B5E"
GRID = "#2A2A2A"

FONT = "'Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI'"
MONO = "'Cascadia Mono', 'Consolas', 'Microsoft YaHei UI'"


# ── Light palette (floating overlays on a light desktop) ─────────────────
_L_PANEL = "rgba(250, 250, 250, 246)"
_L_TEXT = "#1F1F1F"
_L_TEXT_DIM = "#666666"
_L_ACCENT = "#3A3A3A"
_L_ACCENT_SOFT = "#8A8A8A"
_L_GOLD = "#8A6A2F"
_L_GRID = "#CCCCCC"
_L_FIELD = "#EFEFEF"
_L_SOLID = "#FAFAFA"          # menu background
_L_SELECT_BG = "#E8E8E8"      # menu hover highlight
_L_SELECT_TEXT = "#1F1F1F"    # menu hover text
_L_BG = "#F5F5F5"             # dialog background
_L_FIELD_NORM = "#FFFFFF"     # dialog input background
_L_FIELD_FOCUS = "#FFFFFF"    # dialog input focus background
_L_TINT = "rgba(0, 0, 0, 10)"       # subtle note panel tint
_L_HOVER = "rgba(0, 0, 0, 8)"       # button hover tint
_L_PRESSED = "rgba(0, 0, 0, 16)"    # button pressed tint


def _system_is_dark():
    """Best-effort detection of the Windows app color scheme.

    Reads the per-app theme registry value "AppsUseLightTheme": 0 -> dark,
    1 -> light.  Falls back to dark (the app's historical default) when the
    registry is unavailable.
    """
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except (OSError, ImportError):
        return True


if _system_is_dark():
    FLOAT_PANEL = PANEL
    FLOAT_TEXT = TEXT
    FLOAT_TEXT_DIM = TEXT_DIM
    FLOAT_ACCENT = ACCENT
    FLOAT_ACCENT_SOFT = ACCENT_SOFT
    FLOAT_GOLD = GOLD
    FLOAT_GRID = GRID
    FLOAT_FIELD = FIELD_DARK
    FLOAT_SOLID = PANEL_SOLID
    FLOAT_SELECT_BG = "rgba(255, 255, 255, 28)"
    FLOAT_SELECT_TEXT = "white"
    DLG_BG = BG
    DLG_FIELD = FIELD
    DLG_FIELD_FOCUS = FIELD_DARK
    DLG_TINT = "rgba(255, 255, 255, 16)"
    DLG_HOVER = "rgba(255, 255, 255, 26)"
    DLG_PRESSED = "rgba(255, 255, 255, 42)"
else:
    FLOAT_PANEL = _L_PANEL
    FLOAT_TEXT = _L_TEXT
    FLOAT_TEXT_DIM = _L_TEXT_DIM
    FLOAT_ACCENT = _L_ACCENT
    FLOAT_ACCENT_SOFT = _L_ACCENT_SOFT
    FLOAT_GOLD = _L_GOLD
    FLOAT_GRID = _L_GRID
    FLOAT_FIELD = _L_FIELD
    FLOAT_SOLID = _L_SOLID
    FLOAT_SELECT_BG = _L_SELECT_BG
    FLOAT_SELECT_TEXT = _L_SELECT_TEXT
    DLG_BG = _L_BG
    DLG_FIELD = _L_FIELD_NORM
    DLG_FIELD_FOCUS = _L_FIELD_FOCUS
    DLG_TINT = _L_TINT
    DLG_HOVER = _L_HOVER
    DLG_PRESSED = _L_PRESSED


MENU_QSS = """
QMenu {
    background: %s;
    color: %s;
    border: 1px solid %s;
    padding: 6px;
    font-family: %s;
    font-size: 21px;
}
QMenu::item {
    padding: 12px 42px 12px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background: %s;
    color: %s;
}
QMenu::item:disabled {
    color: %s;
}
QMenu::separator {
    height: 1px;
    background: %s;
    margin: 6px 4px;
}
""" % (FLOAT_SOLID, FLOAT_TEXT, FLOAT_ACCENT_SOFT, FONT,
       FLOAT_SELECT_BG, FLOAT_SELECT_TEXT,
       FLOAT_TEXT_DIM, FLOAT_GRID)


DIALOG_QSS = """
QDialog {
    background: %s;
    color: %s;
    font-family: %s;
    font-size: 21px;
}
QLabel {
    color: %s;
}
QLabel#TerminalTitle {
    color: %s;
    font-family: %s;
    font-size: 24px;
    font-weight: 700;
    padding: 0 0 2px 0;
}
QLabel#TerminalSubTitle {
    color: %s;
    font-family: %s;
    font-size: 18px;
    padding: 0 0 8px 0;
}
QLabel#TerminalNote {
    color: %s;
    background: %s;
    border-left: 3px solid %s;
    padding: 7px 9px;
}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background: %s;
    color: %s;
    border: 1px solid %s;
    border-radius: 4px;
    padding: 6px 8px;
    selection-background-color: %s;
    font-family: %s;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border: 1px solid %s;
    background: %s;
}
QComboBox::drop-down {
    width: 24px;
    border-left: 1px solid %s;
}
QCheckBox {
    color: %s;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid %s;
    background: %s;
}
QCheckBox::indicator:checked {
    background: %s;
    border: 1px solid %s;
}
QPushButton {
    background: %s;
    color: %s;
    border: 1px solid %s;
    border-radius: 4px;
    padding: 6px 14px;
    min-width: 62px;
}
QPushButton:hover {
    background: %s;
    border-color: %s;
}
QPushButton:pressed {
    background: %s;
}
""" % (
    DLG_BG, FLOAT_TEXT, FONT,
    FLOAT_TEXT,
    FLOAT_ACCENT, MONO,
    FLOAT_TEXT_DIM, MONO,
    FLOAT_TEXT_DIM, DLG_TINT, FLOAT_GOLD,
    DLG_FIELD, FLOAT_TEXT, FLOAT_GRID, FLOAT_ACCENT, MONO,
    FLOAT_ACCENT, DLG_FIELD_FOCUS,
    FLOAT_GRID,
    FLOAT_TEXT,
    FLOAT_GRID, DLG_FIELD,
    FLOAT_ACCENT, FLOAT_ACCENT,
    DLG_FIELD, FLOAT_TEXT, FLOAT_GRID,
    DLG_HOVER, FLOAT_ACCENT,
    DLG_PRESSED,
)
