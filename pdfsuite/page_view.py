"""Page view.

Scene units are PDF points (``scene_scale`` = 1): the scene is built once
per document structure, and **zooming only changes the view transform** -
no rebuild, no full-page re-render, so zoom in / out is instant even on
huge plans. Each page shows a capped-resolution *base* image stretched to
its size, plus a sharp *detail* tile of the visible area, rendered at the
exact screen resolution once scrolling/zooming pauses.
"""
from __future__ import annotations

import datetime
import getpass
import math

import pymupdf
from PySide6.QtCore import Qt, QPointF, QRectF, QRect, QSize, QSizeF, QTimer, Signal
from PySide6.QtGui import (
    QImage, QPixmap, QPen, QColor, QPainterPath, QBrush, QPainter, QTransform, QFont,
)
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPathItem, QInputDialog,
    QGraphicsProxyWidget, QLineEdit, QCheckBox, QComboBox, QDialog, QLabel,
    QApplication, QWidget,
)

from .tools import Tool, DRAG_TOOLS, POLY_TOOLS
from .pdf_document import PdfDocument, STAMP_COLORS
from .dialogs import CalibrationDialog
from . import annotation_items as ai

GAP = 14
BASE_MAX_PX = 2600        # longest side of a page's base image
DETAIL_DELAY_MS = 120     # pause before the sharp tile is rendered
MIN_ZOOM, MAX_ZOOM = 0.05, 16.0
RULER = 22                # ruler thickness in pixels
MEASURE_TOOLS = {Tool.MEASURE_LINE, Tool.MEASURE_PERIMETER, Tool.MEASURE_AREA, Tool.DIMENSION,
                 Tool.ROOM}
COTE_OFFSET_M = (0.30, 0.65)    # automatic cotes: chain, then overall length
MIN_COTE_SIDE_M = 0.30          # no automatic cote on shorter sides
MIN_CHAIN_M = 0.15              # pieces of a cote chain shorter than this are not drawn


def _rect_to_quad(r: pymupdf.Rect) -> pymupdf.Quad:
    return pymupdf.Quad(r.tl, r.tr, r.bl, r.br)


def pixmap_to_qpixmap(pix: pymupdf.Pixmap) -> QPixmap:
    fmt = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
    return QPixmap.fromImage(img)


class PageItem(QGraphicsItem):
    """One page, in PDF points. Draws base + detail images, never re-renders
    by itself."""

    def __init__(self, page_no: int, width: float, height: float):
        super().__init__()
        self.page_no = page_no
        self.size = QSizeF(width, height)
        self.base: QPixmap | None = None
        self.base_zoom = 0.0
        self.detail: QPixmap | None = None
        self.detail_rect = QRectF()    # local points covered by the detail tile
        self.detail_zoom = 0.0
        self.annot_items: list = []

    @property
    def rendered(self) -> bool:
        return self.base is not None

    def page_rect(self) -> QRectF:
        return QRectF(self.pos(), self.size)

    def boundingRect(self) -> QRectF:
        return QRectF(QPointF(0, 0), self.size)

    def paint(self, painter, option, widget=None):
        r = self.boundingRect()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self.base is None:
            painter.fillRect(r, QColor(255, 255, 255))
        else:
            painter.drawPixmap(r, self.base, QRectF(self.base.rect()))
        if self.detail is not None and not self.detail_rect.isEmpty():
            painter.drawPixmap(self.detail_rect, self.detail, QRectF(self.detail.rect()))


# -- rulers -------------------------------------------------------------------
def _nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if m * exp >= raw:
            return m * exp
    return 10 * exp


class Ruler(QWidget):
    """Graduated ruler in real units (paper cm when no scale is set),
    origin at the top-left corner of the current page."""

    def __init__(self, view: "PdfGraphicsView", horizontal: bool):
        super().__init__(view)
        self.view = view
        self.horizontal = horizontal
        self.cursor_px: float | None = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def paintEvent(self, event):
        v = self.view
        p = QPainter(self)
        bg = v.palette().window().color()
        fg = v.palette().windowText().color()
        p.fillRect(self.rect(), bg)
        p.setPen(QPen(fg.darker(130) if bg.lightness() > 128 else fg.lighter(80)))
        item = v.page_items[v.current_page()] if v.page_items else None
        if item is None:
            return
        # units per PDF point and label of the unit
        upp, unit = v.units_per_point()
        zoom = v.zoom
        origin_vp = v.mapFromScene(item.pos())
        origin = origin_vp.x() if self.horizontal else origin_vp.y()
        # the ruler starts exactly where the viewport starts
        length = self.width() if self.horizontal else self.height()
        px_per_unit = zoom / upp
        major = _nice_step(60 / px_per_unit)
        lead = round(major / 10 ** math.floor(math.log10(major)))
        minor = major / (4 if lead == 2 else 5)
        f = QFont()
        f.setPixelSize(10)
        p.setFont(f)
        k0 = math.floor((0 - origin) / px_per_unit / minor) - 1
        k1 = math.ceil((length - origin) / px_per_unit / minor) + 1
        if k1 - k0 > 3000:
            return
        for k in range(k0, k1 + 1):
            u = k * minor
            pos = origin + u * px_per_unit
            if pos < 0 or pos > length:
                continue
            is_major = abs(u / major - round(u / major)) < 1e-6
            tick = RULER * (0.6 if is_major else 0.25)
            if self.horizontal:
                p.drawLine(QPointF(pos, RULER), QPointF(pos, RULER - tick))
                if is_major:
                    p.drawText(QPointF(pos + 2, 10), _fmt_tick(u))
            else:
                p.drawLine(QPointF(RULER, pos), QPointF(RULER - tick, pos))
                if is_major:
                    p.save()
                    p.translate(10, pos - 2)
                    p.rotate(-90)
                    p.drawText(QPointF(0, 0), _fmt_tick(u))
                    p.restore()
        if self.cursor_px is not None:
            p.setPen(QPen(QColor(220, 40, 40), 1))
            c = self.cursor_px
            if self.horizontal:
                p.drawLine(QPointF(c, 0), QPointF(c, RULER))
            else:
                p.drawLine(QPointF(0, c), QPointF(RULER, c))
        p.setPen(QPen(fg.darker(150)))
        if self.horizontal:
            p.drawLine(0, RULER - 1, self.width(), RULER - 1)
        else:
            p.drawLine(RULER - 1, 0, RULER - 1, self.height())


def _fmt_tick(u: float) -> str:
    if abs(u - round(u)) < 1e-6:
        return str(int(round(u)))
    return f"{u:g}".replace(".", ",")


class MeasureInfo(QLabel):
    """Live measurement panel (distance, angle, ΔX, ΔY, scale, precision)."""

    def __init__(self, view):
        super().__init__(view.viewport())
        self.setTextFormat(Qt.RichText)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "QLabel { background: rgba(250,250,252,235); color: #1c1c1e;"
            " border: 1px solid #b9bec7; border-radius: 6px; padding: 6px 10px; }")
        self.hide()


