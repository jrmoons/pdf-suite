"""Automatic room: click inside a room -> outline, perimeter, area, and the
openings (doors / windows) of each wall.

Works on plans exported WITH their layers (CAD exports usually keep them):
only the wall layers ("Mur", "Poteau", ...) are rendered, the straight lines
of the door / window layer close the openings at the wall face, the room is
flood-filled from the click, outlined, squared up and its corners snapped
onto the real corners of the drawing. Openings = parts of each side not
covered by a wall line. Without layers, the room cannot be told apart from
dimension lines / furniture reliably: the user then clicks the corners
(Périmètre / Surface) and only the openings + cotes are automatic.
"""
from __future__ import annotations

import math

import numpy as np
import pymupdf

PX_M = 0.015            # metres per pixel of the analysis image
WINDOW_M = 26.0         # analysed square around the click (metres)
WINDOWS_M = (26.0, 60.0, 130.0)   # tried in turn for big rooms
GAPS_M = (0.35, 0.5, 0.7, 0.95, 1.25)   # half-widths of the closings tried
MIN_OPENING_M = 0.45
NOTCH_M = 0.6           # notches narrower than this are filled
DENS_R, DENS_T = 3, 0.20    # wall = ink density > DENS_T in a (2R+1)² window
ZOOM_HI = 2.6               # fine image: pixels per PDF point (paper based)
MAX_HI_PX = 4200            # fine image size limit


class RoomError(Exception):
    pass


# -- small morphology toolkit on boolean arrays ------------------------------
def _shift_or(m: np.ndarray, r: int, axis: int) -> np.ndarray:
    out = m.copy()
    for i in range(1, r + 1):
        if axis == 1:
            out[:, i:] |= m[:, :-i]
            out[:, :-i] |= m[:, i:]
        else:
            out[i:, :] |= m[:-i, :]
            out[:-i, :] |= m[i:, :]
    return out


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return m.copy()
    return _shift_or(_shift_or(m, r, 1), r, 0)


def erode(m: np.ndarray, r: int) -> np.ndarray:
    return ~dilate(~m, r)


def density(m: np.ndarray, r: int) -> np.ndarray:
    """Fraction of True pixels in the (2r+1)² square around each pixel
    (box filter via an integral image)."""
    k = 2 * r + 1
    ii = np.zeros((m.shape[0] + 1, m.shape[1] + 1), np.int32)
    ii[1:, 1:] = np.cumsum(np.cumsum(m, axis=0, dtype=np.int32), axis=1)
    p = np.pad(ii, ((r, r), (r, r)), mode="edge")
    H, W = m.shape
    s = p[k:k + H, k:k + W] - p[0:H, k:k + W] - p[k:k + H, 0:W] + p[0:H, 0:W]
    return s / float(k * k)


def dilate_walls_core(walls):
    """Wall pixels that are surely walls (thick cores), never added back
    into the room by the notch closing."""
    return erode(walls, 1)


def closing(m, r):
    return erode(dilate(m, r), r)


def opening(m, r):
    return dilate(erode(m, r), r)


def _row_runs(free: np.ndarray):
    """For every row: (starts, ends) of the horizontal runs of True."""
    H, W = free.shape
    pad = np.zeros((H, W + 2), np.int8)
    pad[:, 1:-1] = free
    d = np.diff(pad, axis=1)
    ys_s, xs_s = np.nonzero(d == 1)
    ys_e, xs_e = np.nonzero(d == -1)
    starts = [[] for _ in range(H)]
    ends = [[] for _ in range(H)]
    # nonzero returns row-major order: split per row
    bs = np.searchsorted(ys_s, np.arange(H + 1))
    be = np.searchsorted(ys_e, np.arange(H + 1))
    for y in range(H):
        starts[y] = xs_s[bs[y]:bs[y + 1]]
        ends[y] = xs_e[be[y]:be[y + 1]]
    return starts, ends


def flood(free: np.ndarray, seed: tuple[int, int], stop_at_border: bool = False):
    """4-connected component of ``free`` containing ``seed``, grown run by
    run (fast). With ``stop_at_border``, returns None as soon as the
    component touches the image border (the room "leaks")."""
    H, W = free.shape
    y, x = seed
    region = np.zeros_like(free)
    if not free[y, x]:
        return region
    starts, ends = _row_runs(free)
    i = int(np.searchsorted(ends[y], x, side="right"))
    stack = [(y, i)]
    seen = {(y, i)}
    while stack:
        y, i = stack.pop()
        s, e = int(starts[y][i]), int(ends[y][i])
        if stop_at_border and (y == 0 or y == H - 1 or s == 0 or e == W):
            return None
        region[y, s:e] = True
        for ny in (y - 1, y + 1):
            if 0 <= ny < H:
                st, en = starts[ny], ends[ny]
                j0 = int(np.searchsorted(en, s, side="right"))
                j1 = int(np.searchsorted(st, e, side="left"))
                for j in range(j0, j1):
                    if (ny, j) not in seen:
                        seen.add((ny, j))
                        stack.append((ny, j))
    return region


