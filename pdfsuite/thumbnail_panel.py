from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QAbstractItemView

from .pdf_document import PdfDocument
from .page_view import pixmap_to_qpixmap


class ThumbnailPanel(QListWidget):
    pageActivated = Signal(int)
    pagesReordered = Signal(list)  # new_order: list of old indices
    deletePagesRequested = Signal(list)
    rotatePagesRequested = Signal(list, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.TopToBottom)
        self.setMovement(QListWidget.Snap)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIconSize(QSize(110, 150))
        self.setResizeMode(QListWidget.Adjust)
        self.setSpacing(8)
        self.itemActivated.connect(lambda it: self.pageActivated.emit(it.data(Qt.UserRole)))
        self.itemClicked.connect(lambda it: self.pageActivated.emit(it.data(Qt.UserRole)))
        self.model().rowsMoved.connect(self._on_rows_moved)
        self._suppress_move_signal = False

    def rebuild(self, doc: PdfDocument):
        self._suppress_move_signal = True
        self.clear()
        for i in range(doc.page_count):
            pix = doc.thumbnail(i)
            item = QListWidgetItem(QIcon(pixmap_to_qpixmap(pix)), str(i + 1))
            item.setData(Qt.UserRole, i)
            item.setTextAlignment(Qt.AlignHCenter)
            self.addItem(item)
        self._suppress_move_signal = False

    def _on_rows_moved(self, *_args):
        if self._suppress_move_signal:
            return
        order = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        self.pagesReordered.emit(order)

    def selected_pages(self) -> list[int]:
        return sorted(it.data(Qt.UserRole) for it in self.selectedItems())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            pages = self.selected_pages()
            if pages:
                self.deletePagesRequested.emit(pages)
            return
        super().keyPressEvent(event)
