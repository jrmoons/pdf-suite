"""Interactive vector representations of PDF annotations.

Annotations are still real PyMuPDF annotations under the hood (so they
save/reload like any PDF), but the page raster is rendered *without* them
(``annots=False``) and every annotation is drawn here instead, as a normal
QGraphicsItem sitting on top of the page. That is what makes a drawn line,
rectangle, ink stroke or measurement selectable, draggable and lockable
instead of being permanently baked into a bitmap - and it also removes the
need to re-rasterise the whole page every time an annotation changes,
which was the main source of the previous UI lag.

PyMuPDF has no "move this annotation" API, so an edited shape is applied
by deleting the old annotation and creating a fresh one with the same
style at the new geometry (see the ``update_*`` helpers on PdfDocument).
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QPainterPath, QFont, QFontMetricsF
from PySide6.QtWidgets import QGraphicsObject, QGraphicsEllipseItem, QGraphicsItem, QMenu

HANDLE_RADIUS = 4.5


def to_visual(pdf_pt, page) -> QPointF:
    """PDF (mediabox) point -> the de-rotated space our raster is drawn in.

    ``pdf_pt`` may be an (x, y) tuple or a ``pymupdf.Point``. Returns a
    ``QPointF`` for direct use in Qt drawing code.
    """
    import pymupdf
    p = pymupdf.Point(pdf_pt) * ~page.derotation_matrix
    return QPointF(p.x, p.y)


def to_pdf(visual_pt: QPointF, page):
    """Inverse of :func:`to_visual`: a ``QPointF`` -> ``pymupdf.Point``."""
    import pymupdf
    return pymupdf.Point(visual_pt.x(), visual_pt.y()) * page.derotation_matrix


def _qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*rgb) if rgb else QColor(0, 0, 0)


def _build_menu(view, locked: bool, on_toggle_lock=None, on_delete=None) -> QMenu:
    menu = QMenu()
    if on_toggle_lock is not None:
        act = menu.addAction("Déverrouiller la position" if locked else "Verrouiller la position")
        act.triggered.connect(on_toggle_lock)
        menu.addSeparator()
    if on_delete is not None:
        act = menu.addAction("Supprimer")
        act.triggered.connect(on_delete)
    return menu


class VertexHandle(QGraphicsEllipseItem):
    """A small draggable dot at one vertex of a measurement shape.

    Kept at a constant pixel size (no zoom scaling) and positioned in the
    parent page item's pixel space, as a sibling of the shape it edits.
    """

    def __init__(self, owner: "MeasureItemBase", index: int, parent=None):
        super().__init__(-HANDLE_RADIUS, -HANDLE_RADIUS, HANDLE_RADIUS * 2, HANDLE_RADIUS * 2, parent)
        self.owner = owner
        self.index = index
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setPen(QPen(owner.color, 1.4))
        self.setZValue(20)
        self.setCursor(Qt.CrossCursor)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def set_locked(self, locked: bool):
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        self.setVisible(not locked)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene() is not None:
            self.owner.handle_moving(self.index, value)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.owner.handle_released()


class ShapeItem(QGraphicsObject):
    """Rect / ellipse / line / ink annotation: whole-shape drag, lock, delete."""

    KIND_ZVALUE = 8

    def __init__(self, view, page_no: int, annot, kind: str, geometry, color,
                 fill=None, width: float = 1.5):
        super().__init__()
        self.view = view
        self.page_no = page_no
        self.annot = annot
        self.kind = kind
        self.geometry = geometry
        self.color_tuple = color
        self.fill_tuple = fill
        self.width = width
        self.locked = False

        self.setScale(view.zoom)
        self.setZValue(self.KIND_ZVALUE)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setCursor(Qt.SizeAllCursor)
        self.setAcceptHoverEvents(True)

    # -- geometry helpers -------------------------------------------------
    def boundingRect(self) -> QRectF:
        pad = max(self.width, 4.0)
        if self.kind in ("rect", "ellipse"):
            return QRectF(self.geometry).normalized().adjusted(-pad, -pad, pad, pad)
        if self.kind == "line":
            p1, p2 = self.geometry
            return QRectF(p1, p2).normalized().adjusted(-pad, -pad, pad, pad)
        # ink: bounding box of every point in every stroke
        xs, ys = [], []
        for stroke in self.geometry:
            for pt in stroke:
                xs.append(pt.x())
                ys.append(pt.y())
        if not xs:
            return QRectF()
        return QRectF(min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)

    def paint(self, painter, option, widget=None):
        pen = QPen(_qcolor(self.color_tuple), self.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QBrush(_qcolor(self.fill_tuple)) if self.fill_tuple else Qt.NoBrush)
        if self.kind == "rect":
            painter.drawRect(QRectF(self.geometry).normalized())
        elif self.kind == "ellipse":
            painter.drawEllipse(QRectF(self.geometry).normalized())
        elif self.kind == "line":
            painter.drawLine(*self.geometry)
        elif self.kind == "ink":
            for stroke in self.geometry:
                if len(stroke) < 2:
                    continue
                path = QPainterPath(stroke[0])
                for pt in stroke[1:]:
                    path.lineTo(pt)
                painter.drawPath(path)
        if self.isSelected():
            sel_pen = QPen(QColor(47, 111, 237), 1, Qt.DashLine)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())

    # -- interaction --------------------------------------------------
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.locked:
            return
        delta = self.pos()
        if abs(delta.x()) < 0.01 and abs(delta.y()) < 0.01:
            return
        zoom = self.scale() or 1.0
        pt_delta = QPointF(delta.x() / zoom, delta.y() / zoom)
        self._apply_delta(pt_delta)
        self.setPos(0, 0)
        self.prepareGeometryChange()
        self._sync_to_pdf()
        self.update()

    def _apply_delta(self, d: QPointF):
        if self.kind in ("rect", "ellipse"):
            self.geometry = QRectF(self.geometry).translated(d)
        elif self.kind == "line":
            p1, p2 = self.geometry
            self.geometry = (p1 + d, p2 + d)
        elif self.kind == "ink":
            self.geometry = [[pt + d for pt in stroke] for stroke in self.geometry]

    def _sync_to_pdf(self):
        page = self.view.doc.page(self.page_no)
        doc = self.view.doc
        if self.kind == "rect":
            pdf_rect = _rect_to_pdf(self.geometry, page)
            self.annot = doc.update_rect(self.page_no, self.annot, pdf_rect,
                                          self.color_tuple, self.fill_tuple, self.width)
        elif self.kind == "ellipse":
            pdf_rect = _rect_to_pdf(self.geometry, page)
            self.annot = doc.update_ellipse(self.page_no, self.annot, pdf_rect,
                                             self.color_tuple, self.fill_tuple, self.width)
        elif self.kind == "line":
            p1, p2 = self.geometry
            self.annot = doc.update_line(self.page_no, self.annot,
                                          to_pdf(p1, page), to_pdf(p2, page),
                                          self.color_tuple, self.width)
        elif self.kind == "ink":
            strokes = [[(to_pdf(pt, page).x, to_pdf(pt, page).y) for pt in stroke]
                       for stroke in self.geometry]
            self.annot = doc.update_ink(self.page_no, self.annot, strokes,
                                         self.color_tuple, self.width)
        self.view.documentModified.emit()

    def contextMenuEvent(self, event):
        def toggle_lock():
            self.locked = not self.locked
            self.setFlag(QGraphicsItem.ItemIsMovable, not self.locked)
            self.update()

        def delete():
            self.view.doc.delete_annot(self.page_no, self.annot)
            self.view.remove_annotation_item(self.page_no, self)
            self.view.documentModified.emit()

        menu = _build_menu(self.view, self.locked, toggle_lock, delete)
        menu.exec(event.screenPos())
        event.accept()


def _rect_to_pdf(rect: QRectF, page) -> "pymupdf.Rect":
    import pymupdf
    p1 = to_pdf(rect.topLeft(), page)
    p2 = to_pdf(rect.bottomRight(), page)
    return pymupdf.Rect(p1, p2).normalize()


class MarkupItem(QGraphicsObject):
    """Highlight / underline / strikeout: display + delete only (text-anchored)."""

    def __init__(self, view, page_no: int, annot, kind: str, quads, color):
        super().__init__()
        self.view = view
        self.page_no = page_no
        self.annot = annot
        self.kind = kind
        self.quads = quads  # list[QRectF] in visual points
        self.color_tuple = color
        self.setScale(view.zoom)
        self.setZValue(3)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:
        if not self.quads:
            return QRectF()
        r = QRectF(self.quads[0])
        for q in self.quads[1:]:
            r = r.united(QRectF(q))
        return r.adjusted(-2, -2, 2, 2)

    def paint(self, painter, option, widget=None):
        color = _qcolor(self.color_tuple)
        if self.kind == "highlight":
            color.setAlphaF(0.45)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            for q in self.quads:
                painter.drawRect(q)
        else:
            pen = QPen(color, 1.6)
            painter.setPen(pen)
            for q in self.quads:
                r = QRectF(q)
                y = r.bottom() - 1 if self.kind == "underline" else r.center().y()
                painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))

    def contextMenuEvent(self, event):
        def delete():
            self.view.doc.delete_annot(self.page_no, self.annot)
            self.view.remove_annotation_item(self.page_no, self)
            self.view.documentModified.emit()

        menu = _build_menu(self.view, False, None, delete)
        menu.exec(event.screenPos())
        event.accept()


class NoteItem(QGraphicsObject):
    def __init__(self, view, page_no: int, annot, point: QPointF, content: str):
        super().__init__()
        self.view = view
        self.page_no = page_no
        self.annot = annot
        self.point = point
        self.content = content
        self.setScale(view.zoom)
        self.setZValue(9)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setToolTip(content)

    SIZE = 16

    def boundingRect(self) -> QRectF:
        s = self.SIZE
        return QRectF(self.point.x(), self.point.y(), s, s)

    def paint(self, painter, option, widget=None):
        r = self.boundingRect()
        painter.setPen(QPen(QColor(40, 40, 40), 1))
        painter.setBrush(QBrush(QColor(255, 224, 102)))
        painter.drawRoundedRect(r, 2, 2)
        for i in range(3):
            y = r.top() + 4 + i * 3
            painter.drawLine(QPointF(r.left() + 3, y), QPointF(r.right() - 3, y))

    def contextMenuEvent(self, event):
        def delete():
            self.view.doc.delete_annot(self.page_no, self.annot)
            self.view.remove_annotation_item(self.page_no, self)
            self.view.documentModified.emit()

        menu = _build_menu(self.view, False, None, delete)
        menu.exec(event.screenPos())
        event.accept()


class FreeTextItem(QGraphicsObject):
    def __init__(self, view, page_no: int, annot, rect: QRectF, text: str, color):
        super().__init__()
        self.view = view
        self.page_no = page_no
        self.annot = annot
        self.rect = rect
        self.text = text
        self.color_tuple = color
        self.setScale(view.zoom)
        self.setZValue(9)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:
        return QRectF(self.rect).adjusted(-2, -2, 2, 2)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(_qcolor(self.color_tuple)))
        font = QFont()
        font.setPointSizeF(11)
        painter.setFont(font)
        painter.drawText(QRectF(self.rect), Qt.TextWordWrap, self.text)

    def contextMenuEvent(self, event):
        def delete():
            self.view.doc.delete_annot(self.page_no, self.annot)
            self.view.remove_annotation_item(self.page_no, self)
            self.view.documentModified.emit()

        menu = _build_menu(self.view, False, None, delete)
        menu.exec(event.screenPos())
        event.accept()


class MeasureItemBase(QGraphicsObject):
    """Shared behaviour for line/perimeter measurement items: a body plus
    draggable vertex handles, so the shape can be "recadré" (nudged into
    place) after being drawn."""

    def __init__(self, view, page_no: int, annot, points: list[QPointF], color, label: str):
        super().__init__()
        self.view = view
        self.page_no = page_no
        self.annot = annot
        self.points = points
        self.color_tuple = color
        self.color = _qcolor(color)
        self.label = label
        self.locked = False
        self.handles: list[VertexHandle] = []
        self.setScale(view.zoom)
        self.setZValue(9)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setCursor(Qt.SizeAllCursor)

    def make_handles(self, page_item) -> list[VertexHandle]:
        zoom = self.view.zoom
        self.handles = []
        for i, pt in enumerate(self.points):
            h = VertexHandle(self, i, parent=page_item)
            h.setPos(pt.x() * zoom, pt.y() * zoom)
            self.handles.append(h)
        return self.handles

    def set_locked(self, locked: bool):
        self.locked = locked
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        for h in self.handles:
            h.set_locked(locked)
        self.update()

    def handle_moving(self, index: int, new_pixel_pos: QPointF):
        zoom = self.view.zoom or 1.0
        self.points[index] = QPointF(new_pixel_pos.x() / zoom, new_pixel_pos.y() / zoom)
        self.prepareGeometryChange()
        self.label = self._compute_label()
        self.update()

    def handle_released(self):
        self._sync_to_pdf()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.locked:
            return
        delta = self.pos()
        if abs(delta.x()) < 0.01 and abs(delta.y()) < 0.01:
            return
        zoom = self.scale() or 1.0
        pt_delta = QPointF(delta.x() / zoom, delta.y() / zoom)
        self.points = [p + pt_delta for p in self.points]
        self.setPos(0, 0)
        for h, p in zip(self.handles, self.points):
            h.setPos(p.x() * self.view.zoom, p.y() * self.view.zoom)
        self.prepareGeometryChange()
        self._sync_to_pdf()
        self.update()

    def contextMenuEvent(self, event):
        def toggle_lock():
            self.set_locked(not self.locked)

        def delete():
            self.view.doc.delete_annot(self.page_no, self.annot)
            self.view.remove_annotation_item(self.page_no, self)
            for h in self.handles:
                if h.scene():
                    h.scene().removeItem(h)
            self.view.documentModified.emit()

        menu = _build_menu(self.view, self.locked, toggle_lock, delete)
        menu.exec(event.screenPos())
        event.accept()

    def _compute_label(self) -> str:
        raise NotImplementedError

    def _sync_to_pdf(self):
        raise NotImplementedError


class MeasureLineItem(MeasureItemBase):
    def _compute_label(self) -> str:
        p1, p2 = self.points
        length_pts = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
        meters = self.view.doc.points_to_meters(length_pts)
        return self.view.doc.format_length(meters) if meters is not None else "?"

    def boundingRect(self) -> QRectF:
        p1, p2 = self.points
        r = QRectF(p1, p2).normalized().adjusted(-6, -6, 6, 6)
        r.setHeight(r.height() + 20)
        return r

    def paint(self, painter, option, widget=None):
        p1, p2 = self.points
        pen = QPen(self.color, 1.4, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length * 5, dx / length * 5
        for pt in (p1, p2):
            painter.drawLine(QPointF(pt.x() - nx, pt.y() - ny), QPointF(pt.x() + nx, pt.y() + ny))
        mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
        self._draw_label(painter, mid)

    def _draw_label(self, painter, pos: QPointF):
        font = QFont()
        font.setPointSizeF(9)
        fm = QFontMetricsF(font)
        text_rect = fm.boundingRect(self.label).adjusted(-3, -2, 3, 2)
        text_rect.moveCenter(QPointF(pos.x(), pos.y() - 8))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
        painter.drawRoundedRect(text_rect, 2, 2)
        painter.setPen(QPen(self.color))
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignCenter, self.label)

    def _sync_to_pdf(self):
        page = self.view.doc.page(self.page_no)
        p1, p2 = self.points
        self.annot = self.view.doc.update_measure_line(
            self.page_no, self.annot, to_pdf(p1, page), to_pdf(p2, page),
            self.color_tuple, self.label,
        )
        self.view.documentModified.emit()


class MeasurePolygonItem(MeasureItemBase):
    def _compute_label(self) -> str:
        perimeter_pts = _polygon_perimeter(self.points)
        area_pts2 = _polygon_area(self.points)
        doc = self.view.doc
        meters = doc.points_to_meters(perimeter_pts)
        if meters is None:
            return "?"
        scale = doc.scale_points_per_meter
        area_m2 = area_pts2 / (scale * scale) if scale else 0.0
        return f"Périmètre {doc.format_length(meters)} · Surface {doc.format_area(area_m2)}"

    def boundingRect(self) -> QRectF:
        if not self.points:
            return QRectF()
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        r = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        r = r.adjusted(-6, -6, 6, 6)
        r.setHeight(r.height() + 24)
        return r

    def paint(self, painter, option, widget=None):
        pen = QPen(self.color, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        fill = QColor(self.color)
        fill.setAlphaF(0.12)
        painter.setBrush(QBrush(fill))
        path = QPainterPath(self.points[0])
        for pt in self.points[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        painter.drawPath(path)
        cx = sum(p.x() for p in self.points) / len(self.points)
        cy = sum(p.y() for p in self.points) / len(self.points)
        self._draw_label(painter, QPointF(cx, cy))

    def _draw_label(self, painter, pos: QPointF):
        font = QFont()
        font.setPointSizeF(9)
        fm = QFontMetricsF(font)
        text_rect = fm.boundingRect(self.label).adjusted(-4, -2, 4, 2)
        text_rect.moveCenter(pos)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
        painter.drawRoundedRect(text_rect, 3, 3)
        painter.setPen(QPen(self.color))
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignCenter, self.label)

    def _sync_to_pdf(self):
        page = self.view.doc.page(self.page_no)
        pdf_points = [to_pdf(p, page) for p in self.points]
        self.annot = self.view.doc.update_measure_polygon(
            self.page_no, self.annot, pdf_points, self.color_tuple, self.label,
        )
        self.view.documentModified.emit()


def _polygon_perimeter(points: list[QPointF]) -> float:
    total = 0.0
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        total += math.hypot(b.x() - a.x(), b.y() - a.y())
    return total


def _polygon_area(points: list[QPointF]) -> float:
    n = len(points)
    s = 0.0
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        s += a.x() * b.y() - b.x() * a.y()
    return abs(s) / 2.0


# -- reconstruction from an existing PyMuPDF annotation ---------------------
def build_item_for_annot(view, page, page_no: int, annot):
    """Create the Qt vector item(s) matching an existing PyMuPDF annotation."""
    kind = annot.type[1]
    subject = (annot.info or {}).get("subject", "")
    color = tuple(annot.colors.get("stroke") or (0, 0, 0))

    if kind in ("Highlight", "Underline", "StrikeOut"):
        verts = annot.vertices or []
        quads = []
        for i in range(0, len(verts), 4):
            group = verts[i:i + 4]
            if len(group) < 4:
                continue
            xs = [p[0] for p in group]
            ys = [p[1] for p in group]
            r = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            corners = [to_visual((x, y), page) for x, y in [(r.left(), r.top()), (r.right(), r.bottom())]]
            quads.append(QRectF(corners[0], corners[1]).normalized())
        kmap = {"Highlight": "highlight", "Underline": "underline", "StrikeOut": "strikeout"}
        return [MarkupItem(view, page_no, annot, kmap[kind], quads, color)]

    if kind == "Square":
        r = to_visual_rect(annot.rect, page)
        fill = tuple(annot.colors.get("fill")) if annot.colors.get("fill") else None
        return [ShapeItem(view, page_no, annot, "rect", r, color, fill, annot.border.get("width") or 1.5)]

    if kind == "Circle":
        r = to_visual_rect(annot.rect, page)
        fill = tuple(annot.colors.get("fill")) if annot.colors.get("fill") else None
        return [ShapeItem(view, page_no, annot, "ellipse", r, color, fill, annot.border.get("width") or 1.5)]

    if kind == "Line":
        verts = annot.vertices or []
        if len(verts) < 2:
            return []
        p1 = to_visual(verts[0], page)
        p2 = to_visual(verts[1], page)
        if subject == "pdfsuite:measure_line":
            label = (annot.info or {}).get("content", "")
            item = MeasureLineItem(view, page_no, annot, [p1, p2], color, label)
            return [item]
        return [ShapeItem(view, page_no, annot, "line", (p1, p2), color, None,
                           annot.border.get("width") or 1.5)]

    if kind == "Ink":
        strokes = []
        for stroke in (annot.vertices or []):
            strokes.append([to_visual(pt, page) for pt in stroke])
        if not strokes:
            return []
        return [ShapeItem(view, page_no, annot, "ink", strokes, color, None,
                           annot.border.get("width") or 2.0)]

    if kind == "Polygon" and subject == "pdfsuite:measure_perimeter":
        verts = annot.vertices or []
        points = [to_visual(pt, page) for pt in verts]
        if len(points) < 3:
            return []
        label = (annot.info or {}).get("content", "")
        return [MeasurePolygonItem(view, page_no, annot, points, color, label)]

    if kind == "FreeText":
        r = to_visual_rect(annot.rect, page)
        text = (annot.info or {}).get("content", "")
        return [FreeTextItem(view, page_no, annot, r, text, color)]

    if kind == "Text":
        r = annot.rect
        pt = to_visual((r.x0, r.y0), page)
        content = (annot.info or {}).get("content", "")
        return [NoteItem(view, page_no, annot, pt, content)]

    return []


class WidgetDisplayItem(QGraphicsObject):
    """Static (non-editable) preview of a form field's current value,
    shown when the interactive "Formulaire" mode is off - otherwise a
    filled-in field would be invisible now that the raster excludes
    annotations/widgets."""

    def __init__(self, view, rect: QRectF, text: str, kind: str):
        super().__init__()
        self.view = view
        self.rect = rect
        self.text = text
        self.kind = kind
        self.setScale(view.zoom)
        self.setZValue(4)

    def boundingRect(self) -> QRectF:
        return QRectF(self.rect)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(QColor(120, 120, 120), 0.75, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect)
        if self.kind == "CheckBox":
            if self.text:
                pen = QPen(QColor(20, 110, 20), 2)
                painter.setPen(pen)
                r = self.rect.adjusted(3, 3, -3, -3)
                painter.drawLine(r.left(), r.center().y(), r.center().x(), r.bottom())
                painter.drawLine(r.center().x(), r.bottom(), r.right(), r.top())
            return
        if not self.text:
            return
        painter.setPen(QPen(QColor(20, 20, 20)))
        font = QFont()
        font.setPointSizeF(max(8.0, self.rect.height() * 0.6))
        painter.setFont(font)
        painter.drawText(self.rect.adjusted(3, 0, -3, 0), Qt.AlignVCenter | Qt.TextSingleLine, self.text)


def build_widget_display_item(view, page, page_no: int, widget):
    rect = to_visual_rect(widget.rect, page)
    kind = widget.field_type_string
    if kind == "CheckBox":
        text = "on" if (widget.field_value and widget.field_value != "Off") else ""
    else:
        text = widget.field_value or ""
    return WidgetDisplayItem(view, rect, text, kind)


def to_visual_rect(rect, page) -> QRectF:
    p1 = to_visual((rect.x0, rect.y0), page)
    p2 = to_visual((rect.x1, rect.y1), page)
    return QRectF(p1, p2).normalized()
