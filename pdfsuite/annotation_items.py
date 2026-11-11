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
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)

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

        self.setScale(view.scene_scale)
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
        if self.kind == "cloud":
            return QRectF(self.geometry).normalized().adjusted(-12, -12, 12, 12)
        if self.kind in ("line", "arrow"):
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
        elif self.kind == "arrow":
            p1, p2 = self.geometry
            painter.drawLine(p1, p2)
            painter.setBrush(QBrush(_qcolor(self.color_tuple)))
            painter.drawPolygon(_arrow_head(p1, p2, 4 + self.width * 3))
        elif self.kind == "cloud":
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(cloud_path(QRectF(self.geometry).normalized()))
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
        if self.kind in ("rect", "ellipse", "cloud"):
            self.geometry = QRectF(self.geometry).translated(d)
        elif self.kind in ("line", "arrow"):
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
        elif self.kind == "cloud":
            pdf_rect = _rect_to_pdf(self.geometry, page)
            self.annot = doc.update_cloud(self.page_no, self.annot, pdf_rect,
                                           self.color_tuple, self.width)
        elif self.kind == "arrow":
            p1, p2 = self.geometry
            self.annot = doc.update_arrow(self.page_no, self.annot,
                                           to_pdf(p1, page), to_pdf(p2, page),
                                           self.color_tuple, self.width)
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


def _arrow_head(p1: QPointF, p2: QPointF, size: float):
    from PySide6.QtGui import QPolygonF
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    base = QPointF(p2.x() - ux * size, p2.y() - uy * size)
    nx, ny = -uy * size * 0.45, ux * size * 0.45
    return QPolygonF([p2, QPointF(base.x() + nx, base.y() + ny),
                      QPointF(base.x() - nx, base.y() - ny)])


