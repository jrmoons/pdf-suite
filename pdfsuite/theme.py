from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "window": "#f2f3f5",
    "text": "#1c1c1e",
    "base": "#ffffff",
    "alt_base": "#eceef1",
    "button": "#e7e9ec",
    "border": "#d0d3d8",
    "highlight": "#2f6fed",
    "highlight_text": "#ffffff",
    "surround": "#c7cad0",
    "icon": "#33363b",
    "disabled": "#9a9ea5",
}

DARK = {
    "window": "#2b2d31",
    "text": "#e7e8ea",
    "base": "#1e1f22",
    "alt_base": "#313338",
    "button": "#383a40",
    "border": "#1a1b1e",
    "highlight": "#5865f2",
    "highlight_text": "#ffffff",
    "surround": "#1a1b1e",
    "icon": "#dcddde",
    "disabled": "#6b6d72",
}


def _make_palette(t: dict) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["window"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["base"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["alt_base"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["button"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(t["base"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["highlight"]))
    pal.setColor(QPalette.HighlightedText, QColor(t["highlight_text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["disabled"]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(t["disabled"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["disabled"]))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["disabled"]))
    return pal


def _qss(t: dict) -> str:
    return f"""
    QMainWindow, QDialog {{ background: {t['window']}; }}
    QMenuBar {{ background: {t['window']}; color: {t['text']}; border-bottom: 1px solid {t['border']}; }}
    QMenuBar::item:selected {{ background: {t['highlight']}; color: {t['highlight_text']}; }}
    QMenu {{ background: {t['base']}; color: {t['text']}; border: 1px solid {t['border']}; }}
    QMenu::item:selected {{ background: {t['highlight']}; color: {t['highlight_text']}; }}
    QToolBar {{
        background: {t['window']}; border: none; border-bottom: 1px solid {t['border']};
        spacing: 2px; padding: 3px;
    }}
    QToolBar::separator {{ background: {t['border']}; width: 1px; margin: 4px 6px; }}
    QToolButton {{
        background: transparent; color: {t['text']}; border: 1px solid transparent;
        border-radius: 5px; padding: 4px 6px; font-size: 11px;
    }}
    QToolButton:hover {{ background: {t['alt_base']}; border: 1px solid {t['border']}; }}
    QToolButton:checked {{ background: {t['highlight']}; color: {t['highlight_text']}; }}
    QToolButton:disabled {{ color: {t['disabled']}; }}
    QStatusBar {{ background: {t['window']}; color: {t['text']}; border-top: 1px solid {t['border']}; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{
        background: {t['alt_base']}; color: {t['text']}; padding: 6px 12px;
        border: 1px solid {t['border']}; border-bottom: none;
    }}
    QTabBar::tab:selected {{ background: {t['base']}; }}
    QListWidget {{ background: {t['base']}; color: {t['text']}; border: none; }}
    QListWidget::item:selected {{ background: {t['highlight']}; color: {t['highlight_text']}; }}
    QLineEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {t['base']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: 3px; padding: 2px;
    }}
    QSplitter::handle {{ background: {t['border']}; }}
    QPushButton {{
        background: {t['button']}; color: {t['text']}; border: 1px solid {t['border']};
        border-radius: 4px; padding: 5px 12px;
    }}
    QPushButton:hover {{ background: {t['highlight']}; color: {t['highlight_text']}; }}
    QLabel {{ color: {t['text']}; }}
    """


def apply_theme(app: QApplication, dark: bool):
    t = DARK if dark else LIGHT
    app.setPalette(_make_palette(t))
    app.setStyleSheet(_qss(t))


def icon_color(dark: bool) -> QColor:
    return QColor((DARK if dark else LIGHT)["icon"])


def surround_color(dark: bool) -> QColor:
    return QColor((DARK if dark else LIGHT)["surround"])
