"""Visual comparison of two versions of a plan (old index vs new index).

Each page of both documents is rendered, tinted, and the two images are
multiplied together:

* lines present in both versions stay dark grey/black,
* lines only in the OLD version come out red (removed),
* lines only in the NEW version come out green (added).

Uses Qt image composition only (no extra library), so it stays fast and
keeps the .exe light. The two plans must share the same layout (same
sheet, same position); pages of a different size are scaled to the old
one.
"""
from __future__ import annotations

import pymupdf
from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

RED = QColor(220, 30, 30)
GREEN = QColor(0, 160, 60)
MAX_PIXELS = 5000          # longest side of the rendered comparison


def _render(page: pymupdf.Page, width_px: int, height_px: int) -> QImage:
    zoom_x = width_px / page.rect.width
    zoom_y = height_px / page.rect.height
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom_x, zoom_y), alpha=False, annots=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
    if img.width() != width_px or img.height() != height_px:
        img = img.scaled(width_px, height_px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return img.convertToFormat(QImage.Format_RGB32)


def _tint(img: QImage, color: QColor) -> QImage:
    """Black ink -> ``color``, white paper stays white."""
    out = QImage(img)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_Screen)
    p.fillRect(out.rect(), color)
    p.end()
    return out


def compare_pages(old_page: pymupdf.Page, new_page: pymupdf.Page, dpi: int = 150) -> QImage:
    w = old_page.rect.width * dpi / 72
    h = old_page.rect.height * dpi / 72
    k = min(1.0, MAX_PIXELS / max(w, h))
    w, h = max(1, int(w * k)), max(1, int(h * k))
    old_img = _render(old_page, w, h)
    new_img = _render(new_page, w, h)
    # red old lines x green new lines: both -> dark, old only -> red,
    # new only -> green, paper white x white -> white.
    result = _tint(old_img, RED)
    p = QPainter(result)
    p.setCompositionMode(QPainter.CompositionMode_Multiply)
    p.drawImage(0, 0, _tint(new_img, GREEN))
    p.end()
    return result


def _png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def build_comparison_pdf(old_doc, new_doc: pymupdf.Document,
                         old_name: str, new_name: str, dpi: int = 150,
                         progress=None) -> tuple[bytes, int]:
    """``old_doc`` is the open PdfDocument (pages fetched through its page
    cache, see pdf_document.py); ``new_doc`` a plain pymupdf document.
    Returns (pdf bytes, number of pages compared)."""
    out = pymupdf.open()
    n = min(old_doc.page_count, new_doc.page_count)
    for i in range(n):
        if progress is not None and not progress(i, n):
            break
        old_page, new_page = old_doc.page(i), new_doc[i]
        img = compare_pages(old_page, new_page, dpi)
        w, h = old_page.rect.width, old_page.rect.height
        banner = 34
        page = out.new_page(width=w, height=h + banner)
        page.insert_image(pymupdf.Rect(0, banner, w, h + banner), stream=_png_bytes(img))
        page.draw_rect(pymupdf.Rect(0, 0, w, banner), color=None, fill=(0.95, 0.95, 0.95))
        page.insert_text((10, 14), f"Comparaison page {i + 1}", fontsize=10, color=(0, 0, 0))
        page.insert_text((10, 28), f"Rouge = supprimé (seulement dans {old_name})",
                         fontsize=8, color=(0.86, 0.12, 0.12))
        page.insert_text((w / 2, 28), f"Vert = ajouté (seulement dans {new_name})",
                         fontsize=8, color=(0, 0.6, 0.24))
    data = out.tobytes(deflate=True, garbage=3)
    out.close()
    return data, n