def cloud_path(r: QRectF, bump: float = 9.0) -> QPainterPath:
    """Revision-cloud outline: small outward arcs all around ``r``."""
    corners = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
    path = QPainterPath(corners[0])
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        n = max(1, round(length / bump))
        # outward normal (corners go clockwise on screen)
        nx, ny = dy / length, -dx / length
        for k in range(n):
            s1 = QPointF(a.x() + dx * (k + 1) / n, a.y() + dy * (k + 1) / n)
            mid = QPointF(a.x() + dx * (k + 0.5) / n + nx * bump * 0.9,
                          a.y() + dy * (k + 0.5) / n + ny * bump * 0.9)
            path.quadTo(mid, s1)
    return path


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
        self.setScale(view.scene_scale)
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
        self.setScale(view.scene_scale)
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
        self.setScale(view.scene_scale)
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
    """Line / perimeter / area measurement: body + draggable vertex handles
    (to adjust the shape after drawing). Lines are cosmetic (constant
    on-screen width) and the label keeps a constant on-screen size."""

    subject = "pdfsuite:measure_line"
    LABEL_PX = 12          # label font size on screen, whatever the zoom

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
        self.setZValue(9)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setCursor(Qt.SizeAllCursor)

    # -- label geometry (in scene units, depends on the view zoom) ---------
    def _k(self) -> float:
        return 1.0 / max(self.view.zoom, 1e-6)

    def _font(self) -> QFont:
        f = QFont()
        f.setPixelSize(self.LABEL_PX)
        f.setBold(True)
        return f

    def _label_anchor(self) -> QPointF:
        raise NotImplementedError

    def _label_rect(self) -> QRectF:
        fm = QFontMetricsF(self._font())
        k = self._k()
        w = (fm.horizontalAdvance(self.label) + 10) * k
        h = (fm.height() + 4) * k
        c = self._label_anchor()
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h)

    def _draw_label(self, painter):
        r = self._label_rect()
        k = self._k()
        painter.save()
        painter.setPen(QPen(self.color, 0))
        painter.setBrush(QBrush(QColor(255, 255, 255, 235)))
        painter.drawRoundedRect(r, 3 * k, 3 * k)
        painter.translate(r.topLeft())
        painter.scale(k, k)
        painter.setFont(self._font())
        painter.setPen(QPen(self.color))
        painter.drawText(QRectF(0, 0, r.width() / k, r.height() / k), Qt.AlignCenter, self.label)
        painter.restore()

    def _pen(self) -> QPen:
        pen = QPen(self.color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        pen.setCosmetic(True)
        return pen

    def zoom_changed(self):
        self.prepareGeometryChange()
        self.update()

    def _compute_label(self) -> str:
        return self.view.doc.measure_label(self.subject, [(p.x(), p.y()) for p in self.points])

    # -- handles --------------------------------------------------------
    def make_handles(self, page_item) -> list[VertexHandle]:
        self.handles = []
        for i, pt in enumerate(self.points):
            h = VertexHandle(self, i, parent=page_item)
            h.setPos(pt)
            self.handles.append(h)
        return self.handles

    def set_locked(self, locked: bool):
        self.locked = locked
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        for h in self.handles:
            h.set_locked(locked)
        self.update()

    def handle_moving(self, index: int, new_pos: QPointF):
        self.prepareGeometryChange()
        self.points[index] = QPointF(new_pos)
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
        self.prepareGeometryChange()
        self.points = [p + delta for p in self.points]
        self.setPos(0, 0)
        for h, p in zip(self.handles, self.points):
            h.setPos(p)
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

    def _sync_to_pdf(self):
        raise NotImplementedError


class MeasureLineItem(MeasureItemBase):
    subject = "pdfsuite:measure_line"

    def _label_anchor(self) -> QPointF:
        p1, p2 = self.points
        mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = math.hypot(dx, dy) or 1
        nx, ny = dy / length, -dx / length          # perpendicular, "above"
        if ny > 0:
            nx, ny = -nx, -ny
        off = 13 * self._k()
        return QPointF(mid.x() + nx * off, mid.y() + ny * off)

    def boundingRect(self) -> QRectF:
        p1, p2 = self.points
        pad = 8 * self._k()
        return QRectF(p1, p2).normalized().adjusted(-pad, -pad, pad, pad).united(
            self._label_rect().adjusted(-2, -2, 2, 2))

    def paint(self, painter, option, widget=None):
        p1, p2 = self.points
        painter.setPen(self._pen())
        painter.drawLine(p1, p2)
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        length = math.hypot(dx, dy) or 1
        t = 6 * self._k()
        nx, ny = -dy / length * t, dx / length * t
        for pt in (p1, p2):
            painter.drawLine(QPointF(pt.x() - nx, pt.y() - ny), QPointF(pt.x() + nx, pt.y() + ny))
        self._draw_label(painter)

    def _sync_to_pdf(self):
        page = self.view.doc.page(self.page_no)
        p1, p2 = self.points
        self.annot = self.view.doc.update_measure_line(
            self.page_no, self.annot, to_pdf(p1, page), to_pdf(p2, page),
            self.color_tuple, self.label,
        )
        self.view.documentModified.emit()


class MeasurePolygonItem(MeasureItemBase):
    subject = "pdfsuite:measure_perimeter"

    @property
    def is_area(self) -> bool:
        return self.subject.endswith("area")

    def _label_anchor(self) -> QPointF:
        n = len(self.points)
        return QPointF(sum(p.x() for p in self.points) / n, sum(p.y() for p in self.points) / n)

    def boundingRect(self) -> QRectF:
        if not self.points:
            return QRectF()
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        pad = 4 * self._k()
        r = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)).adjusted(-pad, -pad, pad, pad)
        return r.united(self._label_rect().adjusted(-2, -2, 2, 2))

    def paint(self, painter, option, widget=None):
        painter.setPen(self._pen())
        fill = QColor(self.color)
        fill.setAlphaF(0.28 if self.is_area else 0.10)
        painter.setBrush(QBrush(fill))
        path = QPainterPath(self.points[0])
        for pt in self.points[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        painter.drawPath(path)
        self._draw_label(painter)

    def _sync_to_pdf(self):
        page = self.view.doc.page(self.page_no)
        pdf_points = [to_pdf(p, page) for p in self.points]
        self.annot = self.view.doc.update_measure_polygon(
            self.page_no, self.annot, pdf_points, self.color_tuple, self.label,
            self.subject,
        )
        self.view.documentModified.emit()


class DimensionItem(QGraphicsObject):
    """Aligned dimension ("cote"): measured points A and B, extension lines,
    a dimension line offset from AB, oblique ticks and the length written
    along the line. Drag the dimension line to slide it (change the
    offset); drag the A / B handles to move the measured points."""

    subject = "pdfsuite:measure_dimension"
    LABEL_PX = 12
    GAP_PX = 3          # gap between measured point and extension line
    OVER_PX = 6         # extension line overshoot past the dimension line
    TICK_PX = 6

    def __init__(self, view, page_no, annot, a: QPointF, b: QPointF, offset: float,
                 color, label: str = ""):
        super().__init__()
        self.view = view
        self.page_no = page_no
        self.annot = annot
        self.a = QPointF(a)
        self.b = QPointF(b)
        self.offset = offset
        self.color_tuple = tuple(color)
        self.color = _qcolor(color)
        self.label = label or self._compute_label()
        self.locked = False
        self.handles: list[VertexHandle] = []
        self._press = None
        self.setZValue(9)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setCursor(Qt.SizeVerCursor)
        self.setAcceptHoverEvents(True)

    # -- geometry ---------------------------------------------------------
    def _k(self) -> float:
        return 1.0 / max(self.view.zoom, 1e-6)

    def normal(self) -> QPointF:
        dx, dy = self.b.x() - self.a.x(), self.b.y() - self.a.y()
        length = math.hypot(dx, dy) or 1.0
        return QPointF(dy / length, -dx / length)

    def dim_points(self) -> tuple[QPointF, QPointF]:
        n = self.normal()
        return self.a + n * self.offset, self.b + n * self.offset

    def pdf_vertices(self, page):
        a2, b2 = self.dim_points()
        return [to_pdf(p, page) for p in (self.a, a2, b2, self.b)]

    def _compute_label(self) -> str:
        return self.view.doc.measure_label(self.subject, [(self.a.x(), self.a.y()),
                                                          (self.b.x(), self.b.y())])

    def _font(self) -> QFont:
        f = QFont()
        f.setPixelSize(self.LABEL_PX)
        f.setBold(True)
        return f

    def _text_geometry(self):
        """Centre, angle (degrees, kept readable) and size of the text."""
        a2, b2 = self.dim_points()
        ang = math.degrees(math.atan2(b2.y() - a2.y(), b2.x() - a2.x()))
        if ang > 90:
            ang -= 180
        elif ang <= -90:
            ang += 180
        fm = QFontMetricsF(self._font())
        k = self._k()
        w = (fm.horizontalAdvance(self.label) + 8) * k
        h = (fm.height() + 2) * k
        mid = QPointF((a2.x() + b2.x()) / 2, (a2.y() + b2.y()) / 2)
        # text sits on the outer side of the dimension line
        n = self.normal()
        side = 1.0 if self.offset >= 0 else -1.0
        r = math.radians(ang)
        up = QPointF(math.sin(r), -math.cos(r))          # "above" the text line
        if up.x() * n.x() * side + up.y() * n.y() * side < 0:
            up = QPointF(-up.x(), -up.y())
        centre = mid + up * (h / 2 + 1 * k)
        return centre, ang, w, h

    def boundingRect(self) -> QRectF:
        a2, b2 = self.dim_points()
        k = self._k()
        pad = (self.OVER_PX + self.TICK_PX) * k
        r = QRectF(self.a, self.b).normalized().united(QRectF(a2, b2).normalized())
        r = r.adjusted(-pad, -pad, pad, pad)
        c, _ang, w, h = self._text_geometry()
        m = max(w, h) / 2 + 2 * k
        return r.united(QRectF(c.x() - m, c.y() - m, 2 * m, 2 * m))

    def shape(self):
        """Clickable area: the dimension line and the text (not the whole
        box), so the plan underneath stays easy to click."""
        a2, b2 = self.dim_points()
        k = self._k()
        path = QPainterPath()
        n = self.normal()
        t = 5 * k
        poly = [a2 + n * t, b2 + n * t, b2 - n * t, a2 - n * t]
        path.moveTo(poly[0])
        for p in poly[1:]:
            path.lineTo(p)
        path.closeSubpath()
        c, ang, w, h = self._text_geometry()
        tp = QPainterPath()
        tp.addRect(QRectF(-w / 2, -h / 2, w, h))
        from PySide6.QtGui import QTransform
        tr = QTransform()
        tr.translate(c.x(), c.y())
        tr.rotate(ang)
        return path.united(tr.map(tp))

    def paint(self, painter, option, widget=None):
        k = self._k()
        pen = QPen(self.color, 1.4 if not self.isSelected() else 2.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        n = self.normal()
        side = 1.0 if self.offset >= 0 else -1.0
        a2, b2 = self.dim_points()
        gap, over = self.GAP_PX * k, self.OVER_PX * k
        if abs(self.offset) > gap:
            for p, p2 in ((self.a, a2), (self.b, b2)):
                painter.drawLine(p + n * (gap * side), p2 + n * (over * side))
        painter.drawLine(a2, b2)
        # oblique architectural ticks (45°)
        d = b2 - a2
        length = math.hypot(d.x(), d.y()) or 1.0
        u = QPointF(d.x() / length, d.y() / length)
        t = self.TICK_PX * k
        diag = QPointF((u.x() + n.x()) * t / 1.414, (u.y() + n.y()) * t / 1.414)
        for p in (a2, b2):
            painter.drawLine(p - diag, p + diag)
        # text along the line
        c, ang, w, h = self._text_geometry()
        painter.save()
        painter.translate(c)
        painter.rotate(ang)
        painter.scale(k, k)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 215)))
        painter.drawRoundedRect(QRectF(-w / 2 / k, -h / 2 / k, w / k, h / k), 2, 2)
        painter.setFont(self._font())
        painter.setPen(QPen(self.color))
        painter.drawText(QRectF(-w / 2 / k, -h / 2 / k, w / k, h / k), Qt.AlignCenter, self.label)
        painter.restore()

    def zoom_changed(self):
        self.prepareGeometryChange()
        self.update()

    # -- sliding the dimension line ---------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.locked:
            self._press = (event.scenePos(), self.offset)
            self.setSelected(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is None:
            return super().mouseMoveEvent(event)
        start, off0 = self._press
        d = event.scenePos() - start
        n = self.normal()
        self.prepareGeometryChange()
        self.offset = off0 + d.x() * n.x() + d.y() * n.y()
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._press is not None:
            _start, off0 = self._press
            self._press = None
            if abs(self.offset - off0) > 1e-3:
                self._sync_to_pdf()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- A / B handles (VertexHandle protocol) ------------------------------
    def make_handles(self, page_item):
        self.handles = []
        for i, pt in enumerate((self.a, self.b)):
            h = VertexHandle(self, i, parent=page_item)
            h.setPos(pt)
            self.handles.append(h)
        return self.handles

    def handle_moving(self, index: int, new_pos: QPointF):
        self.prepareGeometryChange()
        if index == 0:
            self.a = QPointF(new_pos)
        else:
            self.b = QPointF(new_pos)
        self.label = self._compute_label()
        self.update()

    def handle_released(self):
        self._sync_to_pdf()

    def set_locked(self, locked: bool):
        self.locked = locked
        for h in self.handles:
            h.set_locked(locked)
        self.setCursor(Qt.ArrowCursor if locked else Qt.SizeVerCursor)

    def contextMenuEvent(self, event):
        menu = QMenu()
        act_flip = menu.addAction("Changer de côté")
        act_lock = menu.addAction("Déverrouiller" if self.locked else "Verrouiller")
        menu.addSeparator()
        act_del = menu.addAction("Supprimer")
        chosen = menu.exec(event.screenPos())
        if chosen is act_flip:
            self.prepareGeometryChange()
            self.offset = -self.offset
            self._sync_to_pdf()
        elif chosen is act_lock:
            self.set_locked(not self.locked)
        elif chosen is act_del:
            if self.annot is not None:
                self.view.doc.delete_annot(self.page_no, self.annot)
            self.view.remove_annotation_item(self.page_no, self)
            for h in self.handles:
                if h.scene():
                    h.scene().removeItem(h)
            self.view.documentModified.emit()
        event.accept()

    def _sync_to_pdf(self):
        if self.annot is None:
            return
        page = self.view.doc.page(self.page_no)
        self.label = self._compute_label()
        self.annot = self.view.doc.update_dimension(
            self.page_no, self.annot, self.pdf_vertices(page), self.color_tuple, self.label)
        self.update()
        self.view.documentModified.emit()


def dimension_from_vertices(view, page, page_no, annot, verts, color, label=""):
    """Rebuild a DimensionItem from its stored PDF vertices [A, A', B', B]."""
    a = to_visual(verts[0], page)
    a2 = to_visual(verts[1], page)
    b = to_visual(verts[-1], page)
    item = DimensionItem(view, page_no, annot, a, b, 0.0, color, label)
    n = item.normal()
    item.offset = (a2.x() - a.x()) * n.x() + (a2.y() - a.y()) * n.y()
    item.label = item._compute_label()
    return item


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


class _MovableTextBase(QGraphicsObject):
    """Stamp / callout: whole-item drag, lock and delete."""

    def __init__(self, view, page_no, annot, color, text, fontsize):
        super().__init__()
        self.view = view
        self.page_no = page_no
        self.annot = annot
        self.color_tuple = tuple(color)
        self.color = _qcolor(color)
        self.text = text
        self.fontsize = fontsize
        self.locked = False
        self.setScale(view.scene_scale)
        self.setZValue(9)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setCursor(Qt.SizeAllCursor)

    def _font(self) -> QFont:
        f = QFont("Arial")
        f.setPixelSize(max(1, round(self.fontsize)))
        return f

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if self.locked:
            return
        delta = self.pos()
        if abs(delta.x()) < 0.01 and abs(delta.y()) < 0.01:
            return
        zoom = self.scale() or 1.0
        self.prepareGeometryChange()
        self._translate(QPointF(delta.x() / zoom, delta.y() / zoom))
        self.setPos(0, 0)
        self._sync_to_pdf()
        self.update()

    def contextMenuEvent(self, event):
        def toggle_lock():
            self.locked = not self.locked
            self.setFlag(QGraphicsItem.ItemIsMovable, not self.locked)
            for h in getattr(self, "handles", []):
                h.set_locked(self.locked)

        def delete():
            self.view.doc.delete_annot(self.page_no, self.annot)
            self.view.remove_annotation_item(self.page_no, self)
            for h in getattr(self, "handles", []):
                if h.scene():
                    h.scene().removeItem(h)
            self.view.documentModified.emit()

        menu = _build_menu(self.view, self.locked, toggle_lock, delete)
        menu.exec(event.screenPos())
        event.accept()


class StampItem(_MovableTextBase):
    def __init__(self, view, page_no, annot, rect: QRectF, text, color, fontsize=14):
        super().__init__(view, page_no, annot, color, text, fontsize)
        self.rect = rect

    def boundingRect(self) -> QRectF:
        return QRectF(self.rect).adjusted(-3, -3, 3, 3)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(self.color, 2.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect, 3, 3)
        painter.setFont(self._font())
        painter.drawText(self.rect, Qt.AlignCenter, self.text)
        if self.isSelected():
            painter.setPen(QPen(QColor(47, 111, 237), 1, Qt.DashLine))
            painter.drawRect(self.boundingRect())

    def _translate(self, d: QPointF):
        self.rect = QRectF(self.rect).translated(d)

    def _sync_to_pdf(self):
        page = self.view.doc.page(self.page_no)
        self.annot = self.view.doc.update_stamp(
            self.page_no, self.annot, _rect_to_pdf(self.rect, page),
            self.text, self.color_tuple, self.fontsize)
        self.view.documentModified.emit()


class CalloutItem(_MovableTextBase):
    """Text box + leader line; the arrow tip has its own draggable handle."""

    def __init__(self, view, page_no, annot, target: QPointF, box: QRectF, text, color,
                 fontsize=11):
        super().__init__(view, page_no, annot, color, text, fontsize)
        self.target = target
        self.box = box
        self.handles: list[VertexHandle] = []

    # -- VertexHandle protocol (owner.color / handle_moving / handle_released)
    def make_handles(self, page_item):
        h = VertexHandle(self, 0, parent=page_item)
        h.setPos(self.target.x() * self.view.scene_scale, self.target.y() * self.view.scene_scale)
        self.handles = [h]
        return self.handles

    def handle_moving(self, index, new_pixel_pos: QPointF):
        zoom = self.view.scene_scale or 1.0
        self.prepareGeometryChange()
        self.target = QPointF(new_pixel_pos.x() / zoom, new_pixel_pos.y() / zoom)
        self.update()

    def handle_released(self):
        self._sync_to_pdf()

    def _knee(self) -> QPointF:
        b = self.box
        x = b.left() if self.target.x() < b.left() else (
            b.right() if self.target.x() > b.right() else b.center().x())
        return QPointF(x, b.center().y())

    def boundingRect(self) -> QRectF:
        r = QRectF(self.box).united(QRectF(self.target, self.target))
        return r.adjusted(-8, -8, 8, 8)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(self.color, 1.2))
        knee = self._knee()
        painter.drawLine(knee, self.target)
        painter.setBrush(QBrush(self.color))
        painter.drawPolygon(_arrow_head(knee, self.target, 7))
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawRect(self.box)
        painter.setFont(self._font())
        painter.drawText(self.box.adjusted(3, 2, -3, -2), Qt.TextWordWrap, self.text)
        if self.isSelected():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(47, 111, 237), 1, Qt.DashLine))
            painter.drawRect(self.boundingRect())

    def _translate(self, d: QPointF):
        self.box = QRectF(self.box).translated(d)
        self.target = self.target + d
        for h in self.handles:
            h.setPos(self.target.x() * self.view.scene_scale, self.target.y() * self.view.scene_scale)

    def _sync_to_pdf(self):
        page = self.view.doc.page(self.page_no)
        self.annot = self.view.doc.update_callout(
            self.page_no, self.annot, to_pdf(self.target, page),
            _rect_to_pdf(self.box, page), self.text, self.color_tuple, self.fontsize)
        self.view.documentModified.emit()


