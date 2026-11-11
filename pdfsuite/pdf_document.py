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
UNIT_KEY = "PDFSuiteUnit"     # custom catalog key: measurement unit (mm/cm/m)
DECIMALS_KEY = "PDFSuiteDecimals"

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
        self._dl_cache = {}
        self._snap_cache = {}

    # -- object snapping ----------------------------------------------------
    SNAP_CELL = 24.0     # spatial hash cell, in PDF points

    def snap_index(self, index: int):
        """Points of the drawing a measurement can snap to (line ends,
        corners, midpoints), in visual page coordinates, bucketed in a
        spatial hash. Built once per page (≈0.3 s on a big plan)."""
        if not hasattr(self, "_snap_cache"):
            self._snap_cache = {}
        idx = self._snap_cache.get(index)
        if idx is not None:
            return idx
        page = self.page(index)
        m = ~page.derotation_matrix if page.rotation else None
        cell = self.SNAP_CELL
        grid: dict = {}

        def add(x, y, kind):
            if m is not None:
                p = pymupdf.Point(x, y) * m
                x, y = p.x, p.y
            key = (int(x // cell), int(y // cell))
            grid.setdefault(key, []).append((x, y, kind))

        try:
            drawings = page.get_cdrawings()
        except Exception:
            drawings = []
        for path in drawings:
            for it in path.get("items", ()):
                op = it[0]
                if op == "l":
                    (x0, y0), (x1, y1) = it[1], it[2]
                    add(x0, y0, 0)
                    add(x1, y1, 0)
                    if abs(x1 - x0) + abs(y1 - y0) > 2:
                        add((x0 + x1) / 2, (y0 + y1) / 2, 1)
                elif op == "c":
                    add(it[1][0], it[1][1], 0)
                    add(it[4][0], it[4][1], 0)
                elif op == "re":
                    r = pymupdf.Rect(it[1])
                    for x, y in ((r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)):
                        add(x, y, 0)
                elif op == "qu":
                    q = it[1]
                    for pt in (q[0], q[1], q[2], q[3]):
                        add(pt[0], pt[1], 0)
        # de-duplicate (plans repeat the same point many times)
        for key, pts in grid.items():
            grid[key] = list({(round(x, 2), round(y, 2), k) for x, y, k in pts})
        self._snap_cache[index] = grid
        return grid

    def snap_point(self, index: int, x: float, y: float, radius: float):
        """Nearest snap point within ``radius`` (visual coords), ends and
        corners preferred over midpoints. Returns (x, y, kind) or None."""
        grid = self.snap_index(index)
        cell = self.SNAP_CELL
        best, best_score = None, None
        cx0, cx1 = int((x - radius) // cell), int((x + radius) // cell)
        cy0, cy1 = int((y - radius) // cell), int((y + radius) // cell)
        r2 = radius * radius
        for cx in range(cx0, cx1 + 1):
            for cy in range(cy0, cy1 + 1):
                for px, py, kind in grid.get((cx, cy), ()):
                    d2 = (px - x) ** 2 + (py - y) ** 2
                    if d2 > r2:
                        continue
                    score = d2 + (kind * r2 * 0.25)
                    if best_score is None or score < best_score:
                        best, best_score = (px, py, kind), score
        return best

    def invalidate_render(self, index: int | None = None):
        """Forget the cached drawing of a page whose content changed."""
        if not hasattr(self, "_dl_cache"):
            self._dl_cache = {}
        if index is None:
            self._dl_cache = {}
            self._snap_cache = {}
        else:
            self._dl_cache.pop(index, None)
            getattr(self, "_snap_cache", {}).pop(index, None)

    def display_list(self, index: int):
        """Parsed drawing of a page (content only, no annotations), cached:
        rendering a zoomed area from it is ~10x faster than from the page."""
        if not hasattr(self, "_dl_cache"):
            self._dl_cache = {}
        dl = self._dl_cache.get(index)
        if dl is None:
            dl = self.page(index).get_displaylist(annots=False)
            self._dl_cache[index] = dl
        return dl

    def render_clip(self, index: int, zoom: float, clip=None) -> pymupdf.Pixmap:
        """Render (part of) a page's content at ``zoom`` (visual coords)."""
        page = self.page(index)
        mat = pymupdf.Matrix(zoom, zoom)
        if page.rotation:
            # display lists ignore /Rotate: fall back to the page itself
            return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip,
                                   alpha=False, annots=False)
        return self.display_list(index).get_pixmap(matrix=mat, clip=clip, alpha=False)

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
        self.scale_is_default = False
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

    # -- measurement unit / formatting (single source of truth) ------------
    UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0}

    def _read_key(self, key: str):
        try:
            return self.doc.xref_get_key(self.doc.pdf_catalog(), key)
        except Exception:
            return ("null", "null")

    @property
    def unit(self) -> str:
        if not hasattr(self, "_unit"):
            kind, val = self._read_key(UNIT_KEY)
            self._unit = val.strip("()/") if kind in ("string", "name") and val.strip("()/") in self.UNITS else None
        return self._unit or "m"

    @property
    def unit_from_file(self) -> bool:
        _ = self.unit
        return self._unit is not None

    @unit.setter
    def unit(self, value: str):
        if value not in self.UNITS:
            return
        self._unit = value
        try:
            self.doc.xref_set_key(self.doc.pdf_catalog(), UNIT_KEY, f"/{value}")
        except Exception:
            pass
        self.mark_dirty()

    @property
    def decimals(self) -> int:
        if not hasattr(self, "_decimals"):
            kind, val = self._read_key(DECIMALS_KEY)
            self._decimals = int(val) if kind == "int" else None
        return 2 if self._decimals is None else self._decimals

    @decimals.setter
    def decimals(self, value: int):
        self._decimals = max(0, min(4, int(value)))
        try:
            self.doc.xref_set_key(self.doc.pdf_catalog(), DECIMALS_KEY, str(self._decimals))
        except Exception:
            pass
        self.mark_dirty()

    def _num(self, value: float) -> str:
        return f"{value:.{self.decimals}f}".replace(".", ",")

    def fmt_length_pts(self, points: float) -> str:
        """PDF points -> '3,25 m' in the document unit ('?' without scale)."""
        m = self.points_to_meters(points)
        if m is None:
            return "?"
        return f"{self._num(m / self.UNITS[self.unit])} {self.unit}"

    def fmt_area_pts2(self, points2: float) -> str:
        """Surfaces are always given in m² (plan convention), lengths in
        the chosen unit."""
        s = self.scale_points_per_meter
        if not s:
            return "?"
        return f"{self._num(points2 / (s * s))} m²"

    @staticmethod
    def poly_perimeter(pts, closed: bool = True) -> float:
        import math
        n = len(pts)
        segs = range(n) if closed else range(n - 1)
        return sum(math.dist(pts[i], pts[(i + 1) % n]) for i in segs)

    @staticmethod
    def poly_area(pts) -> float:
        n = len(pts)
        return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                       for i in range(n))) / 2.0

    def measure_label(self, subject: str, pts) -> str:
        """Label of a measurement from its vertices [(x, y), ...]."""
        pts = [(float(p[0]), float(p[1])) for p in pts]
        if subject.endswith("dimension"):
            import math
            return self.fmt_length_pts(math.dist(pts[0], pts[-1]))
        if subject.endswith("line"):
            return self.fmt_length_pts(self.poly_perimeter(pts, closed=False))
        area = self.fmt_area_pts2(self.poly_area(pts))
        if subject.endswith("area"):
            return f"S = {area}"
        return f"P = {self.fmt_length_pts(self.poly_perimeter(pts))} · S = {area}"

    def relabel_measurements(self):
        """Rewrites the stored label of every measurement (after a change
        of scale / unit / decimals) so other PDF readers show the same."""
        for i in range(self.page_count):
            for annot in self.annotations(i):
                subject = (annot.info or {}).get("subject", "")
                if subject.startswith("pdfsuite:measure_") and annot.vertices:
                    annot.set_info(content=self.measure_label(subject, annot.vertices))
                    annot.update()
        self.mark_dirty()

    def set_paper_real_scale(self, paper: float, paper_unit: str, real: float, real_unit: str):
        """'paper' length on the sheet represents 'real' length on site,
        e.g. 1 cm = 0,5 m  (-> 1:50)."""
        paper_m = paper * self.UNITS[paper_unit]
        real_m = real * self.UNITS[real_unit]
        if paper_m > 0 and real_m > 0:
            self.scale_points_per_meter = paper_m * POINTS_PER_PAPER_METER / real_m

    def ratio(self) -> float | None:
        s = self.scale_points_per_meter
        return POINTS_PER_PAPER_METER / s if s else None

    def to_unit(self, points: float) -> float | None:
        """PDF points -> value in the document unit (None without scale)."""
        m = self.points_to_meters(points)
        return None if m is None else m / self.UNITS[self.unit]

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
        return self.render_clip(index, zoom)

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
        self.invalidate_render(index)
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

    def add_dimension(self, index: int, vertices, color, label: str):
        """Aligned dimension stored as a polyline A, A', B', B (so any PDF
        reader shows the extension and dimension lines)."""
        annot = self.page(index).add_polyline_annot([pymupdf.Point(v) for v in vertices])
        annot.set_colors(stroke=color)
        annot.set_border(width=0.8)
        annot.set_info(subject="pdfsuite:measure_dimension", content=label)
        annot.update()
        self.mark_dirty()
        return annot

    def update_dimension(self, index: int, old_annot, vertices, color, label: str):
        self.delete_annot(index, old_annot)
        return self.add_dimension(index, vertices, color, label)

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
        """Every PDF Suite measurement of the document, values recomputed
        from the geometry with the current scale, in the document unit."""
        rows = []
        scale = self.scale_points_per_meter
        u = self.UNITS[self.unit]
        for i in range(self.page_count):
            for annot in self.annotations(i):
                subject = (annot.info or {}).get("subject", "")
                if not subject.startswith("pdfsuite:measure_"):
                    continue
                pts = [(p[0], p[1]) for p in (annot.vertices or [])]
                if len(pts) < 2:
                    continue
                kind = subject.split("_", 1)[1]
                if kind == "dimension":
                    import math
                    length, area = math.dist(pts[0], pts[-1]), None
                    kind = "line"
                elif kind == "line":
                    length, area = self.poly_perimeter(pts, closed=False), None
                else:
                    length, area = self.poly_perimeter(pts), self.poly_area(pts)
                rows.append({
                    "page": i + 1,
                    "type": {"line": "Longueur", "perimeter": "Périmètre",
                             "area": "Surface"}.get(kind, kind),
                    "length": length / scale / u if scale else None,
                    "area": area / (scale * scale) if (scale and area is not None) else None,
                    "label": self.measure_label(subject, pts),
                })
        return rows

    def export_measurements_csv(self, out_path: str) -> int:
        """CSV readable by a French Excel (';' separator, ',' decimals)."""
        import csv

        def num(v):
            return "" if v is None else f"{v:.{max(self.decimals, 2)}f}".replace(".", ",")

        unit = self.unit
        rows = self.measurements()
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([self.scale_description()])
            w.writerow(["N°", "Page", "Type", f"Longueur / périmètre ({unit})", "Surface (m²)"])
            for n, r in enumerate(rows, start=1):
                w.writerow([n, r["page"], r["type"], num(r["length"]), num(r["area"])])
            if rows:
                total_len = sum(r["length"] or 0 for r in rows if r["type"] == "Longueur")
                total_area = sum(r["area"] or 0 for r in rows if r["area"] is not None)
                w.writerow([])
                w.writerow(["", "", "Total longueurs", num(total_len), ""])
                w.writerow(["", "", "Total surfaces", "", num(total_area)])
        return len(rows)

    # -- capture --------------------------------------------------------
    def delete_annot_at(self, index: int, point) -> bool:
        page = self.page(index)
        for annot in page.annots() or []:
            if annot.rect.contains(point):
                page.delete_annot(annot)
                self.mark_dirty()
                return True
        return False

    def words_in_rect(self, index: int, rect):
        """Selected text as one rectangle per line (so the spaces between
        words are highlighted too, like the words themselves)."""
        words = self.page(index).get_text("words")
        lines: dict = {}
        for w in words:
            wrect = pymupdf.Rect(w[:4])
            if wrect.intersects(rect):
                key = (w[5], w[6])          # block, line
                lines[key] = lines[key] | wrect if key in lines else wrect
        return [lines[k] for k in sorted(lines)]

    # -- text block editing -------------------------------------------
    def text_blocks(self, index: int):
        return self.page(index).get_text("dict")["blocks"]

    def replace_text_in_rect(self, index: int, rect, new_text: str,
                             fontsize: float, color=(0, 0, 0), fontname="helv",
                             origin=None, direction=(1.0, 0.0)):
        """Replace a text block: the old text is removed (redaction) and the
        new one written at the same baseline, size, colour and direction.
        (Earlier versions skipped any text smaller than 6 pt - typical of
        plans - so the edited text simply vanished.)"""
        import math
        page = self.page(index)
        page.add_redact_annot(rect, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        lines = new_text.split("\n")
        dx, dy = direction
        angle = math.degrees(math.atan2(-dy, dx))
        rot = round(angle / 90) * 90 % 360 if abs(angle / 90 - round(angle / 90)) < 0.02 else None
        if origin is None:
            origin = pymupdf.Point(rect.x0, rect.y0 + fontsize)
        origin = pymupdf.Point(origin)
        step = fontsize * 1.2
        for i, line in enumerate(lines):
            # next line = one step "below", perpendicular to the text direction
            pt = pymupdf.Point(origin.x - dy * step * i, origin.y + dx * step * i)
            if rot is not None:
                page.insert_text(pt, line, fontsize=fontsize, fontname=fontname,
                                 color=color, rotate=rot)
            else:
                page.insert_text(pt, line, fontsize=fontsize, fontname=fontname, color=color,
                                 morph=(pt, pymupdf.Matrix(-angle)))
        self.invalidate_render(index)
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
