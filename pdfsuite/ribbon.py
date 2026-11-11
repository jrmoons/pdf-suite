"""Tabbed ribbon: one row of large icon buttons per tab
(Accueil · Commentaires · Mesures · Pages · Protéger · Affichage)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabBar, QStackedWidget, QToolBar


class Ribbon(QWidget):
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab_bar = QTabBar()
        self.tab_bar.setDrawBase(False)
        self.tab_bar.setExpanding(False)
        self.stack = QStackedWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tab_bar)
        layout.addWidget(self.stack)
        self.tab_bar.currentChanged.connect(self._on_changed)
        self.setObjectName("Ribbon")

    def _on_changed(self, index: int):
        self.stack.setCurrentIndex(index)
        # keep the ribbon only as tall as the current page
        for i in range(self.stack.count()):
            self.stack.widget(i).setVisible(i == index)
        self.currentChanged.emit(index)

    def add_page(self, title: str) -> QToolBar:
        tb = QToolBar(title)
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(22, 22))
        tb.setMovable(False)
        tb.setFloatable(False)
        self.stack.addWidget(tb)
        self.tab_bar.addTab(title)
        return tb

    def page_titles(self) -> list[str]:
        return [self.tab_bar.tabText(i) for i in range(self.tab_bar.count())]

    def set_current(self, index: int):
        if 0 <= index < self.tab_bar.count():
            self.tab_bar.setCurrentIndex(index)
            self._on_changed(index)