def fill_holes(region: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(region)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    sub = region[y0:y1, x0:x1]
    free = np.ones((sub.shape[0] + 2, sub.shape[1] + 2), bool)
    free[1:-1, 1:-1] = ~sub
    outside = flood(free, (0, 0))
    out = region.copy()
    out[y0:y1, x0:x1] = ~outside[1:-1, 1:-1]
    return out


# -- outline -----------------------------------------------------------------
def trace_outline(region: np.ndarray) -> list[tuple[float, float]]:
    """Outer boundary of a filled region as pixel-corner coordinates
    (crack following along pixel edges)."""
    H, W = region.shape
    pad = np.zeros((H + 2, W + 2), bool)
    pad[1:-1, 1:-1] = region
    ys, xs = np.nonzero(pad)
    # start on the top-left pixel's top-left corner, walking right
    i = np.argmin(ys * (W + 2) + xs)
    sy, sx = int(ys[i]), int(xs[i])
    # state: corner (x, y) and direction d (0=right,1=down,2=left,3=up)
    dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
    x, y, d = sx, sy, 0
    pts = [(x, y)]

    def filled(px, py):
        return pad[py, px]

    # pixel to the right-hand side of each move direction is "inside"
    for _ in range(4 * (H + W) * 50):
        # candidate turns: left, straight, right (keeping inside on the right)
        moved = False
        for turn in (-1, 0, 1, 2):
            nd = (d + turn) % 4
            dx, dy = dirs[nd]
            # pixels adjacent to edge from (x,y) to (x+dx,y+dy):
            if nd == 0:
                inside, outside = (x, y), (x, y - 1)
            elif nd == 1:
                inside, outside = (x - 1, y), (x, y)
            elif nd == 2:
                inside, outside = (x - 1, y - 1), (x - 1, y)
            else:
                inside, outside = (x, y - 1), (x - 1, y - 1)
            if filled(*inside) and not filled(*outside):
                x, y, d = x + dx, y + dy, nd
                moved = True
                break
        if not moved:
            break
        if (x, y) == (sx, sy):
            break
        pts.append((x, y))
    # back to region coordinates (remove the 1-pixel pad)
    return [(px - 1.0, py - 1.0) for px, py in pts]


def simplify(pts, eps):
    """Douglas-Peucker on a closed polygon."""
    if len(pts) < 4:
        return pts
    # split at the two farthest points
    a = 0
    b = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)

    def dp(seq):
        if len(seq) < 3:
            return seq
        (x0, y0), (x1, y1) = seq[0], seq[-1]
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy) or 1e-9
        best, idx = -1.0, 0
        for i in range(1, len(seq) - 1):
            px, py = seq[i]
            dist = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / L
            if dist > best:
                best, idx = dist, i
        if best > eps:
            return dp(seq[:idx + 1])[:-1] + dp(seq[idx:])
        return [seq[0], seq[-1]]

    first = dp(pts[a:b + 1])
    second = dp(pts[b:] + [pts[0]])
    return first[:-1] + second[:-1]


def square_up(poly, tol_deg=6.0):
    """Edges within ``tol_deg`` of horizontal / vertical become exact, the
    corners being recomputed as intersections of neighbouring edges."""
    n = len(poly)
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180
        if min(ang, 180 - ang) < tol_deg:
            y = (y0 + y1) / 2
            lines.append(((x0, y), (x1, y)))
        elif abs(ang - 90) < tol_deg:
            x = (x0 + x1) / 2
            lines.append(((x, y0), (x, y1)))
        else:
            lines.append(((x0, y0), (x1, y1)))
    out = []
    for i in range(n):
        p = _intersect(lines[i - 1], lines[i])
        out.append(p if p is not None else lines[i][0])
    return out


def _intersect(l1, l2):
    (x1, y1), (x2, y2) = l1
    (x3, y3), (x4, y4) = l2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return ((a * (x3 - x4) - (x1 - x2) * b) / den, (a * (y3 - y4) - (y1 - y2) * b) / den)


