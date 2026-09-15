"""Wraps a pymupdf.Document with the mutating operations the app needs.

PyMuPDF invalidates an annotation if the ``Page`` python wrapper it was
created from gets garbage-collected while another wrapper for the same
page number is still in use, so every page must be fetched through a
single cached wrapper (``self.page``) rather than repeated ``doc[i]``.
"""
from __future__ import annotations

import pymupdf


class PdfDocument:
    def __init__(self, path: str | None = None, password: str | None = None):
        self.path: str | None = path
        self.dirty: bool = False
        self.doc: pymupdf.Document = pymupdf.open(path) if path else pymupdf.open()
        if self.doc.needs_pass:
            if not password or not self.doc.authenticate(password):
                raise PermissionError("password-required")
        self._page_cache: dict[int, pymupdf.Page] = {}
        # Real-world scale of the plan, in PDF points per metre. Set once
        # by calibrating a measurement tool, then reused for every
        # subsequent measurement in this session.
        self.scale_points_per_meter: float | None = None

    def _invalidate_pages(self):
        self._page_cache = {}

    # -- measurement scale ----------------------------------------------
    def points_to_meters(self, points: float) -> float | None:
        if not self.scale_points_per_meter:
            return None
        return points / self.scale_points_per_meter

    @staticmethod
    def format_length(meters: float) -> str:
        if meters < 1:
            return f"{meters * 100:.1f} cm"
        return f"{meters:.2f} m"

    @staticmethod
    def format_area(square_meters: float) -> str:
        return f"{square_meters:.2f} m²"

    # -- basic info -------------------------------------------------
    @property
    def page_count(self) -> int:
        return self.doc.page_count

    def page(self, index: int) -> pymupdf.Page:
        pg = self._page_cache.get(index)
        if pg is None:
            pg = self.doc[index]
            self._page_cache[index] = pg
        return pg

    def page_size(self, index: int) -> tuple[float, float]:
        r = self.page(index).rect
        return r.width, r.height

    def visual_size(self, index: int) -> tuple[float, float]:
        """Page size in points as actually rendered (rotation applied)."""
        r = self.page(index).bound()
        return r.width, r.height

    # -- render -------------------------------------------------------
    def render_page(self, index: int, zoom: float) -> pymupdf.Pixmap:
        # Annotations are drawn separately as interactive vector items in
        # the Qt scene, so the raster only needs the page's own content.
        # This also means adding/moving an annotation never requires
        # re-rasterising the page (the previous source of the UI lag).
        page = self.page(index)
        mat = pymupdf.Matrix(zoom, zoom)
        return page.get_pixmap(matrix=mat, alpha=False, annots=False)

    def thumbnail(self, index: int, max_dim: int = 140) -> pymupdf.Pixmap:
        page = self.page(index)
        w, h = page.rect.width, page.rect.height
        zoom = max_dim / max(w, h)
        return self.render_page(index, zoom)

    # -- save -----------------------------------------------------------
    def save(self, path: str | None = None):
        target = path or self.path
        if not target:
            raise ValueError("no path given")
        self.doc.save(target, incremental=False, deflate=True, garbage=3)
        self.path = target
        self.dirty = False

    def close(self):
        self.doc.close()

    def mark_dirty(self):
        self.dirty = True

    # -- page manipulation --------------------------------------------
    def insert_blank_page(self, index: int, width: float = 595, height: float = 842):
        self.doc.new_page(pno=index, width=width, height=height)
        self._invalidate_pages()
        self.mark_dirty()

    def delete_pages(self, indices: list[int]):
        for i in sorted(indices, reverse=True):
            self.doc.delete_page(i)
        self._invalidate_pages()
        self.mark_dirty()

    def rotate_page(self, index: int, degrees: int):
        page = self.page(index)
        page.set_rotation((page.rotation + degrees) % 360)
        self.mark_dirty()

    def move_page(self, src: int, dst: int):
        self.doc.move_page(src, dst)
        self._invalidate_pages()
        self.mark_dirty()

    def reorder_pages(self, new_order: list[int]):
        """new_order[i] = old page index that should end up at position i."""
        self.doc.select(new_order)
        self._invalidate_pages()
        self.mark_dirty()

    def insert_pdf(self, other_path: str, at_index: int | None = None,
                    from_page: int | None = None, to_page: int | None = None):
        src = pymupdf.open(other_path)
        try:
            self.doc.insert_pdf(
                src,
                from_page=from_page if from_page is not None else -1,
                to_page=to_page if to_page is not None else -1,
                start_at=at_index if at_index is not None else -1,
            )
        finally:
            src.close()
        self._invalidate_pages()
        self.mark_dirty()

    def extract_pages(self, indices: list[int], out_path: str):
        new_doc = pymupdf.open()
        for i in indices:
            new_doc.insert_pdf(self.doc, from_page=i, to_page=i)
        new_doc.save(out_path, deflate=True, garbage=3)
        new_doc.close()

    def split_at(self, out_dir: str, base_name: str, ranges: list[tuple[int, int]]):
        """ranges: list of (start, end) inclusive, 0-based."""
        import os
        paths = []
        for n, (a, b) in enumerate(ranges, start=1):
            new_doc = pymupdf.open()
            new_doc.insert_pdf(self.doc, from_page=a, to_page=b)
            out_path = os.path.join(out_dir, f"{base_name}_part{n}.pdf")
            new_doc.save(out_path, deflate=True, garbage=3)
            new_doc.close()
            paths.append(out_path)
        return paths

    # -- annotations ------------------------------------------------------
    def add_highlight(self, index: int, quads, color=(1, 0.85, 0.2)):
        annot = self.page(index).add_highlight_annot(quads)
        annot.set_colors(stroke=color)
        annot.update()
        self.mark_dirty()
        return annot

    def add_underline(self, index: int, quads, color=(0.1, 0.4, 1)):
        annot = self.page(index).add_underline_annot(quads)
        annot.set_colors(stroke=color)
        annot.update()
        self.mark_dirty()
        return annot

    def add_strikeout(self, index: int, quads, color=(1, 0.1, 0.1)):
        annot = self.page(index).add_strikeout_annot(quads)
        annot.set_colors(stroke=color)
        annot.update()
        self.mark_dirty()
        return annot

    def add_freetext(self, index: int, rect, text, fontsize=12, color=(0, 0, 0)):
        annot = self.page(index).add_freetext_annot(
            rect, text, fontsize=fontsize, text_color=color, fill_color=None
        )
        annot.update()
        self.mark_dirty()
        return annot

    def add_note(self, index: int, point, text):
        annot = self.page(index).add_text_annot(point, text)
        annot.update()
        self.mark_dirty()
        return annot

    def add_ink(self, index: int, strokes, color=(1, 0, 0), width=2.0):
        strokes = [[(p.x, p.y) if hasattr(p, "x") else tuple(p) for p in s] for s in strokes]
        annot = self.page(index).add_ink_annot(strokes)
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
        annot.update()
        self.mark_dirty()
        return annot

    def add_rect(self, index: int, rect, color=(1, 0, 0), fill=None, width=1.5):
        annot = self.page(index).add_rect_annot(rect)
        annot.set_colors(stroke=color, fill=fill)
        annot.set_border(width=width)
        annot.update()
        self.mark_dirty()
        return annot

    def add_ellipse(self, index: int, rect, color=(1, 0, 0), fill=None, width=1.5):
        annot = self.page(index).add_circle_annot(rect)
        annot.set_colors(stroke=color, fill=fill)
        annot.set_border(width=width)
        annot.update()
        self.mark_dirty()
        return annot

    def add_line(self, index: int, p1, p2, color=(1, 0, 0), width=1.5):
        annot = self.page(index).add_line_annot(p1, p2)
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
        annot.update()
        self.mark_dirty()
        return annot

    _SKIP_ANNOT_TYPES = ("Popup", "Widget", "Link")

    def annotations(self, index: int):
        page = self.page(index)
        return [a for a in (page.annots() or []) if a.type[1] not in self._SKIP_ANNOT_TYPES]

    def delete_annot(self, index: int, annot):
        self.page(index).delete_annot(annot)
        self.mark_dirty()

    # PyMuPDF has no "move this annotation" API: the standard way to
    # change an existing annotation's geometry is to delete it and add a
    # new one with the same style. These helpers do that for interactive
    # (draggable) shapes, keeping colour/border/label intact.
    def update_rect(self, index: int, old_annot, rect, color, fill=None, width=1.5):
        self.delete_annot(index, old_annot)
        return self.add_rect(index, rect, color, fill, width)

    def update_ellipse(self, index: int, old_annot, rect, color, fill=None, width=1.5):
        self.delete_annot(index, old_annot)
        return self.add_ellipse(index, rect, color, fill, width)

    def update_line(self, index: int, old_annot, p1, p2, color, width=1.5):
        self.delete_annot(index, old_annot)
        return self.add_line(index, p1, p2, color, width)

    def update_ink(self, index: int, old_annot, strokes, color, width=2.0):
        self.delete_annot(index, old_annot)
        return self.add_ink(index, strokes, color, width)

    # -- measurement annotations ------------------------------------------
    def add_measure_line(self, index: int, p1, p2, color, label: str):
        annot = self.page(index).add_line_annot(p1, p2)
        annot.set_colors(stroke=color)
        annot.set_border(width=1.5)
        annot.set_info(subject="pdfsuite:measure_line", content=label)
        annot.update()
        self.mark_dirty()
        return annot

    def update_measure_line(self, index: int, old_annot, p1, p2, color, label: str):
        self.delete_annot(index, old_annot)
        return self.add_measure_line(index, p1, p2, color, label)

    def add_measure_polygon(self, index: int, points, color, label: str):
        annot = self.page(index).add_polygon_annot(points)
        annot.set_colors(stroke=color)
        annot.set_border(width=1.5)
        annot.set_info(subject="pdfsuite:measure_perimeter", content=label)
        annot.update()
        self.mark_dirty()
        return annot

    def update_measure_polygon(self, index: int, old_annot, points, color, label: str):
        self.delete_annot(index, old_annot)
        return self.add_measure_polygon(index, points, color, label)

    def delete_annot_at(self, index: int, point) -> bool:
        page = self.page(index)
        for annot in page.annots() or []:
            if annot.rect.contains(point):
                page.delete_annot(annot)
                self.mark_dirty()
                return True
        return False

    def words_in_rect(self, index: int, rect):
        words = self.page(index).get_text("words")
        out = []
        for w in words:
            wrect = pymupdf.Rect(w[:4])
            if wrect.intersects(rect):
                out.append(wrect)
        return out

    # -- text block editing -------------------------------------------
    def text_blocks(self, index: int):
        return self.page(index).get_text("dict")["blocks"]

    def replace_text_in_rect(self, index: int, rect, new_text: str,
                              fontsize: float, color=(0, 0, 0), fontname="helv"):
        page = self.page(index)
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

        # Let the box grow to the right/below (bounded by the page) so the
        # replacement text has room, then shrink the font if it still
        # doesn't fit rather than silently dropping characters.
        page_rect = page.rect
        box = pymupdf.Rect(
            rect.x0, rect.y0,
            max(rect.x1, page_rect.x1 - 18),
            max(rect.y1, page_rect.y1 - 18),
        )
        size = fontsize
        while size >= 6:
            rc = page.insert_textbox(
                box, new_text, fontsize=size, fontname=fontname,
                color=color, align=0,
            )
            if rc >= 0:
                break
            size -= 1
        self.mark_dirty()

    # -- security ---------------------------------------------------------
    def set_password(self, user_pw: str, owner_pw: str | None = None):
        perm = int(
            pymupdf.PDF_PERM_ACCESSIBILITY
            | pymupdf.PDF_PERM_PRINT
            | pymupdf.PDF_PERM_COPY
            | pymupdf.PDF_PERM_ANNOTATE
        )
        encrypt = pymupdf.PDF_ENCRYPT_AES_256
        self._pending_encrypt = dict(
            owner_pw=owner_pw or user_pw, user_pw=user_pw,
            permissions=perm, encryption=encrypt,
        )
        self.mark_dirty()

    def save_with_pending_encryption(self, path: str):
        kwargs = getattr(self, "_pending_encrypt", None)
        if kwargs:
            self.doc.save(path, deflate=True, garbage=3, **kwargs)
        else:
            self.doc.save(path, deflate=True, garbage=3)
        self.path = path
        self.dirty = False

    # -- forms --------------------------------------------------------
    def widgets(self, index: int):
        return list(self.page(index).widgets() or [])