class PdfGraphicsView(QGraphicsView):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    documentModified = Signal()
    statusMessage = Signal(str)
    requestTextEdit = Signal(int, object, str, float)
    requestSignaturePlacement = Signal(int, object)
    requestSelectTool = Signal()      # Échap : retour à l'outil Sélection
    cursorInfo = Signal(str)          # coordonnées sous le curseur
    scaleRequired = Signal()          # mesure tentée sans échelle
    scaleCalibrated = Signal()
    filesDropped = Signal(list)       # PDF glissés sur la vue

    scene_scale = 1.0                 # scene units = PDF points

    def __init__(self, document: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = document
        self.zoom = 1.33
        self.tool = Tool.SELECT
        self.current_color = (0.9, 0.1, 0.1)
        self.measure_color = (0.0, 0.45, 0.85)
        self.page_items: list[PageItem] = []

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.setBackgroundBrush(QBrush(QColor(60, 63, 68)))
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self._dragging = False
        self._drag_page = -1
        self._drag_start_pt = None
        self._drag_points: list = []
        self._preview_item = None
        self.form_mode = False
        self._form_proxies: list = []

        self._poly_page = -1
        self._poly_points: list = []
        self._poly_preview_item = None

        self.auto_cotes = True            # cotes + ouvertures automatiques sur les contours
        self.show_grid = False
        self.snap_to_grid = True          # « Aimanter » : points du plan (+ grille si affichée)
        self._snap_marker = None
        self._last_snap = None
        self.invert_colors = False
        self.stamp_label = "APPROUVÉ"
        self._loupe: QLabel | None = None
        self.loupe_enabled = False
        self.calibrating = False

        # rulers in the viewport margins
        self.rulers_visible = True
        self._hruler = Ruler(self, True)
        self._vruler = Ruler(self, False)
        self._measure_info = MeasureInfo(self)

        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.timeout.connect(self._render_pending)
        self._mid_pan = None              # middle-button panning state
        self._dim = None                  # dimension (cote) being placed
        self._text_edit_info = {}
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(self._on_scrolled)
        self.setTransform(QTransform.fromScale(self.zoom, self.zoom))
        self.set_rulers(True)
        self.build_scene()

    # ------------------------------------------------------------------
    def set_tool(self, tool: Tool):
        if self.tool in POLY_TOOLS and tool != self.tool:
            self._cancel_polygon()
        if tool != Tool.DIMENSION:
            self._cancel_dimension()
        if tool not in MEASURE_TOOLS:
            self.calibrating = False
        self.tool = tool
        self.setDragMode(
            QGraphicsView.ScrollHandDrag if tool == Tool.PAN else QGraphicsView.NoDrag
        )
        self._show_measure_info(None)
        if tool == Tool.ROOM:
            QTimer.singleShot(30, self._prepare_room)

    def _prepare_room(self):
        """Pièce auto: read the walls of the page once (≈1-2 s on a big
        plan) when the tool is chosen, so every click is then instant."""
        if self.tool != Tool.ROOM or not self.page_items or getattr(self, "_closed", False):
            return
        from . import room_detect as rd
        if not self.doc.scale_points_per_meter:
            return
        try:
            if not rd.has_wall_layers(self.doc) or rd.is_prepared(self.doc, self.current_page()):
                return
            self.statusMessage.emit("Pièce auto : lecture des murs du plan…")
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                rd.prepare(self.doc, self.current_page())
            finally:
                QApplication.restoreOverrideCursor()
            self.statusMessage.emit("Pièce auto : cliquez dans une pièce.")
        except Exception:
            pass

    def set_color(self, rgb: tuple[float, float, float]):
        self.current_color = rgb

    def set_measure_color(self, rgb):
        self.measure_color = rgb

    def apply_theme(self, surround_color: QColor):
        self.setBackgroundBrush(QBrush(surround_color))
        self._hruler.update()
        self._vruler.update()

    # -- hardware acceleration ---------------------------------------------
    def set_gpu(self, enabled: bool) -> bool:
        """Draw the view through the graphics card (OpenGL). Returns
        whether it is active. Falls back silently to software drawing."""
        if enabled == isinstance(self.viewport(), _gl_widget_class()):
            return enabled
        if enabled:
            cls = _gl_widget_class()
            if cls is None or QApplication.platformName() in ("offscreen", "minimal"):
                return False
            try:
                vp = cls()
                fmt = vp.format()
                fmt.setSamples(4)
                vp.setFormat(fmt)
                self.setViewport(vp)
                self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
            except Exception:
                return False
        else:
            self.setViewport(QWidget())
            self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.viewport().setMouseTracking(True)
        self.viewport().setAcceptDrops(True)
        # the old viewport was deleted together with its child widgets
        self._measure_info = MeasureInfo(self)
        self._place_rulers()
        self._hruler.raise_()
        self._vruler.raise_()
        return enabled

    # -- drag & drop of PDF files ----------------------------------------
    @staticmethod
    def _pdf_paths(mime) -> list[str]:
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(".pdf")]

    def dragEnterEvent(self, event):
        if self._pdf_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._pdf_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._pdf_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
        else:
            super().dropEvent(event)

    # -- rulers ---------------------------------------------------------
    def set_rulers(self, visible: bool):
        self.rulers_visible = visible
        m = RULER if visible else 0
        self.setViewportMargins(m, m, 0, 0)
        self._hruler.setVisible(visible)
        self._vruler.setVisible(visible)
        self._place_rulers()

    def _place_rulers(self):
        cr = self.contentsRect()
        self._hruler.setGeometry(cr.left() + RULER, cr.top(), cr.width() - RULER, RULER)
        self._vruler.setGeometry(cr.left(), cr.top() + RULER, RULER, cr.height() - RULER)

    def units_per_point(self) -> tuple[float, str]:
        """Ruler/cursor unit: the real unit when the scale is known,
        otherwise centimetres of paper."""
        if self.doc.scale_points_per_meter:
            return self.doc.to_unit(1.0), self.doc.unit
        return 2.54 / 72, "cm"

    def _update_rulers(self):
        if self.rulers_visible:
            self._hruler.update()
            self._vruler.update()

    # -- zoom (view transform only: instant) ------------------------------
    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            if angle:
                factor = 1.2 ** (angle / 120)
                self.set_zoom(self.zoom * factor, anchor=event.position().toPoint())
            event.accept()
            return
        super().wheelEvent(event)

    def set_zoom(self, zoom: float, under_mouse: bool = False, anchor=None):
        """Zoom keeping the point under ``anchor`` (viewport position; the
        mouse when ``under_mouse``, else the centre) exactly where it is —
        zooming in AND out stays on the place you are looking at."""
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(zoom - self.zoom) < 1e-9:
            return
        vp_rect = self.viewport().rect()
        if anchor is None and under_mouse:
            from PySide6.QtGui import QCursor
            anchor = self.viewport().mapFromGlobal(QCursor.pos())
        if anchor is None or not vp_rect.contains(anchor):
            anchor = vp_rect.center()
        scene_pt = self.mapToScene(anchor)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.zoom = zoom
        self._update_scene_rect()
        self.setTransform(QTransform.fromScale(zoom, zoom))
        delta = self.mapFromScene(scene_pt) - anchor
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())
        self.zoomChanged.emit(zoom)
        self._update_rulers()
        self._schedule_detail()

    def fit_width(self):
        if not self.page_items:
            return
        w = max(it.size.width() for it in self.page_items)
        cur = self.current_page()
        self.set_zoom((self.viewport().width() - 24) / max(w, 1))
        self.goto_page(cur)

    def fit_page(self):
        if not self.page_items:
            return
        it = self.page_items[self.current_page()]
        vw, vh = self.viewport().width() - 24, self.viewport().height() - 24
        self.set_zoom(min(vw / it.size.width(), vh / it.size.height()))
        self.centerOn(it.page_rect().center())

    # ------------------------------------------------------------------
    def build_scene(self, keep_page: int | None = None):
        self._scene.clear()
        self.page_items = []
        sizes = [self.doc.visual_size(i) for i in range(self.doc.page_count)]
        max_w = max((w for w, _ in sizes), default=0.0)
        y = GAP
        for i, (w, h) in enumerate(sizes):
            item = PageItem(i, w, h)
            item.setPos((max_w - w) / 2 + GAP, y)
            item.setZValue(0)
            self._scene.addItem(item)
            self.page_items.append(item)
            self._rebuild_page_annotations(item)
            y += h + GAP
        self._content_rect = QRectF(0, 0, max_w + 2 * GAP, y)
        self._update_scene_rect()
        self.goto_page(keep_page if keep_page is not None and 0 <= keep_page < len(self.page_items) else 0)
        self._form_proxies = []
        self._snap_marker = None
        if self.form_mode:
            self._add_form_widgets()
        self._update_visible()
        QTimer.singleShot(400, self._prepare_snap)

    def _update_scene_rect(self):
        """Pages + a margin of one screen on each side: lets the view keep
        the point under the mouse fixed when zooming out near an edge."""
        r = getattr(self, "_content_rect", None)
        if r is None:
            return
        mx = self.viewport().width() / self.zoom
        my = self.viewport().height() / self.zoom
        self._scene.setSceneRect(r.adjusted(-mx, -my, mx, my))

    # -- vector annotation layer ------------------------------------------
    def _rebuild_page_annotations(self, item: PageItem):
        for obj in item.annot_items:
            if obj.scene() is not None:
                self._scene.removeItem(obj)
        item.annot_items = []
        page = self.doc.page(item.page_no)
        for annot in self.doc.annotations(item.page_no):
            qitems = ai.build_item_for_annot(self, page, item.page_no, annot)
            for qitem in qitems:
                qitem.setParentItem(item)
                item.annot_items.append(qitem)
                if hasattr(qitem, "make_handles"):
                    item.annot_items.extend(qitem.make_handles(item))
        if not self.form_mode:
            for w in self.doc.widgets(item.page_no):
                qitem = ai.build_widget_display_item(self, page, item.page_no, w)
                qitem.setParentItem(item)
                item.annot_items.append(qitem)

    def remove_annotation_item(self, page_no: int, qitem):
        item = self.page_items[page_no] if 0 <= page_no < len(self.page_items) else None
        if qitem.scene() is not None:
            self._scene.removeItem(qitem)
        if item is not None and qitem in item.annot_items:
            item.annot_items.remove(qitem)

    def delete_selected(self) -> bool:
        """Delete key: remove every selected annotation (shapes, measures,
        cotes, stamps, notes, highlights...)."""
        targets = [it for it in self._scene.selectedItems() if hasattr(it, "annot")]
        if not targets:
            return False
        for it in targets:
            if getattr(it, "locked", False):
                continue
            if it.annot is not None:
                self.doc.delete_annot(it.page_no, it.annot)
            self.remove_annotation_item(it.page_no, it)
            for h in getattr(it, "handles", []):
                if h.scene() is not None:
                    self._scene.removeItem(h)
                self.remove_annotation_item(it.page_no, h)
        self.documentModified.emit()
        return True

    def rebuild_annotations(self):
        for item in self.page_items:
            self._rebuild_page_annotations(item)

    def _refresh_labels(self):
        """Measure labels keep a constant on-screen size: resize them after
        a zoom change (only for visible pages)."""
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        for item in self.page_items:
            if not item.page_rect().intersects(visible):
                continue
            for obj in item.annot_items:
                if hasattr(obj, "zoom_changed"):
                    obj.zoom_changed()

    # -- form fields --------------------------------------------------
    def set_form_mode(self, enabled: bool):
        self.form_mode = enabled
        self._clear_form_widgets()
        for item in self.page_items:
            self._rebuild_page_annotations(item)
        if enabled:
            self._add_form_widgets()

    def _clear_form_widgets(self):
        for proxy in self._form_proxies:
            if proxy.scene() is not None:
                self._scene.removeItem(proxy)
        self._form_proxies = []

    def _add_form_widgets(self):
        self._clear_form_widgets()
        for item in self.page_items:
            for w in self.doc.widgets(item.page_no):
                editor = self._make_widget_editor(w)
                if editor is None:
                    continue
                r = pymupdf.Rect(w.rect)
                f = editor.font()
                f.setPixelSize(max(5, int(r.height * 0.62)))
                editor.setFont(f)
                editor.setStyleSheet("padding: 0px; margin: 0px;")
                proxy = QGraphicsProxyWidget(item)
                proxy.setWidget(editor)
                proxy.setMinimumSize(1, 1)
                editor.setMinimumSize(1, 1)
                proxy.setPos(r.x0, r.y0)
                proxy.resize(r.width, r.height)
                proxy.setZValue(5)
                self._form_proxies.append(proxy)

    def _make_widget_editor(self, w):
        t = w.field_type_string
        if t == "Text":
            editor = QLineEdit(w.field_value or "")
            editor.editingFinished.connect(
                lambda w=w, e=editor: self._commit_widget(w, e.text())
            )
            return editor
        if t == "CheckBox":
            editor = QCheckBox()
            editor.setChecked(bool(w.field_value and w.field_value != "Off"))
            editor.toggled.connect(lambda checked, w=w: self._commit_widget(w, checked))
            return editor
        if t in ("ComboBox", "ListBox"):
            editor = QComboBox()
            values = w.choice_values or []
            editor.addItems(values)
            if w.field_value in values:
                editor.setCurrentText(w.field_value)
            editor.currentTextChanged.connect(
                lambda text, w=w: self._commit_widget(w, text)
            )
            return editor
        return None

    def _commit_widget(self, widget_obj, value):
        self.doc.set_widget_value(widget_obj, value)
        self.documentModified.emit()

    # -- navigation ---------------------------------------------------------
    def current_page(self) -> int:
        center_y = self.mapToScene(self.viewport().rect().center()).y()
        top = self.mapToScene(0, 0).y()
        probe = top + (center_y - top) * 0.3
        for item in self.page_items:
            if item.y() + item.size.height() > probe:
                return item.page_no
        return max(0, len(self.page_items) - 1)

    def goto_page(self, n: int):
        """Page top at the top of the view, page centred horizontally (or
        its left edge at the left when it is wider than the view)."""
        if 0 <= n < len(self.page_items):
            item = self.page_items[n]
            vw = self.viewport().width() / self.zoom
            if item.size.width() <= vw:
                x = item.x() + item.size.width() / 2 - vw / 2
            else:
                x = item.x() - GAP / 2
            vp = self.mapFromScene(QPointF(x, item.y() - GAP / 2))
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + vp.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + vp.y())

    # -- rendering ----------------------------------------------------------
    def _render_zoom(self) -> float:
        return self.zoom * self.devicePixelRatioF()

    def _base_zoom_for(self, n: int) -> float:
        w, h = self.doc.visual_size(n)
        return min(self._render_zoom(), BASE_MAX_PX / max(w, h, 1))

    def _to_qpixmap(self, pix) -> QPixmap:
        qpix = pixmap_to_qpixmap(pix)
        if self.invert_colors:
            img = qpix.toImage()
            img.invertPixels()
            qpix = QPixmap.fromImage(img)
        return qpix

    def refresh_page(self, n: int, content_changed: bool = False):
        """Re-render one page (``content_changed``: text edit, signature)."""
        if 0 <= n < len(self.page_items):
            item = self.page_items[n]
            if content_changed:
                self.doc.invalidate_render(n)
            bz = self._base_zoom_for(n)
            item.base = self._to_qpixmap(self.doc.render_page(n, bz))
            item.base_zoom = bz
            item.detail = None
            item.detail_zoom = 0.0
            item.update()
            self._schedule_detail()

    def _schedule_detail(self):
        self._detail_timer.start(DETAIL_DELAY_MS)

    def shutdown(self):
        """Called before the document is closed: no more deferred work."""
        self._closed = True
        self._detail_timer.stop()
        self.set_loupe(False)

    def _render_pending(self):
        if getattr(self, "_closed", False) or self.doc.doc.is_closed:
            return
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        far = visible.adjusted(0, -3 * visible.height(), 0, 3 * visible.height())
        rz = self._render_zoom()
        for item in self.page_items:
            pr = item.page_rect()
            if not pr.intersects(visible):
                item.detail = None
                if not pr.intersects(far):
                    item.base = None
                continue
            want = self._base_zoom_for(item.page_no)
            if item.base is None or want > item.base_zoom * 1.15 or want < item.base_zoom / 3:
                item.base = self._to_qpixmap(self.doc.render_page(item.page_no, want))
                item.base_zoom = want
                item.update()
            if rz <= item.base_zoom * 1.05:
                if item.detail is not None:
                    item.detail = None
                    item.update()
                continue
            local = pr.intersected(visible).translated(-pr.topLeft())
            if local.isEmpty():
                continue
            if (item.detail is not None and abs(item.detail_zoom - rz) < 1e-6
                    and item.detail_rect.contains(local)):
                continue
            margin = 40 / self.zoom
            local = local.adjusted(-margin, -margin, margin, margin).intersected(
                QRectF(QPointF(0, 0), item.size))
            clip = pymupdf.Rect(local.left(), local.top(), local.right(), local.bottom())
            pix = self.doc.render_clip(item.page_no, rz, clip)
            item.detail = self._to_qpixmap(pix)
            item.detail_rect = QRectF(clip.x0, clip.y0, pix.width / rz, pix.height / rz)
            item.detail_zoom = rz
            item.update()
        self._refresh_labels()

    def refresh_all(self):
        """Pages changed (insert/delete/rotate...): rebuild, keep position."""
        center = self.mapToScene(self.viewport().rect().center())
        self.build_scene()
        self.centerOn(center)

    def _on_scrolled(self, _val):
        self._update_visible()
        self._update_rulers()
        self.pageChanged.emit(self.current_page())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scene_rect()
        self._place_rulers()
        self._update_visible()

    def _update_visible(self):
        if getattr(self, "_closed", False) or self.doc.doc.is_closed:
            return
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        buffer = visible.height() * 0.5
        expanded = visible.adjusted(0, -buffer, 0, buffer)
        for item in self.page_items:
            if not item.rendered and item.page_rect().intersects(expanded):
                self.refresh_page(item.page_no)
        self._schedule_detail()

    def _item_at_scene(self, scene_pos) -> PageItem | None:
        for item in self.page_items:
            if item.page_rect().contains(scene_pos):
                return item
        return None

    # -- grid / snapping ------------------------------------------------
    def grid_spacing(self) -> float:
        scale = self.doc.scale_points_per_meter
        if scale:
            steps = [s * scale for s in (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100)]
        else:
            steps = [mm * 72 / 25.4 for mm in (1, 2, 5, 10, 20, 50, 100)]
        for st in steps:
            if st * self.zoom >= 14:
                return st
        return steps[-1]

    def grid_description(self) -> str:
        st = self.grid_spacing()
        if self.doc.scale_points_per_meter:
            return f"Grille : {self.doc.fmt_length_pts(st)}"
        return f"Grille : {round(st * 25.4 / 72)} mm (papier)"

    def set_grid(self, show: bool):
        self.show_grid = show
        self.viewport().update()

    def drawForeground(self, painter, rect):
        if not self.show_grid:
            return
        step = self.grid_spacing()
        minor = QPen(QColor(47, 111, 237, 50))
        minor.setCosmetic(True)
        major = QPen(QColor(47, 111, 237, 110))
        major.setCosmetic(True)
        for item in self.page_items:
            r = item.page_rect().intersected(rect)
            if r.isEmpty():
                continue
            pr = item.page_rect()
            i0 = max(0, int((r.left() - pr.left()) / step))
            i1 = int((r.right() - pr.left()) / step) + 1
            for i in range(i0, i1 + 1):
                x = pr.left() + i * step
                painter.setPen(major if i % 5 == 0 else minor)
                painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            j0 = max(0, int((r.top() - pr.top()) / step))
            j1 = int((r.bottom() - pr.top()) / step) + 1
            for j in range(j0, j1 + 1):
                y = pr.top() + j * step
                painter.setPen(major if j % 5 == 0 else minor)
                painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))

    # -- coordinates --------------------------------------------------------
    SNAP_PX = 11          # snap radius on screen

    def snap_visual(self, page_no: int, x: float, y: float):
        """Snap a visual page point: drawing ends/corners/midpoints first,
        then the grid when it is shown. Returns (x, y, kind) — kind 0 = end
        or corner, 1 = midpoint, 2 = grid — or None."""
        if not self.snap_to_grid:
            return None
        hit = self.doc.snap_point(page_no, x, y, self.SNAP_PX / self.zoom)
        if hit is not None:
            return hit
        if self.show_grid:
            st = self.grid_spacing()
            return round(x / st) * st, round(y / st) * st, 2
        return None

    def _scene_to_visual(self, item: PageItem, scene_pos: QPointF, snap: bool = True) -> pymupdf.Point:
        local = scene_pos - item.pos()
        pt = pymupdf.Point(local.x(), local.y())
        shift = QApplication.keyboardModifiers() & Qt.ShiftModifier
        if snap and not shift and self.tool not in (Tool.PAN, Tool.SELECT):
            hit = self.snap_visual(item.page_no, pt.x, pt.y)
            if hit is not None:
                pt = pymupdf.Point(hit[0], hit[1])
        return pt

    def _update_snap_marker(self, viewport_pos):
        """Small marker showing where the next click will snap:
        square = end / corner, triangle = midpoint, cross = grid."""
        hit = None
        item = None
        if self.snap_to_grid and self.tool not in (Tool.PAN, Tool.SELECT) \
                and not (QApplication.keyboardModifiers() & Qt.ShiftModifier):
            scene_pos = self.mapToScene(viewport_pos)
            item = self._item_at_scene(scene_pos)
            if item is not None:
                local = scene_pos - item.pos()
                hit = self.snap_visual(item.page_no, local.x(), local.y())
        if hit is None:
            if self._snap_marker is not None:
                self._snap_marker.hide()
            return
        if self._snap_marker is None:
            self._snap_marker = QGraphicsPathItem()
            self._snap_marker.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            self._snap_marker.setZValue(50)
            pen = QPen(QColor(0, 170, 80), 2)
            pen.setCosmetic(True)
            self._snap_marker.setPen(pen)
            self._scene.addItem(self._snap_marker)
        path = QPainterPath()
        if hit[2] == 0:
            path.addRect(QRectF(-6, -6, 12, 12))
        elif hit[2] == 1:
            path.moveTo(0, -7); path.lineTo(6.5, 5); path.lineTo(-6.5, 5); path.closeSubpath()
        else:
            path.moveTo(-6, 0); path.lineTo(6, 0); path.moveTo(0, -6); path.lineTo(0, 6)
        self._snap_marker.setPath(path)
        self._snap_marker.setPos(item.pos() + QPointF(hit[0], hit[1]))
        self._snap_marker.show()

    def _prepare_snap(self):
        """Build the snap index of the visible page in the background
        (idle time), so the first hover does not stall."""
        if not self.snap_to_grid or not self.page_items or getattr(self, "_closed", False):
            return
        try:
            self.doc.snap_index(self.current_page())
        except Exception:
            pass

    def _scene_to_pdf_point(self, item: PageItem, scene_pos: QPointF) -> pymupdf.Point:
        page = self.doc.page(item.page_no)
        return self._scene_to_visual(item, scene_pos) * page.derotation_matrix

    def _pdf_to_scene(self, item: PageItem, pdf_pt) -> QPointF:
        page = self.doc.page(item.page_no)
        vis = pymupdf.Point(pdf_pt) * ~page.derotation_matrix
        return item.pos() + QPointF(vis.x, vis.y)

    def _constrain(self, item: PageItem, start_pdf, scene_pos: QPointF, modifiers) -> QPointF:
        """Shift: lock the segment to 0°, 45° or 90°."""
        if not (modifiers & Qt.ShiftModifier) or start_pdf is None:
            return scene_pos
        s = self._pdf_to_scene(item, start_pdf)
        dx, dy = scene_pos.x() - s.x(), scene_pos.y() - s.y()
        ang = math.atan2(dy, dx)
        snapped = round(ang / (math.pi / 4)) * (math.pi / 4)
        length = math.hypot(dx, dy) * math.cos(ang - snapped)
        return QPointF(s.x() + length * math.cos(snapped), s.y() + length * math.sin(snapped))

    # ------------------------------------------------------------------
    def _require_scale(self) -> bool:
        if self.doc.scale_points_per_meter or self.calibrating:
            return True
        self.scaleRequired.emit()
        self.statusMessage.emit(
            "Indiquez d'abord l'échelle du plan dans la barre « Mesure » (ou « Calibrer »).")
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._mid_pan = (event.pos(), self.horizontalScrollBar().value(),
                             self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if self.tool == Tool.DIMENSION:
            self._dimension_press(event)
            return
        if self.tool in POLY_TOOLS:
            if event.button() == Qt.LeftButton and not self._poly_points and not self._require_scale():
                return
            self._handle_polygon_click(event)
            return

        if self.tool in (Tool.PAN, Tool.SELECT):
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.pos())
        item = self._item_at_scene(scene_pos)
        if item is None or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        page_no = item.page_no
        pdf_pt = self._scene_to_pdf_point(item, scene_pos)

        if self.tool == Tool.NOTE:
            text, ok = QInputDialog.getMultiLineText(self, "Nouvelle note", "Texte :")
            if ok and text:
                self.doc.add_note(page_no, pdf_pt, text)
                self._rebuild_page_annotations(item)
                self.documentModified.emit()
            return

        if self.tool == Tool.FREETEXT:
            text, ok = QInputDialog.getMultiLineText(self, "Texte libre", "Texte :")
            if ok and text:
                rect = pymupdf.Rect(pdf_pt, pdf_pt + (200, 60))
                self.doc.add_freetext(page_no, rect, text, color=self.current_color)
                self._rebuild_page_annotations(item)
                self.documentModified.emit()
            return

        if self.tool == Tool.ERASER:
            if self.doc.delete_annot_at(page_no, pdf_pt):
                self._rebuild_page_annotations(item)
                self.documentModified.emit()
            return

        if self.tool == Tool.TEXTEDIT:
            self._start_text_edit(page_no, pdf_pt)
            return

        if self.tool == Tool.SIGNATURE:
            self.requestSignaturePlacement.emit(page_no, pdf_pt)
            return

        if self.tool == Tool.STAMP:
            self.place_stamp(page_no, pdf_pt)
            return

        if self.tool == Tool.ROOM:
            local = scene_pos - item.pos()
            self.auto_room(item, (local.x(), local.y()))
            return

        if self.tool in DRAG_TOOLS:
            if self.tool == Tool.MEASURE_LINE and not self._require_scale():
                return
            self._dragging = True
            self._drag_page = page_no
            self._drag_start_pt = pdf_pt
            self._drag_points = [pdf_pt]
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._mid_pan is not None:
            start, h, v = self._mid_pan
            d = event.pos() - start
            self.horizontalScrollBar().setValue(h - d.x())
            self.verticalScrollBar().setValue(v - d.y())
            event.accept()
            return
        self._emit_cursor_info(event.pos())
        if self.loupe_enabled:
            self._update_loupe(event.pos())
        self._update_snap_marker(event.pos())
        if self.tool == Tool.DIMENSION and self._dim is not None:
            self._dimension_move(event)
            return
        if self.tool in POLY_TOOLS and self._poly_points:
            item = self.page_items[self._poly_page]
            scene_pos = self._constrain(item, self._poly_points[-1],
                                        self.mapToScene(event.pos()), event.modifiers())
            self._update_poly_preview(extra_scene_pt=scene_pos)
            return
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        item = self.page_items[self._drag_page]
        scene_pos = self.mapToScene(event.pos())
        if self.tool in (Tool.MEASURE_LINE, Tool.LINE, Tool.ARROW):
            scene_pos = self._constrain(item, self._drag_start_pt, scene_pos, event.modifiers())
        pdf_pt = self._scene_to_pdf_point(item, scene_pos)
        self._drag_points.append(pdf_pt)
        self._update_preview(item, pdf_pt)
        if self.tool == Tool.MEASURE_LINE:
            self._show_measure_info([self._drag_start_pt, pdf_pt], "line", item)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._mid_pan is not None:
            self._mid_pan = None
            self.viewport().unsetCursor()
            event.accept()
            return
        if self.tool == Tool.DIMENSION:
            self._dimension_release(event)
            return
        if not self._dragging:
            super().mouseReleaseEvent(event)
            return
        self._dragging = False
        self._clear_preview()

        page_no = self._drag_page
        item = self.page_items[page_no]
        start = self._drag_start_pt
        end = self._drag_points[-1] if self._drag_points else start
        rect = pymupdf.Rect(start, end)
        rect.normalize()

        try:
            if self.tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
                if rect.width < 1 and rect.height < 1:
                    return
                words = self.doc.words_in_rect(page_no, rect)
                quads = [_rect_to_quad(w) for w in words] or [_rect_to_quad(rect)]
                if self.tool == Tool.HIGHLIGHT:
                    self.doc.add_highlight(page_no, quads, self.current_color)
                elif self.tool == Tool.UNDERLINE:
                    self.doc.add_underline(page_no, quads, self.current_color)
                else:
                    self.doc.add_strikeout(page_no, quads, self.current_color)

            elif self.tool == Tool.RECT:
                if rect.width < 2 or rect.height < 2:
                    return
                self.doc.add_rect(page_no, rect, self.current_color)

            elif self.tool == Tool.ELLIPSE:
                if rect.width < 2 or rect.height < 2:
                    return
                self.doc.add_ellipse(page_no, rect, self.current_color)

            elif self.tool == Tool.LINE:
                self.doc.add_line(page_no, start, end, self.current_color)

            elif self.tool == Tool.ARROW:
                if math.hypot(end.x - start.x, end.y - start.y) < 3:
                    return
                self.doc.add_arrow(page_no, start, end, self.current_color)

            elif self.tool == Tool.CLOUD:
                if rect.width < 6 or rect.height < 6:
                    return
                self.doc.add_cloud(page_no, rect, self.current_color)

            elif self.tool == Tool.CALLOUT:
                self._create_callout(page_no, start, end)

            elif self.tool == Tool.CAPTURE:
                if rect.width < 3 or rect.height < 3:
                    return
                self.capture_to_clipboard(item, start, end)
                return

            elif self.tool == Tool.INK:
                if len(self._drag_points) < 2:
                    return
                self.doc.add_ink(page_no, [self._drag_points], self.current_color)

            elif self.tool == Tool.MEASURE_LINE:
                length_pts = math.hypot(end.x - start.x, end.y - start.y)
                if length_pts < 1:
                    return
                if self.calibrating:
                    self._calibrate_with(length_pts)
                    return
                label = self.doc.measure_label("pdfsuite:measure_line", [start, end])
                self.doc.add_measure_line(page_no, start, end, self.measure_color, label)

            self._rebuild_page_annotations(item)
            self.documentModified.emit()
        finally:
            self._drag_points = []
            self._drag_start_pt = None

    # -- calibration ------------------------------------------------------
    def start_calibration(self):
        self.calibrating = True
        self.statusMessage.emit(
            "Calibrage : tracez une ligne sur une cote connue du plan, puis saisissez sa longueur réelle.")

    def _calibrate_with(self, length_pts: float):
        self.calibrating = False
        dlg = CalibrationDialog(self, default_unit=self.doc.unit)
        if dlg.exec() != QDialog.Accepted:
            return
        real_m = dlg.real_length_meters()
        if real_m <= 0:
            return
        self.doc.scale_points_per_meter = length_pts / real_m
        self.doc.relabel_measurements()
        self.rebuild_annotations()
        self.scaleCalibrated.emit()
        self.documentModified.emit()

    # -- click-to-add-vertex polygon tools ---------------------------------
    def _handle_polygon_click(self, event):
        if event.button() == Qt.RightButton:
            self._finish_polygon()
            event.accept()
            return
        scene_pos = self.mapToScene(event.pos())
        item = self._item_at_scene(scene_pos)
        if item is None:
            return
        if self._poly_points and item.page_no != self._poly_page:
            self.statusMessage.emit("Restez sur la même page pour ce tracé.")
            return
        if self._poly_points:
            scene_pos = self._constrain(item, self._poly_points[-1], scene_pos, event.modifiers())
            # click back on the first point closes the shape
            first = self.mapFromScene(self._pdf_to_scene(item, self._poly_points[0]))
            if len(self._poly_points) >= 3 and (first - event.pos()).manhattanLength() <= 10:
                self._finish_polygon()
                return
        self._poly_page = item.page_no
        self._poly_points.append(self._scene_to_pdf_point(item, scene_pos))
        self._update_poly_preview()

    def mouseDoubleClickEvent(self, event):
        if self.tool in POLY_TOOLS:
            self._finish_polygon()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if self.tool in POLY_TOOLS:
            if event.key() == Qt.Key_Escape and self._poly_points:
                self._cancel_polygon()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._finish_polygon()
                return
            if event.key() == Qt.Key_Backspace and self._poly_points:
                self._poly_points.pop()
                self._update_poly_preview()
                return
        if event.key() == Qt.Key_Delete and self._dim is None and not self._poly_points:
            if self.delete_selected():
                return
        if event.key() == Qt.Key_Escape and self._dim is not None:
            self._cancel_dimension()
            return
        if event.key() == Qt.Key_Escape and self.tool != Tool.SELECT:
            self.requestSelectTool.emit()
            return
        super().keyPressEvent(event)

    def _update_poly_preview(self, extra_scene_pt: QPointF | None = None):
        if self._poly_preview_item is not None:
            self._scene.removeItem(self._poly_preview_item)
            self._poly_preview_item = None
        if not self._poly_points or self._poly_page < 0:
            self._show_measure_info(None)
            return
        item = self.page_items[self._poly_page]
        pen = QPen(QColor.fromRgbF(*self.measure_color), 2, Qt.DashLine)
        pen.setCosmetic(True)
        path = QPainterPath(self._pdf_to_scene(item, self._poly_points[0]))
        for pt in self._poly_points[1:]:
            path.lineTo(self._pdf_to_scene(item, pt))
        pts = list(self._poly_points)
        if extra_scene_pt is not None:
            path.lineTo(extra_scene_pt)
            pts.append(self._scene_to_pdf_point(item, extra_scene_pt))
        if len(pts) >= 3:
            path.closeSubpath()
        self._poly_preview_item = QGraphicsPathItem(path)
        self._poly_preview_item.setPen(pen)
        fill = QColor.fromRgbF(*self.measure_color)
        fill.setAlpha(40 if self.tool == Tool.MEASURE_AREA else 0)
        self._poly_preview_item.setBrush(QBrush(fill))
        self._poly_preview_item.setZValue(10)
        self._scene.addItem(self._poly_preview_item)
        self._show_measure_info(pts, "area" if self.tool == Tool.MEASURE_AREA else "perimeter", item)

    def _cancel_polygon(self):
        self._poly_points = []
        self._poly_page = -1
        if self._poly_preview_item is not None:
            self._scene.removeItem(self._poly_preview_item)
            self._poly_preview_item = None
        self._show_measure_info(None)

    def _finish_polygon(self):
        points = self._poly_points
        page_no = self._poly_page
        if len(points) < 3:
            self._cancel_polygon()
            return
        subject = "pdfsuite:measure_area" if self.tool == Tool.MEASURE_AREA else "pdfsuite:measure_perimeter"
        label = self.doc.measure_label(subject, points)
        with self.doc.op("Mesure de pièce"):
            self.doc.add_measure_polygon(page_no, points, self.measure_color, label, subject)
            if self.auto_cotes:
                page = self.doc.page(page_no)
                vis = [pymupdf.Point(p) * ~page.derotation_matrix for p in points]
                self._add_room_cotes(page_no, [(p.x, p.y) for p in vis], None)
        self._cancel_polygon()
        self._rebuild_page_annotations(self.page_items[page_no])
        self.documentModified.emit()

    # -- live measurement panel -------------------------------------------
    def _show_measure_info(self, pdf_pts, kind: str = "line", item: PageItem | None = None):
        box = self._measure_info
        if not pdf_pts or len(pdf_pts) < 2 or self.tool not in MEASURE_TOOLS:
            box.hide()
            return
        doc = self.doc
        page = doc.page(item.page_no) if item else None
        vis = [pymupdf.Point(p) * ~page.derotation_matrix for p in pdf_pts] if page else pdf_pts
        rows = []
        if kind == "line" or self.calibrating:
            a, b = vis[0], vis[-1]
            dx, dy = b.x - a.x, b.y - a.y
            angle = math.degrees(math.atan2(-dy, dx)) % 360
            title = "Calibrage" if self.calibrating else "Longueur"
            rows += [("Distance", doc.fmt_length_pts(math.hypot(dx, dy)) if not self.calibrating
                      else f"{math.hypot(dx, dy) * 25.4 / 72:.1f} mm papier"),
                     ("Angle", f"{angle:.1f}°".replace(".", ",")),
                     ("ΔX", doc.fmt_length_pts(abs(dx))),
                     ("ΔY", doc.fmt_length_pts(abs(dy)))]
        else:
            tup = [(p.x, p.y) for p in vis]
            title = "Surface" if kind == "area" else "Périmètre"
            last = math.dist(tup[-2], tup[-1])
            rows += [("Surface", doc.fmt_area_pts2(doc.poly_area(tup))),
                     ("Périmètre", doc.fmt_length_pts(doc.poly_perimeter(tup))),
                     ("Dernier côté", doc.fmt_length_pts(last)),
                     ("Points", str(len(tup)))]
        ratio = doc.ratio()
        rows += [("Échelle", f"1:{ratio:g}".replace(".", ",") if ratio else "non définie"),
                 ("Précision", f"{10 ** -doc.decimals:g}".replace(".", ","))]
        html = (f"<b style='color:#2f6fed'>{title}</b><table cellspacing=0 cellpadding=1>"
                + "".join(f"<tr><td align=right style='color:#555'>{k} :&nbsp;</td>"
                          f"<td><b>{v}</b></td></tr>" for k, v in rows)
                + "</table>")
        box.setText(html)
        box.adjustSize()
        vp = self.viewport()
        box.move(vp.width() - box.width() - 12, 12)
        box.show()
        box.raise_()

    # -- live preview while dragging ------------------------------------
    def _update_preview(self, item: PageItem, _cur_pt):
        self._clear_preview()
        color = self.measure_color if self.tool == Tool.MEASURE_LINE else self.current_color
        pen = QPen(QColor.fromRgbF(*color), 2)
        pen.setCosmetic(True)
        p0 = self._pdf_to_scene(item, self._drag_start_pt)
        if self.tool == Tool.INK:
            path = QPainterPath(p0)
            for pt in self._drag_points[1:]:
                path.lineTo(self._pdf_to_scene(item, pt))
            self._preview_item = QGraphicsPathItem(path)
            self._preview_item.setPen(pen)
        elif self.tool in (Tool.LINE, Tool.MEASURE_LINE, Tool.ARROW, Tool.CALLOUT):
            p1 = self._pdf_to_scene(item, self._drag_points[-1])
            self._preview_item = QGraphicsLineItem(p0.x(), p0.y(), p1.x(), p1.y())
            self._preview_item.setPen(pen)
        else:
            p1 = self._pdf_to_scene(item, self._drag_points[-1])
            r = QRectF(p0, p1).normalized()
            if self.tool == Tool.ELLIPSE:
                self._preview_item = QGraphicsEllipseItem(r)
            else:
                self._preview_item = QGraphicsRectItem(r)
            if self.tool == Tool.CAPTURE:
                pen = QPen(QColor(47, 111, 237), 1.5, Qt.DashLine)
                pen.setCosmetic(True)
            self._preview_item.setPen(pen)
        self._preview_item.setZValue(10)
        self._scene.addItem(self._preview_item)

    def _clear_preview(self):
        if self._preview_item is not None:
            self._scene.removeItem(self._preview_item)
            self._preview_item = None
        if not self._poly_points:
            self._measure_info.hide()

    # -- text block editing ----------------------------------------------
    def _start_text_edit(self, page_no: int, pdf_pt):
        blocks = self.doc.text_blocks(page_no)
        for block in blocks:
            if block.get("type") != 0:
                continue
            bbox = pymupdf.Rect(block["bbox"])
            if bbox.contains(pdf_pt):
                text = "".join(
                    span["text"]
                    for line in block["lines"]
                    for span in line["spans"]
                )
                fontsize = 12.0
                text = "\n".join("".join(sp["text"] for sp in line["spans"])
                                 for line in block["lines"])
                if block["lines"] and block["lines"][0]["spans"]:
                    span = block["lines"][0]["spans"][0]
                    fontsize = span.get("size", 12.0)
                    c = span.get("color", 0)
                    self._text_edit_info[(page_no, tuple(round(v, 2) for v in bbox))] = {
                        "origin": span.get("origin"),
                        "dir": block["lines"][0].get("dir", (1.0, 0.0)),
                        "color": (((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255),
                    }
                self.requestTextEdit.emit(page_no, bbox, text, fontsize)
                return
        self.statusMessage.emit("Aucun bloc de texte à cet endroit.")

    def apply_text_edit(self, page_no: int, bbox, new_text: str, fontsize: float):
        info = self._text_edit_info.get((page_no, tuple(round(v, 2) for v in bbox)), {})
        self.doc.replace_text_in_rect(page_no, bbox, new_text, fontsize,
                                      color=info.get("color", (0, 0, 0)),
                                      origin=info.get("origin"),
                                      direction=info.get("dir", (1.0, 0.0)))
        self.refresh_page(page_no, content_changed=True)
        self.documentModified.emit()

    def place_signature_image(self, page_no: int, pdf_pt, png_bytes: bytes,
                              width_pt: float = 140.0):
        page = self.doc.page(page_no)
        aspect = 0.4
        rect = pymupdf.Rect(pdf_pt.x, pdf_pt.y,
                            pdf_pt.x + width_pt, pdf_pt.y + width_pt * aspect)
        self.doc.insert_image(page_no, rect, png_bytes)
        self.refresh_page(page_no, content_changed=True)
        self.documentModified.emit()

    # -- cursor coordinates -----------------------------------------------
    def _emit_cursor_info(self, viewport_pos):
        if self.rulers_visible:
            self._hruler.cursor_px = viewport_pos.x()
            self._vruler.cursor_px = viewport_pos.y()
            self._update_rulers()
        scene_pos = self.mapToScene(viewport_pos)
        item = self._item_at_scene(scene_pos)
        if item is None:
            self.cursorInfo.emit("")
            return
        local = scene_pos - item.pos()
        upp, unit = self.units_per_point()
        x, y = local.x() * upp, local.y() * upp
        d = max(self.doc.decimals, 1) if unit != "cm" or self.doc.scale_points_per_meter else 1
        self.cursorInfo.emit(f"X : {x:.{d}f} {unit}   Y : {y:.{d}f} {unit}".replace(".", ","))

    def page_size_text(self) -> str:
        if not self.page_items:
            return ""
        it = self.page_items[self.current_page()]
        upp, unit = self.units_per_point()
        w, h = it.size.width() * upp, it.size.height() * upp
        return f"L : {w:.2f} {unit}   H : {h:.2f} {unit}".replace(".", ",")

    # -- magnifier --------------------------------------------------------
    LOUPE_SRC = 70
    LOUPE_FACTOR = 2.5

    def set_loupe(self, enabled: bool):
        self.loupe_enabled = enabled
        if not enabled and self._loupe is not None:
            self._loupe.hide()

    def _update_loupe(self, viewport_pos):
        if self._loupe is None:
            self._loupe = QLabel(None, Qt.ToolTip | Qt.FramelessWindowHint)
            self._loupe.setStyleSheet("border: 2px solid #2f6fed; background: white;")
        h = self.LOUPE_SRC
        src = QRect(viewport_pos.x() - h, viewport_pos.y() - h, 2 * h, 2 * h)
        size = int(2 * h * self.LOUPE_FACTOR)
        # re-render the area (works with the GPU viewport, unlike grab())
        pix = QPixmap(size, size)
        pix.fill(self.backgroundBrush().color())
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        self.render(painter, QRectF(0, 0, size, size), src)
        painter.end()
        self._loupe.setPixmap(pix)
        self._loupe.resize(size + 4, size + 4)
        gpos = self.viewport().mapToGlobal(viewport_pos)
        self._loupe.move(gpos.x() + 24, gpos.y() + 24)
        self._loupe.show()

    def leaveEvent(self, event):
        if self._loupe is not None:
            self._loupe.hide()
        self._hruler.cursor_px = self._vruler.cursor_px = None
        self._update_rulers()
        self.cursorInfo.emit("")
        super().leaveEvent(event)

    # -- invert colours ------------------------------------------------------
    def set_invert(self, enabled: bool):
        self.invert_colors = enabled
        for item in self.page_items:
            item.base = None
            item.detail = None
            item.update()
        self._update_visible()

    # -- capture a zone to the clipboard -------------------------------------
    def capture_to_clipboard(self, item: PageItem, p1, p2, factor: float | None = None) -> QImage:
        a = self._pdf_to_scene(item, p1)
        b = self._pdf_to_scene(item, p2)
        src = QRectF(a, b).normalized()
        factor = factor or max(2.0, self.zoom * 2)
        img = QImage(QSize(max(1, int(src.width() * factor)), max(1, int(src.height() * factor))),
                     QImage.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self._scene.render(painter, QRectF(0, 0, img.width(), img.height()), src)
        painter.end()
        QApplication.clipboard().setImage(img)
        self.statusMessage.emit("Zone copiée dans le presse-papiers (Ctrl+V pour la coller).")
        return img

    # -- stamps ---------------------------------------------------------------
    @staticmethod
    def stamp_text(label: str) -> str:
        today = datetime.date.today().strftime("%d/%m/%Y")
        try:
            user = getpass.getuser()
        except Exception:
            user = ""
        return f"{label}\n{today}" + (f" – {user}" if user else "")

    def place_stamp(self, page_no: int, pdf_pt, label: str | None = None):
        label = label or self.stamp_label
        text = self.stamp_text(label)
        color = STAMP_COLORS.get(label, (0.85, 0.1, 0.1))
        size = 14
        longest = max(len(line) for line in text.split("\n"))
        w = longest * size * 0.62 + 18
        h = 2 * size * 1.3 + 10
        rect = pymupdf.Rect(pdf_pt.x - w / 2, pdf_pt.y - h / 2, pdf_pt.x + w / 2, pdf_pt.y + h / 2)
        self.doc.add_stamp(page_no, rect, text, color, size)
        self._rebuild_page_annotations(self.page_items[page_no])
        self.documentModified.emit()

    # -- callouts -------------------------------------------------------------
    def _create_callout(self, page_no: int, target, end, text: str | None = None):
        if text is None:
            text, ok = QInputDialog.getMultiLineText(self, "Légende", "Texte de la légende :")
            if not ok or not text.strip():
                return
        size = 11
        lines = text.split("\n")
        w = max(len(line) for line in lines) * size * 0.58 + 12
        h = len(lines) * size * 1.35 + 8
        x0 = end.x if end.x >= target.x else end.x - w
        box = pymupdf.Rect(x0, end.y - h / 2, x0 + w, end.y + h / 2)
        self.doc.add_callout(page_no, target, box, text, self.current_color, size)


_GL_CLASS = False


def _gl_widget_class():
    """QOpenGLWidget if available (hardware-accelerated drawing), else None."""
    global _GL_CLASS
    if _GL_CLASS is False:
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
            _GL_CLASS = QOpenGLWidget
        except Exception:
            _GL_CLASS = None
    return _GL_CLASS


# -- dimension tool (cote) ---------------------------------------------------
def _dim_methods():
    """Methods of the "Cote" tool, attached to PdfGraphicsView below.

    1st click = point A, 2nd click (or drag A -> B) = point B, then move the
    mouse to slide the dimension line away from AB and click to place it.
    Shift locks AB to 0 / 45 / 90 degrees. Échap or right click cancels."""

    def _visual_at(self, item, viewport_pos, modifiers, anchor=None):
        scene_pos = self.mapToScene(viewport_pos)
        if anchor is not None and modifiers & Qt.ShiftModifier:
            base = item.pos() + anchor
            d = scene_pos - base
            ang = math.atan2(d.y(), d.x())
            snapped = round(ang / (math.pi / 4)) * (math.pi / 4)
            length = math.hypot(d.x(), d.y()) * math.cos(ang - snapped)
            scene_pos = base + QPointF(length * math.cos(snapped), length * math.sin(snapped))
        v = self._scene_to_visual(item, scene_pos)
        return QPointF(v.x, v.y)

    def _dimension_press(self, event):
        if event.button() == Qt.RightButton:
            self._cancel_dimension()
            event.accept()
            return
        if event.button() != Qt.LeftButton:
            return
        d = self._dim
        if d is None:
            if not self._require_scale():
                return
            item = self._item_at_scene(self.mapToScene(event.pos()))
            if item is None:
                return
            a = self._visual_at(item, event.pos(), Qt.NoModifier)
            preview = ai.DimensionItem(self, item.page_no, None, a, a, 0.0, self.measure_color, " ")
            preview.setParentItem(item)
            preview.setZValue(15)
            self._dim = {"item": item, "a": a, "b": None, "press": event.pos(), "preview": preview}
            return
        if d["b"] is None:
            d["b"] = self._visual_at(d["item"], event.pos(), event.modifiers(), d["a"])
            self._dimension_b_set()
            return
        self._dimension_place()

    def _dimension_release(self, event):
        d = self._dim
        if d is None or d["b"] is not None or event.button() != Qt.LeftButton:
            return
        # press-drag-release from A to B also works
        if (event.pos() - d["press"]).manhattanLength() > 8:
            d["b"] = self._visual_at(d["item"], event.pos(), event.modifiers(), d["a"])
            self._dimension_b_set()

    def _dimension_b_set(self):
        d = self._dim
        if math.hypot(d["b"].x() - d["a"].x(), d["b"].y() - d["a"].y()) < 0.5:
            d["b"] = None
            return
        if self.calibrating:
            length = math.hypot(d["b"].x() - d["a"].x(), d["b"].y() - d["a"].y())
            self._cancel_dimension()
            self._calibrate_with(length)
            return
        self.statusMessage.emit("Déplacez la souris pour décaler la cote, puis cliquez pour la poser.")

    def _dimension_move(self, event):
        d = self._dim
        pv = d["preview"]
        pv.prepareGeometryChange()
        if d["b"] is None:
            pv.b = self._visual_at(d["item"], event.pos(), event.modifiers(), d["a"])
            pv.offset = 0.0
        else:
            pv.b = d["b"]
            cur = self._visual_at(d["item"], event.pos(), Qt.NoModifier)
            n = pv.normal()
            pv.offset = (cur.x() - d["a"].x()) * n.x() + (cur.y() - d["a"].y()) * n.y()
        pv.label = pv._compute_label() if pv.a != pv.b else " "
        pv.update()
        page = self.doc.page(d["item"].page_no)
        self._show_measure_info([ai.to_pdf(pv.a, page), ai.to_pdf(pv.b, page)], "line", d["item"])

    def _dimension_place(self):
        d = self._dim
        pv = d["preview"]
        item = d["item"]
        page = self.doc.page(item.page_no)
        verts = pv.pdf_vertices(page)
        label = pv._compute_label()
        self._cancel_dimension()
        self.doc.add_dimension(item.page_no, verts, self.measure_color, label)
        self._rebuild_page_annotations(item)
        self.documentModified.emit()

    def _cancel_dimension(self):
        d = getattr(self, "_dim", None)
        if d is not None and d["preview"].scene() is not None:
            self._scene.removeItem(d["preview"])
        self._dim = None
        if hasattr(self, "_measure_info"):
            self._measure_info.hide()

    return {k: v for k, v in locals().items() if callable(v)}


for _name, _fn in _dim_methods().items():
    setattr(PdfGraphicsView, _name, _fn)


# -- automatic room (Pièce auto) + automatic cotes -----------------------------
def _room_methods():

    def auto_room(self, item, click_visual):
        """One click inside a room: outline, perimeter + area, cotes of
        every wall with its doors / windows. One undo step."""
        from . import room_detect as rd
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = rd.detect_room(self.doc, item.page_no, click_visual)
        except rd.RoomError as exc:
            QApplication.restoreOverrideCursor()
            self.statusMessage.emit(str(exc))
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Pièce automatique", str(exc))
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        poly = res["polygon"]
        page = self.doc.page(item.page_no)
        pdf_pts = [pymupdf.Point(p) * page.derotation_matrix for p in poly]
        subject = "pdfsuite:measure_perimeter"
        label = self.doc.measure_label(subject, pdf_pts)
        with self.doc.op("Pièce automatique"):
            self.doc.add_measure_polygon(item.page_no, pdf_pts, self.measure_color, label, subject)
            if self.auto_cotes:
                self._add_room_cotes(item.page_no, poly, res["openings"])
        self._rebuild_page_annotations(item)
        self.documentModified.emit()
        doors = sum(1 for o in res["openings"] if o["kind"] == "porte")
        wins = sum(1 for o in res["openings"] if o["kind"] == "fenêtre")
        extra = []
        if doors:
            extra.append(f"{doors} porte" + ("s" if doors > 1 else ""))
        if wins:
            extra.append(f"{wins} fenêtre" + ("s" if wins > 1 else ""))
        self.statusMessage.emit("Pièce : " + label.replace("\n", " · ") + (" · " + ", ".join(extra) if extra else ""))

    def _add_room_cotes(self, page_no, poly, openings):
        """Cotes inside the room along each side: the side's length, or a
        chain wall / opening / wall plus the overall length when the side
        has openings. ``openings`` None = detect them now."""
        from . import room_detect as rd
        if openings is None:
            try:
                openings = rd.find_openings(self.doc, page_no, poly)
            except Exception:
                openings = []
        scale = self.doc.scale_points_per_meter or 1.0
        d1, d2 = COTE_OFFSET_M[0] * scale, COTE_OFFSET_M[1] * scale
        page = self.doc.page(page_no)
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            L = math.dist(a, b)
            if L < MIN_COTE_SIDE_M * scale:
                continue                           # door frames, small returns
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, ny = uy, -ux                       # DimensionItem.normal()
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            inside = 1.0 if rd.point_in_poly(mid[0] + nx * d1 * 0.5, mid[1] + ny * d1 * 0.5,
                                              poly) else -1.0
            ts = sorted((math.dist(a, o["a"]), math.dist(a, o["b"]))
                        for o in openings if o["edge"] == i)
            marks = [0.0]
            for t0, t1 in ts:
                marks += [min(t0, t1), max(t0, t1)]
            marks.append(L)
            marks = sorted(set(marks))

            def cote(t0, t1, off):
                pa = QPointF(a[0] + ux * t0, a[1] + uy * t0)
                pb = QPointF(a[0] + ux * t1, a[1] + uy * t1)
                tmp = ai.DimensionItem(self, page_no, None, pa, pb, off * inside, self.measure_color)
                self.doc.add_dimension(page_no, tmp.pdf_vertices(page), self.measure_color,
                                       tmp._compute_label())

            if len(marks) > 2:
                for k in range(len(marks) - 1):
                    if marks[k + 1] - marks[k] >= MIN_CHAIN_M * scale:   # no 2 cm pieces
                        cote(marks[k], marks[k + 1], d1)
                cote(0.0, L, d2)
            else:
                cote(0.0, L, d1)

    return {k: v for k, v in locals().items() if callable(v)}


for _name, _fn in _room_methods().items():
    setattr(PdfGraphicsView, _name, _fn)