def drop_collinear(poly, tol=0.5):
    out = list(poly)
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
            if area2 / (math.dist(a, c) or 1e-9) < tol or math.dist(a, b) < 1e-6:
                del out[i]
                changed = True
                break
    return out


def point_in_poly(x, y, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xi = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if xi > x:
                inside = not inside
    return inside


# -- main entry -------------------------------------------------------------
WALL_WORDS = ("mur", "wall", "cloison", "poteau", "column", "voile", "porteur", "maçonnerie")
OPENING_WORDS = ("fenêtre", "fenetre", "porte", "door", "window", "menuiserie", "baie")


def _norm(name: str) -> str:
    return (name or "").lower()


def layer_roles(doc) -> dict:
    """{ocg xref: "wall" | "opening"} from the layer names of the PDF."""
    roles = {}
    try:
        ocgs = doc.doc.get_ocgs()
    except Exception:
        return roles
    for xref, info in ocgs.items():
        n = _norm(info.get("name"))
        if any(w in n for w in OPENING_WORDS):
            roles[xref] = "opening"
        elif any(w in n for w in WALL_WORDS):
            roles[xref] = "wall"
    return roles


def has_wall_layers(doc) -> bool:
    return "wall" in layer_roles(doc).values()


def _layer_items(doc, page_no, role_names):
    """Drawing items of the page whose layer name matches a role."""
    page = doc.page(page_no)
    m = ~page.derotation_matrix if page.rotation else None
    out = []
    for path in page.get_cdrawings():
        n = _norm(path.get("layer"))
        if any(w in n for w in role_names):
            for it in path.get("items", ()):
                if m is not None:
                    it = (it[0],) + tuple(pymupdf.Point(p) * m if isinstance(p, tuple) and len(p) == 2
                                          else p for p in it[1:])
                out.append(it)
    return out


def _draw_line(mask, x0, y0, x1, y1):
    """Rasterise a segment into a boolean mask (pixel coords)."""
    n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    xs = np.linspace(x0, x1, n + 1).round().astype(int)
    ys = np.linspace(y0, y1, n + 1).round().astype(int)
    ok = (xs >= 0) & (ys >= 0) & (xs < mask.shape[1]) & (ys < mask.shape[0])
    mask[ys[ok], xs[ok]] = True


def _gray(rgb):
    """Real colour of a drawing item as grey (white fills must stay white:
    they mask what is under them)."""
    from PySide6.QtGui import QColor
    if not rgb:
        return QColor(0, 0, 0)
    c = list(rgb) + [0, 0, 0]
    if len(rgb) == 1:
        c = [rgb[0]] * 3
    elif len(rgb) == 4:            # CMYK
        k = rgb[3]
        c = [(1 - rgb[0]) * (1 - k), (1 - rgb[1]) * (1 - k), (1 - rgb[2]) * (1 - k)]
    v = int(255 * (0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]))
    v = max(0, min(255, v))
    return QColor(v, v, v)