# -- reconstruction from an existing PyMuPDF annotation ---------------------
def _freetext_color(doc, annot):
    """Text colour of a FreeText annotation (stored in its /DA string)."""
    try:
        kind, da = doc.doc.xref_get_key(annot.xref, "DA")
        nums = da.split(" rg")[0].split()[-3:]
        return tuple(float(x) for x in nums)
    except Exception:
        return None


def build_item_for_annot(view, page, page_no: int, annot):
    """Create the Qt vector item(s) matching an existing PyMuPDF annotation."""
    import pymupdf
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

    doc = view.doc

    if kind == "Square" and subject == "pdfsuite:cloud":
        g = doc.get_geom(annot)
        rect = pymupdf.Rect(g[:4]) if g and len(g) >= 4 else annot.rect
        r = to_visual_rect(rect, page)
        return [ShapeItem(view, page_no, annot, "cloud", r, color, None,
                          annot.border.get("width") or 1.5)]

    if kind == "Square":
        g = doc.get_geom(annot)
        r = to_visual_rect(pymupdf.Rect(g[:4]) if g and len(g) >= 4 else annot.rect, page)
        fill = tuple(annot.colors.get("fill")) if annot.colors.get("fill") else None
        return [ShapeItem(view, page_no, annot, "rect", r, color, fill, annot.border.get("width") or 1.5)]

    if kind == "Circle":
        g = doc.get_geom(annot)
        r = to_visual_rect(pymupdf.Rect(g[:4]) if g and len(g) >= 4 else annot.rect, page)
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
            item.label = item._compute_label()
            return [item]
        if subject == "pdfsuite:arrow":
            return [ShapeItem(view, page_no, annot, "arrow", (p1, p2), color, None,
                              annot.border.get("width") or 1.8)]
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

    if kind == "PolyLine" and subject == "pdfsuite:measure_dimension":
        verts = annot.vertices or []
        if len(verts) < 4:
            return []
        return [dimension_from_vertices(view, page, page_no, annot, verts, color)]

    if kind == "Polygon" and subject in ("pdfsuite:measure_perimeter", "pdfsuite:measure_area"):
        verts = annot.vertices or []
        points = [to_visual(pt, page) for pt in verts]
        if len(points) < 3:
            return []
        label = (annot.info or {}).get("content", "")
        item = MeasurePolygonItem(view, page_no, annot, points, color, label)
        item.subject = subject
        item.label = item._compute_label()
        return [item]

    if kind == "FreeText" and subject in ("pdfsuite:stamp", "pdfsuite:callout"):
        text = (annot.info or {}).get("content", "")
        g = doc.get_geom(annot)
        tcolor = _freetext_color(doc, annot) or (0, 0, 0)
        if subject == "pdfsuite:stamp":
            rect = pymupdf.Rect(g[:4]) if g and len(g) >= 4 else annot.rect
            size = g[4] if g and len(g) >= 5 else 14
            return [StampItem(view, page_no, annot, to_visual_rect(rect, page), text, tcolor, size)]
        if g and len(g) >= 6:
            target = pymupdf.Point(g[0], g[1])
            box = pymupdf.Rect(g[2:6])
            size = g[6] if len(g) >= 7 else 11
        else:
            verts = annot.vertices or [(annot.rect.x0, annot.rect.y0)]
            target = pymupdf.Point(verts[0])
            box = annot.rect
            size = 11
        return [CalloutItem(view, page_no, annot, to_visual(target, page),
                            to_visual_rect(box, page), text, tcolor, size)]

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
        self.setScale(view.scene_scale)
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
