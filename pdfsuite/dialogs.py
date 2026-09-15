from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QBuffer, QIODevice
from PySide6.QtGui import QPainter, QPen, QImage, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QDoubleSpinBox,
    QPushButton, QWidget, QDialogButtonBox, QInputDialog, QLineEdit, QComboBox,
)


def ask_password(parent, filename: str) -> str | None:
    text, ok = QInputDialog.getText(
        parent, "Document protégé",
        f"« {filename} » est protégé par mot de passe :",
        QLineEdit.Password,
    )
    return text if ok else None


def parse_page_ranges(spec: str, max_pages: int) -> list[int] | None:
    """'1-3,5,8-9' (1-based, inclusive) -> sorted unique 0-based indices."""
    spec = spec.strip()
    if not spec:
        return None
    out: set[int] = set()
    try:
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                a, b = int(a), int(b)
                for p in range(min(a, b), max(a, b) + 1):
                    if 1 <= p <= max_pages:
                        out.add(p - 1)
            else:
                p = int(part)
                if 1 <= p <= max_pages:
                    out.add(p - 1)
    except ValueError:
        return None
    return sorted(out) if out else None


def ask_page_ranges(parent, title: str, max_pages: int) -> list[int] | None:
    text, ok = QInputDialog.getText(
        parent, title,
        f"Pages (1 à {max_pages}), ex. 1-3,5,8-9 :",
    )
    if not ok:
        return None
    return parse_page_ranges(text, max_pages)


class TextEditDialog(QDialog):
    def __init__(self, parent, current_text: str, fontsize: float):
        super().__init__(parent)
        self.setWindowTitle("Modifier le texte")
        self.resize(420, 260)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Texte :"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(current_text)
        layout.addWidget(self.text_edit)

        row = QHBoxLayout()
        row.addWidget(QLabel("Taille de police :"))
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(4, 96)
        self.size_spin.setValue(fontsize)
        row.addWidget(self.size_spin)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, float]:
        return self.text_edit.toPlainText(), self.size_spin.value()


class CalibrationDialog(QDialog):
    """Asks the real-world length of a line just drawn, to derive the
    plan's scale. Shown once per document; the scale is then reused."""

    UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Échelle du plan")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Quelle est la longueur réelle représentée par la ligne\n"
            "que vous venez de tracer ?"
        ))
        row = QHBoxLayout()
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(0.001, 100000)
        self.value_spin.setDecimals(3)
        self.value_spin.setValue(1.0)
        row.addWidget(self.value_spin)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(list(self.UNITS.keys()))
        self.unit_combo.setCurrentText("m")
        row.addWidget(self.unit_combo)
        layout.addLayout(row)
        layout.addWidget(QLabel(
            "Cette échelle sera réutilisée automatiquement pour toutes les\n"
            "prochaines mesures de ce document."
        ))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def real_length_meters(self) -> float:
        return self.value_spin.value() * self.UNITS[self.unit_combo.currentText()]


class SignatureCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(420, 180)
        self.setAttribute(Qt.WA_StaticContents)
        self._image = QImage(self.size(), QImage.Format_ARGB32)
        self._image.fill(Qt.transparent)
        self._last_point = None
        self._has_ink = False

    def clear(self):
        self._image.fill(Qt.transparent)
        self._has_ink = False
        self.update()

    def is_empty(self) -> bool:
        return not self._has_ink

    def mousePressEvent(self, event):
        self._last_point = event.position().toPoint()
        self._has_ink = True

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._last_point is not None:
            new_point = event.position().toPoint()
            painter = QPainter(self._image)
            pen = QPen(QColor(20, 20, 20), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(self._last_point, new_point)
            painter.end()
            self._last_point = new_point
            self.update()

    def mouseReleaseEvent(self, event):
        self._last_point = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(255, 255, 255))
        painter.drawImage(0, 0, self._image)
        painter.setPen(QPen(QColor(180, 180, 180)))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def to_png_bytes(self) -> bytes:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        self._image.save(buf, "PNG")
        return bytes(buf.data())


class SignatureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Signature")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dessinez votre signature :"))
        self.canvas = SignatureCanvas()
        layout.addWidget(self.canvas)

        row = QHBoxLayout()
        clear_btn = QPushButton("Effacer")
        clear_btn.clicked.connect(self.canvas.clear)
        row.addWidget(clear_btn)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def png_bytes(self) -> bytes:
        return self.canvas.to_png_bytes()
