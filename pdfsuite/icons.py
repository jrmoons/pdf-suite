"""Small vector icons drawn at runtime (no external assets needed)."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath, QFont

SIZE = 28


def _painter(pix: QPixmap, color: QColor, width: float = 1.8) -> QPainter:
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    return p


def _pixmap() -> QPixmap:
    pix = QPixmap(SIZE, SIZE)
    pix.fill(Qt.transparent)
    return pix


def _draw_pan(p: QPainter, r: QRectF, c: QColor):
    cx, cy = r.center().x(), r.center().y()
    p.drawEllipse(QPointF(cx, cy), 1.5, 1.5)
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        x0, y0 = cx + dx * 4, cy + dy * 4
        x1, y1 = cx + dx * 9, cy + dy * 9
        p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        ax, ay = dx * 9 + cx, dy * 9 + cy
        px, py = -dy, dx
        p.drawLine(QPointF(ax, ay), QPointF(ax - dx * 2.4 + px * 2, ay - dy * 2.4 + py * 2))
        p.drawLine(QPointF(ax, ay), QPointF(ax - dx * 2.4 - px * 2, ay - dy * 2.4 - py * 2))


def _draw_text_lines(p: QPainter, r: QRectF, n=3, y0=None, x1=None):
    y0 = r.top() + 5 if y0 is None else y0
    x1 = r.right() - 4 if x1 is None else x1
    step = (r.bottom() - 5 - y0) / max(1, n - 1)
    for i in range(n):
        y = y0 + i * step
        p.drawLine(QPointF(r.left() + 4, y), QPointF(x1, y))


def _draw_highlight(p: QPainter, r: QRectF, c: QColor, accent: QColor):
    p.fillRect(QRectF(r.left() + 3, r.center().y() - 1, r.width() - 6, 7), accent)
    _draw_text_lines(p, r, 3)


def _draw_underline(p: QPainter, r: QRectF, c: QColor, accent: QColor):
    _draw_text_lines(p, r, 3)
    pen = p.pen()
    pen.setColor(accent)
    pen.setWidthF(2.4)
    p.setPen(pen)
    p.drawLine(QPointF(r.left() + 4, r.bottom() - 5), QPointF(r.right() - 4, r.bottom() - 5))


def _draw_strikeout(p: QPainter, r: QRectF, c: QColor, accent: QColor):
    _draw_text_lines(p, r, 3)
    pen = p.pen()
    pen.setColor(accent)
    pen.setWidthF(2.4)
    p.setPen(pen)
    y = r.center().y()
    p.drawLine(QPointF(r.left() + 3, y), QPointF(r.right() - 3, y))


def _draw_freetext(p: QPainter, r: QRectF, c: QColor):
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(r.height() * 0.62))
    p.setFont(f)
    p.drawText(r, Qt.AlignCenter, "T")


def _draw_note(p: QPainter, r: QRectF, c: QColor):
    box = r.adjusted(3, 3, -3, -6)
    path = QPainterPath()
    fold = 5
    path.moveTo(box.left(), box.top())
    path.lineTo(box.right() - fold, box.top())
    path.lineTo(box.right(), box.top() + fold)
    path.lineTo(box.right(), box.bottom())
    path.lineTo(box.left(), box.bottom())
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(box.right() - fold, box.top()), QPointF(box.right() - fold, box.top() + fold))
    p.drawLine(QPointF(box.right() - fold, box.top() + fold), QPointF(box.right(), box.top() + fold))
    _draw_text_lines(p, QRectF(box.left(), box.top(), box.width(), box.height()), 2, box.top() + 8, box.right() - 4)


def _draw_ink(p: QPainter, r: QRectF, c: QColor):
    path = QPainterPath(QPointF(r.left() + 3, r.bottom() - 6))
    path.cubicTo(
        QPointF(r.left() + 8, r.top() + 2),
        QPointF(r.left() + 14, r.bottom() - 2),
        QPointF(r.right() - 6, r.top() + 6),
    )
    p.drawPath(path)
    p.drawEllipse(QPointF(r.right() - 5, r.top() + 5), 1.6, 1.6)


def _draw_rect(p: QPainter, r: QRectF, c: QColor):
    p.drawRoundedRect(r.adjusted(4, 6, -4, -6), 2, 2)


def _draw_ellipse(p: QPainter, r: QRectF, c: QColor):
    p.drawEllipse(r.adjusted(4, 5, -4, -5))


def _draw_select(p: QPainter, r: QRectF, c: QColor):
    path = QPainterPath(QPointF(r.left() + 6, r.top() + 4))
    path.lineTo(QPointF(r.left() + 6, r.bottom() - 4))
    path.lineTo(QPointF(r.left() + 12, r.bottom() - 10))
    path.lineTo(QPointF(r.left() + 16, r.bottom() - 3))
    path.lineTo(QPointF(r.left() + 19, r.bottom() - 5))
    path.lineTo(QPointF(r.left() + 15, r.bottom() - 12))
    path.lineTo(QPointF(r.left() + 21, r.bottom() - 12))
    path.closeSubpath()
    p.setBrush(c)
    p.drawPath(path)
    p.setBrush(Qt.NoBrush)


def _draw_measure_line(p: QPainter, r: QRectF, c: QColor):
    x0, y0 = r.left() + 5, r.bottom() - 6
    x1, y1 = r.right() - 5, r.top() + 6
    p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1
    nx, ny = -dy / length * 3, dx / length * 3
    for t in (0.0, 0.5, 1.0):
        cx, cy = x0 + dx * t, y0 + dy * t
        p.drawLine(QPointF(cx - nx, cy - ny), QPointF(cx + nx, cy + ny))


def _draw_measure_perimeter(p: QPainter, r: QRectF, c: QColor):
    pts = [
        QPointF(r.left() + 6, r.top() + 8),
        QPointF(r.right() - 6, r.top() + 6),
        QPointF(r.right() - 8, r.bottom() - 6),
        QPointF(r.left() + 8, r.bottom() - 8),
    ]
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(c)
    for pt in pts:
        p.drawEllipse(pt, 1.4, 1.4)
    p.setBrush(Qt.NoBrush)


def _draw_line(p: QPainter, r: QRectF, c: QColor):
    p.drawLine(QPointF(r.left() + 5, r.bottom() - 5), QPointF(r.right() - 5, r.top() + 5))
    p.drawEllipse(QPointF(r.left() + 5, r.bottom() - 5), 1.4, 1.4)
    p.drawEllipse(QPointF(r.right() - 5, r.top() + 5), 1.4, 1.4)


def _draw_eraser(p: QPainter, r: QRectF, c: QColor):
    p.save()
    p.translate(r.center())
    p.rotate(-35)
    p.drawRoundedRect(QRectF(-8, -5, 16, 10), 2, 2)
    p.drawLine(QPointF(-2, -5), QPointF(-2, 5))
    p.restore()


def _draw_textedit(p: QPainter, r: QRectF, c: QColor):
    f = QFont()
    f.setPixelSize(int(r.height() * 0.55))
    p.setFont(f)
    p.drawText(r.adjusted(-3, -3, -3, -3), Qt.AlignCenter, "A")
    path = QPainterPath(QPointF(r.right() - 9, r.bottom() - 3))
    path.lineTo(r.right() - 3, r.bottom() - 9)
    path.lineTo(r.right() - 1, r.bottom() - 7)
    path.lineTo(r.right() - 7, r.bottom() - 1)
    path.closeSubpath()
    p.drawPath(path)


def _draw_signature(p: QPainter, r: QRectF, c: QColor):
    path = QPainterPath(QPointF(r.left() + 3, r.bottom() - 8))
    path.cubicTo(
        QPointF(r.left() + 6, r.top() + 4), QPointF(r.left() + 9, r.bottom() - 2),
        QPointF(r.left() + 13, r.top() + 8),
    )
    path.cubicTo(
        QPointF(r.left() + 16, r.top() + 12), QPointF(r.left() + 19, r.top() + 2),
        QPointF(r.right() - 3, r.bottom() - 10),
    )
    p.drawPath(path)
    pen = p.pen()
    pen.setWidthF(2.2)
    p.setPen(pen)
    p.drawLine(QPointF(r.left() + 3, r.bottom() - 4), QPointF(r.right() - 3, r.bottom() - 4))


def _draw_open(p: QPainter, r: QRectF, c: QColor):
    body = r.adjusted(3, 8, -3, -5)
    p.drawRoundedRect(body, 1, 1)
    tab = QPainterPath(QPointF(body.left() + 2, body.top()))
    tab.lineTo(body.left() + 5, body.top() - 4)
    tab.lineTo(body.left() + 13, body.top() - 4)
    tab.lineTo(body.left() + 15, body.top())
    p.drawPath(tab)


def _draw_save(p: QPainter, r: QRectF, c: QColor):
    box = r.adjusted(4, 4, -4, -4)
    p.drawRoundedRect(box, 1, 1)
    p.drawRect(QRectF(box.left() + 3, box.top(), box.width() - 12, 6))
    p.drawRect(QRectF(box.left() + 3, box.bottom() - 8, box.width() - 6, 8))


def _draw_zoom(p: QPainter, r: QRectF, c: QColor, sign: str):
    center = QPointF(r.center().x() - 2, r.center().y() - 2)
    p.drawEllipse(center, 6.5, 6.5)
    p.drawLine(center + QPointF(4.6, 4.6), center + QPointF(9, 9))
    p.drawLine(center + QPointF(-3, 0), center + QPointF(3, 0))
    if sign == "+":
        p.drawLine(center + QPointF(0, -3), center + QPointF(0, 3))


def _draw_color(p: QPainter, r: QRectF, c: QColor):
    p.setBrush(c)
    p.drawEllipse(r.adjusted(5, 5, -5, -5))
    p.setBrush(Qt.NoBrush)


def _draw_form(p: QPainter, r: QRectF, c: QColor):
    p.drawRoundedRect(r.adjusted(4, 4, -4, -4), 2, 2)
    check = QPainterPath(QPointF(r.left() + 8, r.center().y()))
    check.lineTo(QPointF(r.center().x() - 1, r.bottom() - 8))
    check.lineTo(QPointF(r.right() - 7, r.top() + 8))
    p.drawPath(check)


def _draw_page(p: QPainter, r: QRectF, c: QColor, mark: str | None = None):
    box = r.adjusted(6, 4, -6, -4)
    p.drawRoundedRect(box, 1, 1)
    if mark == "+":
        cx, cy = box.center().x(), box.center().y()
        p.drawLine(QPointF(cx - 4, cy), QPointF(cx + 4, cy))
        p.drawLine(QPointF(cx, cy - 4), QPointF(cx, cy + 4))
    elif mark == "x":
        cx, cy = box.center().x(), box.center().y()
        p.drawLine(QPointF(cx - 3.5, cy - 3.5), QPointF(cx + 3.5, cy + 3.5))
        p.drawLine(QPointF(cx - 3.5, cy + 3.5), QPointF(cx + 3.5, cy - 3.5))
    else:
        _draw_text_lines(p, box, 2, box.top() + 6, box.right() - 3)


def _draw_rotate(p: QPainter, r: QRectF, c: QColor, clockwise: bool):
    rect = QRectF(0, 0, 14, 14)
    rect.moveCenter(r.center())
    start_angle = 40 * 16
    span = 260 * 16 if clockwise else -260 * 16
    p.drawArc(rect, start_angle, span)
    end_deg = (40 + 260) if clockwise else (40 - 260)
    rad = math.radians(end_deg)
    ex = rect.center().x() + rect.width() / 2 * math.cos(rad)
    ey = rect.center().y() - rect.height() / 2 * math.sin(rad)
    tangent = rad + (math.pi / 2 if clockwise else -math.pi / 2)
    ax = ex - 4 * math.cos(tangent + 0.5)
    ay = ey + 4 * math.sin(tangent + 0.5)
    bx = ex - 4 * math.cos(tangent - 0.5)
    by = ey + 4 * math.sin(tangent - 0.5)
    p.drawLine(QPointF(ex, ey), QPointF(ax, ay))
    p.drawLine(QPointF(ex, ey), QPointF(bx, by))


def _draw_insert_pdf(p: QPainter, r: QRectF, c: QColor):
    p.drawRoundedRect(QRectF(r.left() + 3, r.top() + 5, 12, 16), 1, 1)
    p.drawRoundedRect(QRectF(r.left() + 9, r.top() + 8, 12, 16), 1, 1)
    cx, cy = r.left() + 15, r.top() + 16
    p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
    p.drawLine(QPointF(cx, cy - 3), QPointF(cx, cy + 3))


def _draw_extract(p: QPainter, r: QRectF, c: QColor):
    box = QRectF(r.left() + 5, r.top() + 8, 14, 16)
    p.drawRoundedRect(box, 1, 1)
    p.drawLine(QPointF(box.right() - 4, box.top() + 2), QPointF(box.right() + 5, box.top() - 5))
    p.drawLine(QPointF(box.right() + 5, box.top() - 5), QPointF(box.right() + 1, box.top() - 5))
    p.drawLine(QPointF(box.right() + 5, box.top() - 5), QPointF(box.right() + 5, box.top() - 1))


def _draw_split(p: QPainter, r: QRectF, c: QColor):
    p.drawRoundedRect(QRectF(r.left() + 2, r.top() + 6, 9, 15), 1, 1)
    p.drawRoundedRect(QRectF(r.right() - 11, r.top() + 6, 9, 15), 1, 1)
    pen = p.pen()
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawLine(QPointF(r.center().x(), r.top() + 3), QPointF(r.center().x(), r.bottom() - 3))


def _draw_password(p: QPainter, r: QRectF, c: QColor):
    body = QRectF(r.left() + 6, r.center().y(), r.width() - 12, r.height() / 2 - 4)
    p.drawRoundedRect(body, 2, 2)
    shackle = QRectF(body.center().x() - 5, body.top() - 10, 10, 12)
    p.drawArc(shackle, 0, 180 * 16)
    p.drawEllipse(body.center(), 1.3, 1.3)


def _draw_theme(p: QPainter, r: QRectF, c: QColor, dark: bool):
    cx, cy = r.center().x(), r.center().y()
    if dark:
        p.drawEllipse(QPointF(cx, cy), 7, 7)
        for i in range(8):
            a = i * math.pi / 4
            x0 = cx + 9 * math.cos(a)
            y0 = cy + 9 * math.sin(a)
            x1 = cx + 12 * math.cos(a)
            y1 = cy + 12 * math.sin(a)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
    else:
        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), 7, 7)
        cut = QPainterPath()
        cut.addEllipse(QPointF(cx + 4, cy - 4), 7, 7)
        p.setBrush(c)
        p.drawPath(path.subtracted(cut))
        p.setBrush(Qt.NoBrush)


_DRAWERS = {
    "pan": _draw_pan,
    "select": _draw_select,
    "measure_line": _draw_measure_line,
    "measure_perimeter": _draw_measure_perimeter,
    "freetext": _draw_freetext,
    "note": _draw_note,
    "ink": _draw_ink,
    "rect": _draw_rect,
    "ellipse": _draw_ellipse,
    "line": _draw_line,
    "eraser": _draw_eraser,
    "textedit": _draw_textedit,
    "signature": _draw_signature,
    "open": _draw_open,
    "save": _draw_save,
    "color": _draw_color,
    "form": _draw_form,
}


# -- icons added with the "plans / chantier" batch ---------------------------
def _draw_arrow(p: QPainter, r: QRectF, c: QColor):
    a, b = QPointF(r.left() + 5, r.bottom() - 5), QPointF(r.right() - 5, r.top() + 5)
    p.drawLine(a, b)
    p.setBrush(c)
    from PySide6.QtGui import QPolygonF
    p.drawPolygon(QPolygonF([b, QPointF(b.x() - 9, b.y() + 2), QPointF(b.x() - 2, b.y() + 9)]))


def _draw_cloud(p: QPainter, r: QRectF, c: QColor):
    from .annotation_items import cloud_path
    p.drawPath(cloud_path(r.adjusted(7, 8, -7, -8), bump=4.5))


def _draw_callout(p: QPainter, r: QRectF, c: QColor):
    box = QRectF(r.left() + 10, r.top() + 4, r.width() - 14, 11)
    p.drawRect(box)
    p.drawLine(QPointF(box.left(), box.center().y()), QPointF(r.left() + 4, r.bottom() - 4))
    p.drawLine(QPointF(box.left() + 3, box.center().y()), QPointF(box.right() - 3, box.center().y()))


def _draw_stamp(p: QPainter, r: QRectF, c: QColor):
    p.drawRoundedRect(QRectF(r.left() + 3, r.top() + 7, r.width() - 6, r.height() - 14), 2, 2)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(8)
    p.setFont(f)
    p.drawText(r, Qt.AlignCenter, "OK")


def _draw_measure_area(p: QPainter, r: QRectF, c: QColor):
    from PySide6.QtGui import QPolygonF
    fill = QColor(c)
    fill.setAlpha(80)
    p.setBrush(fill)
    p.drawPolygon(QPolygonF([QPointF(r.left() + 4, r.top() + 8), QPointF(r.right() - 6, r.top() + 4),
                             QPointF(r.right() - 4, r.bottom() - 6), QPointF(r.left() + 8, r.bottom() - 4)]))
    f = QFont()
    f.setPixelSize(8)
    p.setFont(f)
    p.drawText(r, Qt.AlignCenter, "m²")


def _draw_scale(p: QPainter, r: QRectF, c: QColor):
    y = r.center().y() + 3
    p.drawLine(QPointF(r.left() + 3, y), QPointF(r.right() - 3, y))
    for i in range(5):
        x = r.left() + 3 + i * (r.width() - 6) / 4
        p.drawLine(QPointF(x, y), QPointF(x, y - (6 if i % 2 == 0 else 3)))
    f = QFont()
    f.setPixelSize(8)
    p.setFont(f)
    p.drawText(QRectF(r.left(), r.top() + 2, r.width(), 10), Qt.AlignCenter, "1:50")


def _draw_export(p: QPainter, r: QRectF, c: QColor):
    p.drawRect(QRectF(r.left() + 4, r.top() + 4, 14, 20))
    for i in range(3):
        y = r.top() + 10 + i * 5
        p.drawLine(QPointF(r.left() + 7, y), QPointF(r.left() + 15, y))
    p.drawLine(QPointF(r.left() + 14, r.center().y()), QPointF(r.right() - 3, r.center().y()))
    p.drawLine(QPointF(r.right() - 3, r.center().y()), QPointF(r.right() - 7, r.center().y() - 4))
    p.drawLine(QPointF(r.right() - 3, r.center().y()), QPointF(r.right() - 7, r.center().y() + 4))


def _draw_compare(p: QPainter, r: QRectF, c: QColor):
    p.setPen(QPen(QColor(220, 30, 30), 1.8))
    p.drawRect(QRectF(r.left() + 3, r.top() + 4, 14, 17))
    p.setPen(QPen(QColor(0, 160, 60), 1.8))
    p.drawRect(QRectF(r.left() + 10, r.top() + 8, 14, 17))


def _draw_grid(p: QPainter, r: QRectF, c: QColor):
    for i in range(4):
        x = r.left() + 4 + i * (r.width() - 8) / 3
        y = r.top() + 4 + i * (r.height() - 8) / 3
        p.drawLine(QPointF(x, r.top() + 4), QPointF(x, r.bottom() - 4))
        p.drawLine(QPointF(r.left() + 4, y), QPointF(r.right() - 4, y))


def _draw_snap(p: QPainter, r: QRectF, c: QColor):
    _draw_grid(p, r, c)
    p.setBrush(c)
    p.drawEllipse(QPointF(r.left() + 4 + (r.width() - 8) / 3, r.top() + 4 + (r.height() - 8) / 3), 3.2, 3.2)


def _draw_loupe(p: QPainter, r: QRectF, c: QColor):
    p.drawEllipse(QPointF(r.left() + 11, r.top() + 11), 7.5, 7.5)
    pen = p.pen()
    pen.setWidthF(3)
    p.setPen(pen)
    p.drawLine(QPointF(r.left() + 17, r.top() + 17), QPointF(r.right() - 4, r.bottom() - 4))


def _draw_invert(p: QPainter, r: QRectF, c: QColor):
    p.drawEllipse(r.center(), 9, 9)
    path = QPainterPath()
    path.moveTo(r.center().x(), r.center().y() - 9)
    path.arcTo(QRectF(r.center().x() - 9, r.center().y() - 9, 18, 18), 90, 180)
    path.closeSubpath()
    p.setBrush(c)
    p.drawPath(path)


def _draw_splitview(p: QPainter, r: QRectF, c: QColor):
    p.drawRect(QRectF(r.left() + 3, r.top() + 5, r.width() - 6, r.height() - 10))
    p.drawLine(QPointF(r.center().x(), r.top() + 5), QPointF(r.center().x(), r.bottom() - 5))


def _draw_capture(p: QPainter, r: QRectF, c: QColor):
    pen = p.pen()
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawRect(QRectF(r.left() + 4, r.top() + 4, r.width() - 8, r.height() - 8))
    pen.setStyle(Qt.SolidLine)
    p.setPen(pen)
    p.drawLine(QPointF(r.center().x(), r.center().y() - 4), QPointF(r.center().x(), r.center().y() + 4))
    p.drawLine(QPointF(r.center().x() - 4, r.center().y()), QPointF(r.center().x() + 4, r.center().y()))


def _draw_dimension(p: QPainter, r: QRectF, c: QColor):
    y = r.top() + 10
    p.drawLine(QPointF(r.left() + 5, r.bottom() - 5), QPointF(r.left() + 5, y - 3))
    p.drawLine(QPointF(r.right() - 5, r.bottom() - 5), QPointF(r.right() - 5, y - 3))
    p.drawLine(QPointF(r.left() + 5, y), QPointF(r.right() - 5, y))
    for x in (r.left() + 5, r.right() - 5):
        p.drawLine(QPointF(x - 3, y + 3), QPointF(x + 3, y - 3))
    f = QFont()
    f.setPixelSize(8)
    p.setFont(f)
    p.drawText(QRectF(r.left(), y + 2, r.width(), 10), Qt.AlignCenter, "3,25")


def _draw_undo(p: QPainter, r: QRectF, c: QColor, mirror: bool = False):
    path = QPainterPath()
    if not mirror:
        path.moveTo(r.left() + 7, r.top() + 11)
        path.cubicTo(r.left() + 14, r.top() + 4, r.right() - 3, r.top() + 10, r.right() - 6, r.bottom() - 6)
        p.drawPath(path)
        p.drawLine(QPointF(r.left() + 7, r.top() + 11), QPointF(r.left() + 7, r.top() + 4))
        p.drawLine(QPointF(r.left() + 7, r.top() + 11), QPointF(r.left() + 14, r.top() + 12))
    else:
        path.moveTo(r.right() - 7, r.top() + 11)
        path.cubicTo(r.right() - 14, r.top() + 4, r.left() + 3, r.top() + 10, r.left() + 6, r.bottom() - 6)
        p.drawPath(path)
        p.drawLine(QPointF(r.right() - 7, r.top() + 11), QPointF(r.right() - 7, r.top() + 4))
        p.drawLine(QPointF(r.right() - 7, r.top() + 11), QPointF(r.right() - 14, r.top() + 12))


def _draw_room(p: QPainter, r: QRectF, c: QColor):
    from PySide6.QtGui import QPolygonF
    fill = QColor(c)
    fill.setAlpha(60)
    p.setBrush(fill)
    p.drawPolygon(QPolygonF([QPointF(r.left() + 4, r.top() + 5), QPointF(r.right() - 4, r.top() + 5),
                             QPointF(r.right() - 4, r.bottom() - 9), QPointF(r.center().x(), r.bottom() - 9),
                             QPointF(r.center().x(), r.bottom() - 4), QPointF(r.left() + 4, r.bottom() - 4)]))
    p.setBrush(c)
    p.drawEllipse(QPointF(r.center().x() - 3, r.center().y() - 2), 2.2, 2.2)


_DRAWERS.update({
    "room": _draw_room,
    "undo": _draw_undo,
    "redo": lambda p, r, c: _draw_undo(p, r, c, True),
    "dimension": _draw_dimension,
    "arrow": _draw_arrow,
    "cloud": _draw_cloud,
    "callout": _draw_callout,
    "stamp": _draw_stamp,
    "measure_area": _draw_measure_area,
    "scale": _draw_scale,
    "export": _draw_export,
    "compare": _draw_compare,
    "grid": _draw_grid,
    "snap": _draw_snap,
    "loupe": _draw_loupe,
    "invert": _draw_invert,
    "splitview": _draw_splitview,
    "capture": _draw_capture,
})


def make_icon(kind: str, color: QColor, accent: QColor | None = None) -> QIcon:
    pix = _pixmap()
    r = QRectF(0, 0, SIZE, SIZE)
    p = _painter(pix, color)
    accent = accent or color
    try:
        if kind == "highlight":
            _draw_highlight(p, r, color, accent)
        elif kind == "underline":
            _draw_underline(p, r, color, accent)
        elif kind == "strikeout":
            _draw_strikeout(p, r, color, accent)
        elif kind == "zoomin":
            _draw_zoom(p, r, color, "+")
        elif kind == "zoomout":
            _draw_zoom(p, r, color, "-")
        elif kind in ("insertblank",):
            _draw_page(p, r, color, "+")
        elif kind == "deletepages":
            _draw_page(p, r, color, "x")
        elif kind == "rotateleft":
            _draw_rotate(p, r, color, False)
        elif kind == "rotateright":
            _draw_rotate(p, r, color, True)
        elif kind == "insertpdf":
            _draw_insert_pdf(p, r, color)
        elif kind == "extract":
            _draw_extract(p, r, color)
        elif kind == "split":
            _draw_split(p, r, color)
        elif kind == "password":
            _draw_password(p, r, color)
        elif kind == "theme_dark":
            _draw_theme(p, r, color, True)
        elif kind == "theme_light":
            _draw_theme(p, r, color, False)
        elif kind in _DRAWERS:
            _DRAWERS[kind](p, r, color)
    finally:
        p.end()
    return QIcon(pix)
