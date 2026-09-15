from __future__ import annotations

import math

import pymupdf
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QPainterPath, QBrush
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPathItem, QInputDialog,
    QGraphicsProxyWidget, QLineEdit, QCheckBox, QComboBox, QDialog,
)

from .tools import Tool, DRAG_TOOLS, POLY_TOOLS
from .pdf_document import PdfDocument
from .dialogs import CalibrationDialog
from . import annotation_items as ai

GAP = 14


def _rect_to_quad(r: pymupdf.Rect) -> pymupdf.Quad:
    return pymupdf.Quad(r.tl, r.tr, r.bl, r.br)


def pixmap_to_qpixmap(pix: pymupdf.Pixmap) -> QPixmap:
    fmt = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
    return QPixmap.fromImage(img)


class PageItem(QGraphicsPixmapItem):
    def __init__(self, page_no: int):
        super().__init__()
        self.page_no = page_no
        self.rendered = False
        self.annot_items: list = []  # top-level vector items + their handles


class PdfGraphicsView(QGraphicsView):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    documentModified = Signal()
    statusMessage = Signal(str)
    requestTextEdit = Signal(int, object, str, float)
    requestSignaturePlacement = Signal(int, object)

    def __init__(self, document: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = document
        self.zoom = 1.33
        self.tool = Tool.SELECT
        self.current_color = (0.9, 0.1, 0.1)
        self.page_items: list[PageItem] = []

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(self.renderHints())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(60, 63, 68)))
        self.setFocusPolicy(Qt.StrongFocus)

        self._dragging = False
        self._drag_page = -1
        self._drag_start_pt = None
        self._drag_points: list = []
        self._preview_item = None
        self.form_mode = False
        self._form_proxies: list = []

        # state for the click-to-add-vertex perimeter tool
        self._poly_page = -1
        self._poly_points: list = []
        self._poly_preview_item = None

        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.build_scene()

    # ------------------------------------------------------------------
    def set_tool(self, tool: Tool):
        if self.tool == Tool.MEASURE_PERIMETER and tool != Tool.MEASURE_PERIMETER:
            self._cancel_polygon()
        self.tool = tool
        self.setDragMode(
            QGraphicsView.ScrollHandDrag if tool == Tool.PAN else QGraphicsView.NoDrag
        )

    def set_color(self, rgb: tuple[float, float, float]):
        self.current_color = rgb

    def apply_theme(self, surround_color: QColor):
        self.setBackgroundBrush(QBrush(surround_color))

    # -- ctrl+wheel zoom, centred on the cursor --------------------------
    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            angle = event.angleDelta().y()
            if angle == 0:
                event.accept()
                return
            viewport_pos = event.position().toPoint()
            fraction = self._fraction_at(viewport_pos)
            factor = 1.15 if angle > 0 else 1 / 1.15
            new_zoom = max(0.2, min(6.0, self.zoom * factor))
            self.set_zoom(new_zoom)
            if fraction is not None:
                self._recenter_on_fraction(*fraction, viewport_pos)
            event.accept()
            return
        super().wheelEvent(event)

    def _fraction_at(self, viewport_pos):
        scene_pos = self.mapToScene(viewport_pos)
        item = self._item_at_scene(scene_pos)
        if item is None:
            return None
        size = item.pixmap().size()
        if size.width() == 0 or size.height() == 0:
            return None
        local = scene_pos - item.pos()
        return item.page_no, local.x() / size.width(), local.y() / size.height()

    def _recenter_on_fraction(self, page_no, fx, fy, viewport_pos):
        if not (0 <= page_no < len(self.page_items)):
            return
        item = self.page_items[page_no]
        size = item.pixmap().size()
        target = item.pos() + QPointF(fx * size.width(), fy * size.height())
        self.verticalScrollBar().setValue(int(target.y() - viewport_pos.y()))

    # ------------------------------------------------------------------
    def build_scene(self, keep_page: int | None = None):
        self._scene.clear()
        self.page_items = []
        max_w = 0.0
        sizes = []
        for i in range(self.doc.page_count):
            w, h = self.doc.visual_size(i)
            sizes.append((w, h))
            max_w = max(max_w, w * self.zoom)

        y = GAP
        for i, (w, h) in enumerate(sizes):
            pw, ph = w * self.zoom, h * self.zoom
            item = PageItem(i)
            placeholder = QPixmap(max(1, int(pw)), max(1, int(ph)))
            placeholder.fill(QColor(255, 255, 255))
            item.setPixmap(placeholder)
            item.setPos((max_w - pw) / 2, y)
            item.setZValue(0)
            self._scene.addItem(item)
            self.page_items.append(item)
            self._rebuild_page_annotations(item)
            y += ph + GAP

        self._scene.setSceneRect(0, 0, max_w, y)
        if keep_page is not None and 0 <= keep_page < len(self.page_items):
            self.goto_page(keep_page)
        self._update_visible()
        self._form_proxies = []
        if self.form_mode:
            self._add_form_widgets()

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
            self._scene.removeItem(proxy)
        self._form_proxies = []

    def _add_form_widgets(self):
        self._clear_form_widgets()
        for item in self.page_items:
            for w in self.doc.widgets(item.page_no):
                editor = self._make_widget_editor(w)
                if editor is None:
                    continue
                proxy = QGraphicsProxyWidget(item)
                proxy.setWidget(editor)
                r = pymupdf.Rect(w.rect)
                proxy.setPos(r.x0 * self.zoom, r.y0 * self.zoom)
                proxy.resize(r.width * self.zoom, r.height * self.zoom)
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
        widget_obj.field_value = value
        widget_obj.update()
        self.doc.mark_dirty()
        self.documentModified.emit()

    def set_zoom(self, zoom: float):
        cur = self.current_page()
        self.zoom = max(0.2, min(6.0, zoom))
        self.build_scene(keep_page=cur)
        self.zoomChanged.emit(self.zoom)

    def current_page(self) -> int:
        top = self.mapToScene(0, 0).y()
        for item in self.page_items:
            if item.y() + item.pixmap().height() > top:
                return item.page_no
        return max(0, len(self.page_items) - 1)

    def goto_page(self, n: int):
        if 0 <= n < len(self.page_items):
            item = self.page_items[n]
            self.verticalScrollBar().setValue(int(item.y()) - GAP)

    def refresh_page(self, n: int):
        """Re-render the page's raster. Only needed when the page's actual
        *content* changes (text edit, rotation, signature) - annotations
        live in their own vector layer and never need this."""
        if 0 <= n < len(self.page_items):
            pix = self.doc.render_page(n, self.zoom)
            self.page_items[n].setPixmap(pixmap_to_qpixmap(pix))
            self.page_items[n].rendered = True

    def refresh_all(self):
        cur = self.current_page()
        self.build_scene(keep_page=cur)

    # ------------------------------------------------------------------
    def _on_scrolled(self, _val):
        self._update_visible()
        self.pageChanged.emit(self.current_page())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_visible()

    def _update_visible(self):
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        buffer = visible.height()
        expanded = visible.adjusted(0, -buffer, 0, buffer)
        for item in self.page_items:
            r = QRectF(item.pos(), item.pixmap().size())
            if not item.rendered and r.intersects(expanded):
                self.refresh_page(item.page_no)

    # ------------------------------------------------------------------
    def _item_at_scene(self, scene_pos) -> PageItem | None:
        for item in self.page_items:
            r = QRectF(item.pos(), item.pixmap().size())
            if r.contains(scene_pos):
                return item
        return None

    def _scene_to_pdf_point(self, item: PageItem, scene_pos: QPointF) -> pymupdf.Point:
        local = scene_pos - item.pos()
        pt = pymupdf.Point(local.x() / self.zoom, local.y() / self.zoom)
        page = self.doc.page(item.page_no)
        return pt * page.derotation_matrix

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if self.tool == Tool.MEASURE_PERIMETER:
            self._handle_polygon_click(event)
            return

        if self.tool in (Tool.PAN, Tool.SELECT):
            super().mousePressEvent(event)
            return

        scene_pos = self.mapToScene(event.pos())
        item = self._item_at_scene(scene_pos)
        if item is None:
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

        if self.tool in DRAG_TOOLS:
            self._dragging = True
            self._drag_page = page_no
            self._drag_start_pt = pdf_pt
            self._drag_points = [pdf_pt]
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.tool == Tool.MEASURE_PERIMETER and self._poly_points:
            scene_pos = self.mapToScene(event.pos())
            self._update_poly_preview(extra_scene_pt=scene_pos)
            return
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        scene_pos = self.mapToScene(event.pos())
        item = self.page_items[self._drag_page]
        pdf_pt = self._scene_to_pdf_point(item, scene_pos)
        self._drag_points.append(pdf_pt)
        self._update_preview(item, pdf_pt)

    def mouseReleaseEvent(self, event):
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

            elif self.tool == Tool.INK:
                if len(self._drag_points) < 2:
                    return
                self.doc.add_ink(page_no, [self._drag_points], self.current_color)

            elif self.tool == Tool.MEASURE_LINE:
                length_pts = math.hypot(end.x - start.x, end.y - start.y)
                if length_pts < 1:
                    return
                if not self._ensure_scale(length_pts):
                    return
                meters = self.doc.points_to_meters(length_pts)
                label = self.doc.format_length(meters)
                self.doc.add_measure_line(page_no, start, end, self.current_color, label)

            self._rebuild_page_annotations(item)
            self.documentModified.emit()
        finally:
            self._drag_points = []
            self._drag_start_pt = None

    # -- scale calibration ------------------------------------------------
    def _ensure_scale(self, reference_length_points: float) -> bool:
        if self.doc.scale_points_per_meter or reference_length_points <= 0:
            return self.doc.scale_points_per_meter is not None
        dlg = CalibrationDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return False
        real_m = dlg.real_length_meters()
        if real_m <= 0:
            return False
        self.doc.scale_points_per_meter = reference_length_points / real_m
        return True

    # -- click-to-add-vertex perimeter tool --------------------------------
    def _handle_polygon_click(self, event):
        scene_pos = self.mapToScene(event.pos())
        if event.button() == Qt.RightButton:
            self._finish_polygon()
            event.accept()
            return
        item = self._item_at_scene(scene_pos)
        if item is None:
            return
        if self._poly_points and item.page_no != self._poly_page:
            self.statusMessage.emit("Restez sur la même page pour ce périmètre.")
            return
        self._poly_page = item.page_no
        pdf_pt = self._scene_to_pdf_point(item, scene_pos)
        self._poly_points.append(pdf_pt)
        self._update_poly_preview()

    def mouseDoubleClickEvent(self, event):
        if self.tool == Tool.MEASURE_PERIMETER:
            self._finish_polygon()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if self.tool == Tool.MEASURE_PERIMETER:
            if event.key() == Qt.Key_Escape:
                self._cancel_polygon()
                return
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._finish_polygon()
                return
        super().keyPressEvent(event)

    def _update_poly_preview(self, extra_scene_pt: QPointF | None = None):
        if self._poly_preview_item is not None:
            self._scene.removeItem(self._poly_preview_item)
            self._poly_preview_item = None
        if not self._poly_points or self._poly_page < 0:
            return
        item = self.page_items[self._poly_page]
        pen = QPen(QColor.fromRgbF(*self.current_color))
        pen.setWidth(2)
        pen.setStyle(Qt.DashLine)
        path = QPainterPath(self._pdf_to_scene(item, self._poly_points[0]))
        for pt in self._poly_points[1:]:
            path.lineTo(self._pdf_to_scene(item, pt))
        if extra_scene_pt is not None:
            path.lineTo(extra_scene_pt)
        self._poly_preview_item = QGraphicsPathItem(path)
        self._poly_preview_item.setPen(pen)
        self._poly_preview_item.setZValue(10)
        self._scene.addItem(self._poly_preview_item)

    def _cancel_polygon(self):
        self._poly_points = []
        self._poly_page = -1
        if self._poly_preview_item is not None:
            self._scene.removeItem(self._poly_preview_item)
            self._poly_preview_item = None

    def _finish_polygon(self):
        points = self._poly_points
        page_no = self._poly_page
        if len(points) < 3:
            self._cancel_polygon()
            return
        first_edge = math.hypot(points[1].x - points[0].x, points[1].y - points[0].y)
        if not self._ensure_scale(first_edge):
            self._cancel_polygon()
            return
        perimeter_pts = sum(
            math.hypot(points[(i + 1) % len(points)].x - points[i].x,
                       points[(i + 1) % len(points)].y - points[i].y)
            for i in range(len(points))
        )
        area_pts2 = abs(sum(
            points[i].x * points[(i + 1) % len(points)].y
            - points[(i + 1) % len(points)].x * points[i].y
            for i in range(len(points))
        )) / 2.0
        meters = self.doc.points_to_meters(perimeter_pts)
        scale = self.doc.scale_points_per_meter
        area_m2 = area_pts2 / (scale * scale) if scale else 0.0
        label = f"Périmètre {self.doc.format_length(meters)} · Surface {self.doc.format_area(area_m2)}"
        self.doc.add_measure_polygon(page_no, points, self.current_color, label)
        self._cancel_polygon()
        self._rebuild_page_annotations(self.page_items[page_no])
        self.documentModified.emit()

    # -- live preview while dragging ------------------------------------
    def _pdf_to_scene(self, item: PageItem, pdf_pt) -> QPointF:
        page = self.doc.page(item.page_no)
        vis = pdf_pt * ~page.derotation_matrix
        return item.pos() + QPointF(vis.x * self.zoom, vis.y * self.zoom)

    def _update_preview(self, item: PageItem, _cur_pt):
        self._clear_preview()
        pen = QPen(QColor.fromRgbF(*self.current_color))
        pen.setWidth(2)
        p0 = self._pdf_to_scene(item, self._drag_start_pt)
        if self.tool == Tool.INK:
            path = QPainterPath(p0)
            for pt in self._drag_points[1:]:
                path.lineTo(self._pdf_to_scene(item, pt))
            self._preview_item = QGraphicsPathItem(path)
            self._preview_item.setPen(pen)
        elif self.tool in (Tool.LINE, Tool.MEASURE_LINE):
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
            self._preview_item.setPen(pen)
        self._preview_item.setZValue(10)
        self._scene.addItem(self._preview_item)

    def _clear_preview(self):
        if self._preview_item is not None:
            self._scene.removeItem(self._preview_item)
            self._preview_item = None

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
                if block["lines"] and block["lines"][0]["spans"]:
                    fontsize = block["lines"][0]["spans"][0].get("size", 12.0)
                self.requestTextEdit.emit(page_no, bbox, text, fontsize)
                return
        self.statusMessage.emit("Aucun bloc de texte à cet endroit.")

    def apply_text_edit(self, page_no: int, bbox, new_text: str, fontsize: float):
        self.doc.replace_text_in_rect(page_no, bbox, new_text, fontsize)
        self.refresh_page(page_no)
        self.documentModified.emit()

    def place_signature_image(self, page_no: int, pdf_pt, png_bytes: bytes,
                               width_pt: float = 140.0):
        page = self.doc.page(page_no)
        aspect = 0.4
        rect = pymupdf.Rect(pdf_pt.x, pdf_pt.y,
                             pdf_pt.x + width_pt, pdf_pt.y + width_pt * aspect)
        page.insert_image(rect, stream=png_bytes, keep_proportion=True)
        self.doc.mark_dirty()
        self.refresh_page(page_no)
        self.documentModified.emit()
