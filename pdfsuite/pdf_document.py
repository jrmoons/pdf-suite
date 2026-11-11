"""Wraps a pymupdf.Document with the mutating operations the app needs.

PyMuPDF invalidates an annotation if the ``Page`` python wrapper it was
created from gets garbage-collected while another wrapper for the same
page number is still in use, so every page must be fetched through a
single cached wrapper (``self.page``) rather than repeated ``doc[i]``.
"""
from __future__ import annotations

import pymupdf


SCALE_KEY = "PDFSuiteScale"   # custom catalog key: plan scale (points per metre)
GEOM_KEY = "PDFSuiteGeom"     # custom annot key: our own exact geometry

# 1 metre of paper expressed in PDF points (72 pt per inch).
POINTS_PER_PAPER_METER = 72 / 0.0254

STAMP_COLORS = {
    "APPROUVÉ": (0.0, 0.5, 0.15),
    "BON POUR EXÉCUTION": (0.0, 0.5, 0.15),
    "VU": (0.1, 0.35, 0.85),
    "À REVOIR": (0.9, 0.5, 0.0),
    "REFUSÉ": (0.85, 0.1, 0.1),
}


class PdfDocument:
    def __init__(self, path: str | None = None, password: str | None = None,
                 data: bytes | None = None, title: str | None = None):
        self.path: str | None = path
        # The file the user opened. "Enregistrer" never writes to it.
        self.original_path: str | None = path
        self.title: str | None = title
        self.dirty: bool = False
        if data is not None:
            self.doc = pymupdf.open("pdf", data)
            self.dirty = True
        else:
            self.doc = pymupdf.open(path) if path else pymupdf.open()
        if self.doc.needs_pass:
            if not password or not self.doc.authenticate(password):
                raise PermissionError("password-required")
        self._page_cache: dict[int, pymupdf.Page] = {}
        # Real-world scale of the plan, in PDF points per metre. Read from
        # the file when it was saved by PDF Suite, otherwise asked once.
        self._scale: float | None = self._read_scale()

    def _invalidate_pages(self):
        self._page_cache = {}

    # -- measurement scale ----------------------------------------------
    def _read_scale(self) -> float | None:
        try:
            kind, val = self.doc.xref_get_key(self.doc.pdf_catalog(), SCALE_KEY)
            if kind in ("float", "int"):
                v = float(val)
                return v if v > 0 else None
        except Exception:
            pass
        return None

    @property
    def scale_points_per_meter(self) -> float | None:
        return self._scale

    @scale_points_per_meter.setter
    def scale_points_per_meter(self, value: float | None):
        """Also written into the PDF so the scale survives a reopen."""
        self._scale = value if value and value > 0 else None
        try:
            cat = self.doc.pdf_catalog()
            self.doc.xref_set_key(cat, SCALE_KEY,
                                  f"{self._scale:.6f}" if self._scale else "null")
        except Exception:
            pass
        self.mark_dirty()

    def set_ratio_scale(self, ratio: float):
        """Plan drawn at 1:ratio (e.g. 50 for 1:50)."""
        self.scale_points_per_meter = POINTS_PER_PAPER_METER / ratio

    def scale_description(self) -> str:
        if not self._scale:
            return "Échelle : non définie"
        ratio = POINTS_PER_PAPER_METER / self._scale
        if abs(ratio - round(ratio)) < 0.05:
            return f"Échelle 1:{round(ratio)}"
        return f"Échelle 1:{ratio:.1f}"

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
    def is_original(self, path: str) -> bool:
        import os
        if not self.original_path:
            return False
        return os.path.normcase(os.path.abspath(path)) == os.path.normcase(
            os.path.abspath(self.original_path))

    def save(self, path: str | None = None):
        target = path or self.path
        if not target:
            raise ValueError("no path given")
        if self.is_original(target):
            raise PermissionError("Le fichier d'origine n'est jamais écrasé.")
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
        rect = pymupdf.Rect(rect).normalize()
        annot = self.page(index).add_rect_annot(rect)
        annot.set_colors(stroke=color, fill=fill)
        annot.set_border(width=width)
        annot.update()
        # exact shape, so that moving it does not make it grow by the border
        self.set_geom(annot, (rect.x0, rect.y0, rect.x1, rect.y1))
        self.mark_dirty()
        return annot

    def add_ellipse(self, index: int, rect, color=(1, 0, 0), fill=None, width=1.5):
        rect = pymupdf.Rect(rect).normalize()
        annot = self.page(index).add_circle_annot(rect)
        annot.set_colors(stroke=color, fill=fill)
        annot.set_border(width=width)
        annot.update()
        # exact shape, so that moving it does not make it grow by the border
        self.set_geom(annot, (rect.x0, rect.y0, rect.x1, rect.y1))
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

    def add_measure_polygon(self, index: int, points, color, label: str,
                            subject: str = "pdfsuite:measure_perimeter"):
        annot = self.page(index).add_polygon_annot(points)
        annot.set_colors(stroke=color, fill=color if subject.endswith("area") else None)
        if subject.endswith("area"):
            annot.set_opacity(0.35)
        annot.set_border(width=1.5)
        annot.set_info(subject=subject, content=label)
        annot.update()
        self.mark_dirty()
        return annot

    def update_measure_polygon(self, index: int, old_annot, points, color, label: str,
                               subject: str = "pdfsuite:measure_perimeter"):
        self.delete_annot(index, old_annot)
        return self.add_measure_polygon(index, points, color, label, subject)

    # -- custom geometry (exact shape we drew, independent of the
    # -- annotation rectangle that the PDF library may enlarge) ----------
    def set_geom(self, annot, values):
        self.doc.xref_set_key(annot.xref, GEOM_KEY,
                              "[" + " ".join(f"{v:.3f}" for v in values) + "]")

    def get_geom(self, annot) -> list[float] | None:
        try:
            kind, val = self.doc.xref_get_key(annot.xref, GEOM_KEY)
            if kind == "array":
                return [float(x) for x in val.strip("[]").split()]
        except Exception:
            pass
        return None

    # -- review markup: cloud / arrow / callout / stamp -------------------
    def add_cloud(self, index: int, rect, color, width=1.5):
        rect = pymupdf.Rect(rect).normalize()
        annot = self.page(index).add_rect_annot(rect)
        annot.set_colors(stroke=color)
        annot.set_border(width=width, clouds=2)
        annot.set_info(subject="pdfsuite:cloud")
        annot.update()
        self.set_geom(annot, (rect.x0, rect.y0, rect.x1, rect.y1))
        self.mark_dirty()
        return annot

    def update_cloud(self, index: int, old_annot, rect, color, width=1.5):
        self.delete_annot(index, old_annot)
        return self.add_cloud(index, rect, color, width)

    def add_arrow(self, index: int, p1, p2, color, width=1.8):
        annot = self.page(index).add_line_annot(p1, p2)
        annot.set_colors(stroke=color, fill=color)
        annot.set_border(width=width)
        annot.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_CLOSED_ARROW)
        annot.set_info(subject="pdfsuite:arrow")
        annot.update()
        self.mark_dirty()
        return annot

    def update_arrow(self, index: int, old_annot, p1, p2, color, width=1.8):
        self.delete_annot(index, old_annot)
        return self.add_arrow(index, p1, p2, color, width)

    def add_callout(self, index: int, target, box, text: str, color, fontsize=11):
        """Text box with a leader line pointing at ``target``."""
        box = pymupdf.Rect(box).normalize()
        knee = pymupdf.Point(box.x0 if target.x < box.x0 else
                             (box.x1 if target.x > box.x1 else (box.x0 + box.x1) / 2),
                             (box.y0 + box.y1) / 2)
        annot = self.page(index).add_freetext_annot(
            box, text, fontsize=fontsize, text_color=color, border_width=1,
            fill_color=(1, 1, 1), callout=(target, knee),
            line_end=pymupdf.PDF_ANNOT_LE_OPEN_ARROW,
        )
        annot.set_info(subject="pdfsuite:callout", content=text)
        annot.update()
        self.set_geom(annot, (target.x, target.y, box.x0, box.y0, box.x1, box.y1, fontsize))
        self.mark_dirty()
        return annot

    def update_callout(self, index: int, old_annot, target, box, text, color, fontsize=11):
        self.delete_annot(index, old_annot)
        return self.add_callout(index, target, box, text, color, fontsize)

    def add_stamp(self, index: int, rect, text: str, color, fontsize=14):
        rect = pymupdf.Rect(rect).normalize()
        annot = self.page(index).add_freetext_annot(
            rect, text, fontsize=fontsize, text_color=color, border_width=2.5,
            align=pymupdf.TEXT_ALIGN_CENTER,
        )
        annot.set_info(subject="pdfsuite:stamp", content=text)
        annot.update()
        self.set_geom(annot, (rect.x0, rect.y0, rect.x1, rect.y1, fontsize))
        self.mark_dirty()
        return annot

    def update_stamp(self, index: int, old_annot, rect, text, color, fontsize=14):
        self.delete_annot(index, old_annot)
        return self.add_stamp(index, rect, text, color, fontsize)

    # -- measurement report ----------------------------------------------
    def measurements(self) -> list[dict]:
        """Every PDF Suite measurement of the document, with values
        recomputed from the geometry using the current scale."""
        import math
        rows = []
        scale = self.scale_points_per_meter
        for i in range(self.page_count):
            for annot in self.annotations(i):
                subject = (annot.info or {}).get("subject", "")
                if not subject.startswith("pdfsuite:measure_"):
                    continue
                pts = [pymupdf.Point(p) for p in (annot.vertices or [])]
                if len(pts) < 2:
                    continue
                kind = subject.split("_", 1)[1]
                if kind == "line":
                    length = math.dist(pts[0], pts[1])
                    area = None
                else:
                    n = len(pts)
                    length = sum(math.dist(pts[k], pts[(k + 1) % n]) for k in range(n))
                    area = abs(sum(pts[k].x * pts[(k + 1) % n].y - pts[(k + 1) % n].x * pts[k].y
                                   for k in range(n))) / 2
                rows.append({
                    "page": i + 1,
                    "type": {"line": "Longueur", "perimeter": "Périmètre",
                             "area": "Surface"}.get(kind, kind),
                    "length_m": length / scale if scale else None,
                    "area_m2": area / (scale * scale) if (scale and area is not None) else None,
                    "label": (annot.info or {}).get("content", ""),
                })
        return rows

    def export_measurements_csv(self, out_path: str) -> int:
        """CSV readable by a French Excel (';' separator, ',' decimals)."""
        import csv

        def num(v):
            return "" if v is None else f"{v:.3f}".replace(".", ",")

        rows = self.measurements()
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["N°", "Page", "Type", "Longueur / périmètre (m)", "Surface (m²)"])
            for n, r in enumerate(rows, start=1):
                w.writerow([n, r["page"], r["type"], num(r["length_m"]), num(r["area_m2"])])
            if rows:
                total_len = sum(r["length_m"] or 0 for r in rows if r["type"] == "Longueur")
                total_area = sum(r["area_m2"] or 0 for r in rows if r["area_m2"] is not None)
                w.writerow([])
                w.writerow(["", "", "Total longueurs", num(total_len), ""])
                w.writerow(["", "", "Total surfaces", "", num(total_area)])
        return len(rows)

    # -- capture --------------------------------------------------------
    def render_clip(self, index: int, rect, dpi: int = 200) -> pymupdf.Pixmap:
        """High-resolution render of part of a page, annotations included."""
        return self.page(index).get_pixmap(dpi=dpi, clip=pymupdf.Rect(rect), annots=True)

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
        if self.is_original(path):
            raise PermissionError("Le fichier d'origine n'est jamais écrasé.")
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
