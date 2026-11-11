from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap, QColor
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
        """Lists every page at once with a blank icon, then draws the real
        thumbnails one by one in the background (event loop stays free, so
        a big set of plans opens without freezing the window)."""
        self._suppress_move_signal = True
        self.clear()
        blank = QPixmap(80, 110)
        blank.fill(QColor(255, 255, 255))
        for i in range(doc.page_count):
            item = QListWidgetItem(QIcon(blank), str(i + 1))
            item.setData(Qt.UserRole, i)
            item.setTextAlignment(Qt.AlignHCenter)
            self.addItem(item)
        self._suppress_move_signal = False
        self._thumb_doc = doc
        self._thumb_next = 0
        self._thumb_gen = getattr(self, "_thumb_gen", 0) + 1
        gen = self._thumb_gen
        QTimer.singleShot(0, lambda: self._render_next_thumb(gen))

    def _render_next_thumb(self, gen: int):
        if gen != self._thumb_gen or self._thumb_next >= self.count():
            return
        i = self._thumb_next
        self._thumb_next += 1
        try:
            pix = self._thumb_doc.thumbnail(i)
            item = self.item(i)
            if item is not None:
                item.setIcon(QIcon(pixmap_to_qpixmap(pix)))
        except Exception:
            return      # document closed meanwhile
        QTimer.singleShot(0, lambda: self._render_next_thumb(gen))

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