def _walls_mask(doc, page_no, clip, zoom):
    """Walls only: the drawing items of the wall layers (Mur, Poteau...)
    near the click are painted into a mask. Dimension lines, texts and
    furniture are on no layer / other layers, so they are left out."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QBrush, QColor, QPolygonF
    W = max(1, int(clip.width * zoom))
    H = max(1, int(clip.height * zoom))
    img = QImage(W, H, QImage.Format_Grayscale8)
    img.fill(255)
    page = doc.page(page_no)
    m = ~page.derotation_matrix if page.rotation else None
    qp = QPainter(img)
    qp.setRenderHint(QPainter.Antialiasing, False)
    qp.scale(zoom, zoom)
    qp.translate(-clip.x0, -clip.y0)
    black = QColor(0, 0, 0)

    def P(pt):
        if m is not None:
            pt = pymupdf.Point(pt) * m
        return QPointF(pt[0], pt[1])

    view = QRectF(clip.x0, clip.y0, clip.width, clip.height)
    for path in page.get_cdrawings():
        lname = _norm(path.get("layer"))
        if not any(w in lname for w in WALL_WORDS):
            continue
        r = pymupdf.Rect(path["rect"])
        if m is not None:
            r = r * m
        if not QRectF(r.x0, r.y0, r.width, r.height).adjusted(-2, -2, 2, 2).intersects(view):
            continue
        qpath = QPainterPath()
        for it in path.get("items", ()):
            op = it[0]
            if op == "l":
                a, b = P(it[1]), P(it[2])
                if qpath.elementCount() == 0 or qpath.currentPosition() != a:
                    qpath.moveTo(a)
                qpath.lineTo(b)
            elif op == "c":
                if path["type"] == "s":
                    continue          # door swing arcs: not walls
                a = P(it[1])
                if qpath.elementCount() == 0 or qpath.currentPosition() != a:
                    qpath.moveTo(a)
                qpath.cubicTo(P(it[2]), P(it[3]), P(it[4]))
            elif op == "re":
                rr = pymupdf.Rect(it[1])
                qpath.addPolygon(QPolygonF([P((rr.x0, rr.y0)), P((rr.x1, rr.y0)),
                                            P((rr.x1, rr.y1)), P((rr.x0, rr.y1))]))
                qpath.closeSubpath()
            elif op == "qu":
                q = it[1]
                qpath.addPolygon(QPolygonF([P(q[0]), P(q[1]), P(q[3]), P(q[2])]))
                qpath.closeSubpath()
        if path.get("closePath"):
            qpath.closeSubpath()
        if path.get("even_odd"):
            qpath.setFillRule(Qt.OddEvenFill)
        else:
            qpath.setFillRule(Qt.WindingFill)
        if "f" in path["type"]:
            qp.fillPath(qpath, QBrush(_gray(path.get("fill"))))
        if "s" in path["type"]:
            pen = QPen(_gray(path.get("color")), max(path.get("width") or 0, 1.0 / zoom))
            qp.strokePath(qpath, pen)
    qp.end()
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, count=img.bytesPerLine() * H).reshape(H, img.bytesPerLine())[:, :W]
    return arr < 128


class _Leak(Exception):
    pass


def _find_region(doc, page_no, cx, cy, scale, window_m):
    """Flood-fill the room around (cx, cy) inside a square of ``window_m``
    metres. Raises _Leak if the room reaches the border of that square."""
    w_pts, h_pts = doc.visual_size(page_no)
    size = window_m * scale
    zoom = min(ZOOM_HI, MAX_HI_PX / size)
    half = size / 2
    clip = pymupdf.Rect(max(0, cx - half), max(0, cy - half),
                        min(w_pts, cx + half), min(h_pts, cy + half))
    walls = _walls_mask(doc, page_no, clip, zoom)
    walls = closing(walls, 2)                       # hatching -> solid wall
    # doors / windows: their straight lines (threshold, glazing) close the
    # openings at the wall face; arcs (door swings) are ignored
    barrier = np.zeros_like(walls)
    for it in _layer_items(doc, page_no, OPENING_WORDS):
        if it[0] == "l":
            (x0, y0), (x1, y1) = it[1], it[2]
            _draw_line(barrier, (x0 - clip.x0) * zoom, (y0 - clip.y0) * zoom,
                       (x1 - clip.x0) * zoom, (y1 - clip.y0) * zoom)
    barrier = closing(barrier, 5) | walls           # join dashed threshold lines
    # pool to the analysis grid (real size)
    zoom_lo = max(0.2, min(6.0, 1.0 / (PX_M * scale)))
    f = max(1, int(round(zoom / zoom_lo)))
    if f > 1:
        Hh, Wh = (barrier.shape[0] // f) * f, (barrier.shape[1] // f) * f
        barrier = barrier[:Hh, :Wh].reshape(Hh // f, f, Wh // f, f).any(axis=(1, 3))
        walls = walls[:Hh, :Wh].reshape(Hh // f, f, Wh // f, f).any(axis=(1, 3))
        zoom = zoom / f
    px_m = 1.0 / (zoom * scale)
    H, W = barrier.shape
    sx, sy = int((cx - clip.x0) * zoom), int((cy - clip.y0) * zoom)
    if not (0 <= sx < W and 0 <= sy < H):
        raise RoomError("Cliquez à l'intérieur d'une pièce.")
    if barrier[sy, sx]:
        # clicked on a wall / label: nearest free point within 50 cm
        r0 = max(2, int(0.5 / px_m))
        y0, y1, x0, x1 = max(0, sy - r0), min(H, sy + r0), max(0, sx - r0), min(W, sx + r0)
        ys, xs = np.nonzero(~barrier[y0:y1, x0:x1])
        if len(ys) == 0:
            raise RoomError("Cliquez à l'intérieur d'une pièce (pas sur un mur).")
        k = np.argmin((ys + y0 - sy) ** 2 + (xs + x0 - sx) ** 2)
        sy, sx = int(ys[k] + y0), int(xs[k] + x0)
    touches_page = (clip.x0 <= 0, clip.y0 <= 0, clip.x1 >= w_pts, clip.y1 >= h_pts)
    for g in (0.0, 0.25, 0.45, 0.6):                # small gaps only (missing lines)
        r = int(round(g / px_m))
        closed = closing(barrier, r) if r else barrier
        if closed[sy, sx]:
            break
        reg = flood(~closed, (sy, sx), stop_at_border=True)
        if reg is not None:
            return reg, clip, zoom, walls
    if all(touches_page):
        raise RoomError("Pièce non fermée : cliquez bien à l'intérieur d'une pièce fermée "
                        "par des murs.")
    raise _Leak()


def detect_room(doc, page_no: int, click_xy: tuple[float, float]):
    """``click_xy`` in visual page points. Needs a plan exported with its
    layers (walls on a "Mur"-like layer). Returns {"polygon": [(x, y)],
    "openings": [{"edge", "a", "b", "kind"}]} in visual page points."""
    scale = doc.scale_points_per_meter
    if not scale:
        raise RoomError("Indiquez d'abord l'échelle du plan.")
    if not has_wall_layers(doc):
        raise RoomError("Ce plan n'a pas de calque de murs : la pièce automatique n'est pas "
                        "possible. Utilisez Périmètre ou Surface (clic sur chaque coin), "
                        "les cotes et ouvertures sont alors calculées automatiquement.")
    cx, cy = click_xy
    last_error = None
    for window_m in WINDOWS_M:          # grow the analysed area for big rooms
        try:
            region, clip, zoom, walls = _find_region(doc, page_no, cx, cy, scale, window_m)
            break
        except _Leak:
            last_error = RoomError("Pièce non fermée ou trop grande : cliquez bien à l'intérieur "
                                   "d'une pièce fermée par des murs.")
    else:
        raise last_error
    px_pt = 1.0 / zoom
    region = fill_holes(region)
    # door leaves / swing arcs inside the room: thin slits and pockets
    px_m = 1.0 / (zoom * scale)
    region = closing(region, max(1, int(round(0.45 / px_m)))) & ~erode(walls, 1)
    region = fill_holes(region)

    outline = trace_outline(region)
    poly = simplify(outline, 1.5)
    poly = drop_collinear(square_up(poly), tol=0.8)
    if len(poly) < 3:
        raise RoomError("Contour de pièce introuvable.")

    def to_pt(p):
        return (clip.x0 + p[0] * px_pt, clip.y0 + p[1] * px_pt)

    pts = [to_pt(p) for p in poly]
    pts = snap_polygon(doc, page_no, pts, 4 * px_pt)
    openings = find_openings(doc, page_no, pts, layers=True)
    return {"polygon": pts, "openings": openings}


def snap_polygon(doc, page_no, pts, radius):
    """Corners onto the real corners of the drawing (exact measurements)."""
    out = []
    for x, y in pts:
        hit = doc.snap_point(page_no, x, y, radius)
        out.append((hit[0], hit[1]) if hit is not None and hit[2] == 0 else (x, y))
    return drop_collinear(out, tol=0.05)


def find_openings(doc, page_no, pts, layers: bool | None = None):
    """Openings along each side of the room polygon: parts of the side not
    covered by a wall line. Door if a swing arc is nearby, else window."""
    scale = doc.scale_points_per_meter or 1.0
    if layers is None:
        layers = has_wall_layers(doc)
    arcs = []
    if layers:
        # door swings are stroked arcs (on the door layer or the wall layer)
        for it in _layer_items(doc, page_no, OPENING_WORDS + WALL_WORDS):
            if it[0] == "c":
                arcs.append(((it[1][0] + it[4][0]) / 2, (it[1][1] + it[4][1]) / 2))
    wall_filter = WALL_WORDS if layers else None
    n = len(pts)
    out = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.dist(a, b)
        if L < MIN_OPENING_M * scale:
            continue
        gaps = doc.wall_openings(page_no, a, b, tol=0.03 * scale,
                                 min_gap=MIN_OPENING_M * scale, layer_words=wall_filter)
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        for t0, t1 in gaps:
            pa = (a[0] + ux * t0, a[1] + uy * t0)
            pb = (a[0] + ux * t1, a[1] + uy * t1)
            mid = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
            near = (t1 - t0) * 1.2
            kind = "porte" if any(math.dist(mid, c) < near for c in arcs) else "fenêtre"
            if not layers:
                kind = "ouverture"
            out.append({"edge": i, "a": pa, "b": pb, "kind": kind})
    return out
