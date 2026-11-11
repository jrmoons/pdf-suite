"""Properties bar for the measurement tools, shown under the ribbon.

    Échelle : [1] [cm] sur le plan = [0,5] [m] en réel   [1:50 ▾]
    Précision [0,01 ▾]   Couleur ■   [Calibrer…]   ⚠ message

The real-side unit is also the unit of every measurement label. Scale,
unit and precision are stored in the PDF (see PdfDocument)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QDoubleSpinBox, QComboBox, QPushButton,
    QColorDialog, QFrame,
)

from .dialogs import SCALE_PRESETS
from .settings import app_settings

UNITS = ["mm", "cm", "m"]
UNIT_M = {"mm": 0.001, "cm": 0.01, "m": 1.0}
PRECISIONS = [("1", 0), ("0,1", 1), ("0,01", 2), ("0,001", 3)]


class MeasureBar(QFrame):
    applied = Signal()              # scale / unit / precision changed
    colorChanged = Signal(tuple)
    calibrateRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MeasureBar")
        self.doc = None
        self.color = (0.0, 0.45, 0.85)
        self.settings = app_settings()
        self._loading = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)

        title = QLabel("<b>Mesure</b>")
        lay.addWidget(title)
        lay.addSpacing(8)
        lay.addWidget(QLabel("Échelle :"))
        self.paper = QDoubleSpinBox()
        self.paper.setDecimals(2)
        self.paper.setRange(0.01, 100000)
        self.paper.setValue(1)
        self.paper.setToolTip("Longueur mesurée sur le plan (papier)")
        self.paper_unit = QComboBox()
        self.paper_unit.addItems(UNITS)
        self.paper_unit.setCurrentText("cm")
        lay.addWidget(self.paper)
        lay.addWidget(self.paper_unit)
        lay.addWidget(QLabel("sur le plan  ="))
        self.real = QDoubleSpinBox()
        self.real.setDecimals(3)
        self.real.setRange(0.0, 1e9)
        self.real.setSpecialValueText("?")
        self.real.setToolTip("Longueur réelle correspondante")
        self.real_unit = QComboBox()
        self.real_unit.addItems(UNITS)
        self.real_unit.setCurrentText("m")
        self.real_unit.setToolTip("Unité réelle — c'est aussi l'unité affichée sur les mesures")
        lay.addWidget(self.real)
        lay.addWidget(self.real_unit)
        lay.addWidget(QLabel("en réel"))

        self.presets = QComboBox()
        self.presets.addItem("Préréglages…")
        self.presets.addItems([f"1:{n}" for n in SCALE_PRESETS])
        self.presets.setToolTip("Échelles courantes")
        lay.addWidget(self.presets)

        lay.addSpacing(10)
        lay.addWidget(QLabel("Précision :"))
        self.precision = QComboBox()
        for text, _d in PRECISIONS:
            self.precision.addItem(text)
        self.precision.setCurrentIndex(2)
        lay.addWidget(self.precision)

        lay.addSpacing(10)
        self.color_btn = QPushButton("Couleur")
        self.color_btn.setToolTip("Couleur des nouvelles mesures")
        lay.addWidget(self.color_btn)
        from PySide6.QtWidgets import QCheckBox
        self.auto_cotes = QCheckBox("Cotes auto")
        self.auto_cotes.setToolTip("Pièce auto / Périmètre / Surface : poser aussi les cotes de "
                                   "chaque mur, avec les portes et fenêtres")
        self.auto_cotes.setChecked(bool(self.settings.value("auto_cotes", True, type=bool)))
        lay.addWidget(self.auto_cotes)
        self.calib_btn = QPushButton("Calibrer…")
        self.calib_btn.setToolTip("Tracer une ligne sur une cote connue du plan pour en déduire l'échelle")
        lay.addWidget(self.calib_btn)

        self.warning = QLabel("")
        lay.addSpacing(8)
        lay.addWidget(self.warning)
        lay.addStretch()

        self.paper.editingFinished.connect(self._apply_scale)
        self.real.editingFinished.connect(self._apply_scale)
        self.paper_unit.activated.connect(lambda _i: self._apply_scale())
        self.real_unit.activated.connect(lambda _i: self._on_unit_changed())
        self.presets.activated.connect(self._on_preset)
        self.precision.activated.connect(self._on_precision)
        self.color_btn.clicked.connect(self._pick_color)
        self.calib_btn.clicked.connect(self.calibrateRequested.emit)
        self._update_color_btn()

    # -- document binding --------------------------------------------------
    def set_document(self, doc):
        self.doc = doc
        self.setEnabled(doc is not None)
        if doc is None:
            return
        self.apply_defaults(doc)
        self.refresh()

    DEFAULT_RATIO = 50      # 1 cm sur le plan = 0,5 m en réel

    def apply_defaults(self, doc):
        """Documents without stored scale get 1:50 (not written into the
        PDF until changed); unit / precision default to the last used."""
        if not doc.scale_points_per_meter:
            from .pdf_document import POINTS_PER_PAPER_METER
            doc._scale = POINTS_PER_PAPER_METER / self.DEFAULT_RATIO
            doc.scale_is_default = True
        if not doc.unit_from_file:
            doc._unit = self.settings.value("measure_unit", "m")
        if getattr(doc, "_decimals", None) is None:
            _ = doc.decimals
            if doc._decimals is None:
                doc._decimals = int(self.settings.value("measure_decimals", 2))

    def refresh(self):
        doc = self.doc
        if doc is None:
            return
        self._loading = True
        self.real_unit.setCurrentText(doc.unit)
        self.precision.setCurrentIndex(max(0, min(3, doc.decimals)))
        ratio = doc.ratio()
        if ratio:
            paper_m = self.paper.value() * UNIT_M[self.paper_unit.currentText()]
            self.real.setValue(paper_m * ratio / UNIT_M[doc.unit])
            default = " (par défaut)" if getattr(doc, "scale_is_default", False) else ""
            self.warning.setText(
                f"<span style='color:#2e7d32'>✔ 1:{ratio:g}{default}</span>".replace(".", ","))
        else:
            self.real.setValue(0)
            self.warning.setText(
                "<span style='color:#e65100'><b>⚠ Saisissez l'échelle du plan</b></span>")
        self._loading = False

    def flash_warning(self):
        self.real.setFocus()
        self.real.selectAll()
        self.setStyleSheet("#MeasureBar { border: 2px solid #e65100; border-radius: 4px; }")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.setStyleSheet(""))

    # -- edits -------------------------------------------------------------
    def _apply_scale(self):
        if self._loading or self.doc is None:
            return
        paper, real = self.paper.value(), self.real.value()
        if paper <= 0 or real <= 0:
            return
        with self.doc.op("Échelle"):
            self._apply_scale_inner(paper, real)

    def _apply_scale_inner(self, paper, real):
        self.doc.unit = self.real_unit.currentText()
        self.doc.set_paper_real_scale(paper, self.paper_unit.currentText(),
                                      real, self.real_unit.currentText())
        self.doc.scale_is_default = False
        self._done()

    def _on_unit_changed(self):
        if self.doc is None:
            return
        with self.doc.op("Unité"):
            self._on_unit_changed_inner()

    def _on_unit_changed_inner(self):
        unit = self.real_unit.currentText()
        if self.doc.ratio():
            # same scale, values re-expressed in the new unit
            self.doc.unit = unit
            self.settings.setValue("measure_unit", unit)
            self._done()
        else:
            self.doc.unit = unit
            self.settings.setValue("measure_unit", unit)
            self.refresh()

    def _on_preset(self, index: int):
        if index <= 0 or self.doc is None:
            return
        n = SCALE_PRESETS[index - 1]
        self.presets.setCurrentIndex(0)
        with self.doc.op("Échelle"):
            self.doc.unit = self.real_unit.currentText()
            self.doc.set_ratio_scale(n)
            self.doc.scale_is_default = False
            self._done()

    def _on_precision(self, index: int):
        if self.doc is None:
            return
        with self.doc.op("Précision"):
            self.doc.decimals = PRECISIONS[index][1]
            self.settings.setValue("measure_decimals", PRECISIONS[index][1])
            self._done()

    def _done(self):
        self.settings.setValue("measure_unit", self.doc.unit)
        self.doc.relabel_measurements()
        self.refresh()
        self.applied.emit()

    def _pick_color(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.color), self, "Couleur des mesures")
        if c.isValid():
            self.color = (c.redF(), c.greenF(), c.blueF())
            self._update_color_btn()
            self.colorChanged.emit(self.color)

    def _update_color_btn(self):
        c = QColor.fromRgbF(*self.color)
        self.color_btn.setStyleSheet(
            f"QPushButton {{ border-left: 14px solid {c.name()}; padding: 3px 8px; }}")
