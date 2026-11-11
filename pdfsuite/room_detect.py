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
OPENING_WORDS = ("fenêtre", "fenetre", "porte", "door", "window", "menuiserie", "baie",
                 "châssis", "chassis", "coulissant", "vitrage", "glazing")
_OPEN_RE = __import__("re").compile(r"fen[eê]tre|\bportes?\b|door|window|menuiserie|baie|ch[aâ]ssis|coulissant|vitrage|glazing")


def _is_opening_layer(n: str) -> bool:
    """'Macro de fenêtre, porte' yes, 'Mur maçonnerie porteur' no."""
    return bool(_OPEN_RE.search(n))


def _is_wall_layer(n: str) -> bool:
    return any(w in n for w in WALL_WORDS) and not _is_opening_layer(n)


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
        if _is_opening_layer(n):
            roles[xref] = "opening"
        elif _is_wall_layer(n):
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



# -- page preparation (once per page and scale, then every click is fast) -----
PREP_PX_M = 0.012           # metres per pixel of the page wall mask
MAX_PREP_PX = 45e6          # mask size limit (pixels)
BRIDGE_MIN_M, BRIDGE_MAX_M = 0.2, 4.6   # door / window widths closed by a bridge
MAX_ROOM_M2 = 400.0
PASSAGE_MAX_M = 2.0         # open passage (no door) closed between wall ends
THIN_M = 0.24              # strips narrower than this are not part of a room
SNAP_TOL_PX = 3.5           # outline edge -> drawing line distance (mask pixels)


def _neutral_dark(rgb, limit=0.6) -> bool:
    """Black / dark grey (walls), not coloured (axes, furniture...)."""
    if not rgb:
        return True
    if len(rgb) == 1:
        return rgb[0] < limit
    if len(rgb) == 4:                       # CMYK
        c, m, y, k = rgb
        rgb = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    r, g, b = rgb[:3]
    return max(r, g, b) - min(r, g, b) < 0.12 and 0.3 * r + 0.59 * g + 0.11 * b < limit


def _light_grey(rgb) -> bool:
    if not rgb:
        return False
    if len(rgb) == 1:
        rgb = (rgb[0],) * 3
    elif len(rgb) == 4:
        c, m, y, k = rgb
        rgb = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    r, g, b = rgb[:3]
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    return max(r, g, b) - min(r, g, b) < 0.06 and 0.7 <= lum <= 0.95


class _Prep:
    pass


def _xf(m):
    if m is None:
        return lambda p: (float(p[0]), float(p[1]))
    return lambda p: tuple(pymupdf.Point(p) * m)


def is_prepared(doc, page_no: int) -> bool:
    return _key(doc, page_no) in doc.__dict__.get("_room_cache", {})


def _collect(doc, page_no: int) -> dict:
    """Everything read from MuPDF (main thread only): drawings, room
    stamps, page geometry. The heavy analysis then runs in _build."""
    page = doc.page(page_no)
    labels = []
    try:
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", ()):
                t = "".join(sp["text"] for sp in ln["spans"])
                if _AREA_RE.match(t):
                    r = pymupdf.Rect(ln["bbox"])
                    labels.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
    except Exception:
        pass
    try:
        drawings = page.get_cdrawings()
    except Exception:
        drawings = []
    return {"scale": doc.scale_points_per_meter,
            "m": ~page.derotation_matrix if page.rotation else None,
            "size": doc.visual_size(page_no), "drawings": drawings, "labels": labels}


def _key(doc, page_no):
    return (page_no, round(doc.scale_points_per_meter or 0, 4))


def prepare_async(doc, page_no: int):
    """Starts reading the walls in the background (file opened, tool
    chosen): the first click then finds it ready. MuPDF is only used here,
    in the calling (main) thread; the analysis runs in a worker thread."""
    import threading
    if not doc.scale_points_per_meter or not has_wall_layers(doc):
        return
    cache = doc.__dict__.setdefault("_room_cache", {})
    pending = doc.__dict__.setdefault("_room_pending", {})
    key = _key(doc, page_no)
    if key in cache or key in pending:
        return
    data = _collect(doc, page_no)

    def work():
        try:
            prep = _build(data)
            cache.clear()
            cache[key] = prep
        except Exception:
            pass
        finally:
            pending.pop(key, None)

    t = threading.Thread(target=work, daemon=True)
    pending[key] = t
    t.start()


def prepare(doc, page_no: int):
    """Wall lines, door / window bridges and a wall mask of the whole page,
    cached on the document (≈1-2 s on a big plan, done once)."""
    cache = doc.__dict__.setdefault("_room_cache", {})
    key = _key(doc, page_no)
    t = doc.__dict__.get("_room_pending", {}).get(key)
    if t is not None:
        t.join()                       # already being read in the background
    prep = cache.get(key)
    if prep is not None:
        return prep
    prep = _build(_collect(doc, page_no))
    cache.clear()                      # one page at a time is enough
    cache[key] = prep
    return prep


def _build(data: dict):
    from PySide6.QtCore import QLineF, QPointF, Qt
    from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen, QBrush, QColor, QPolygonF

    scale = data["scale"]
    m = data["m"]
    T = _xf(m)
    w_pts, h_pts = data["size"]
    zoom = 1.0 / (PREP_PX_M * scale)
    zoom = min(zoom, math.sqrt(MAX_PREP_PX / max(1.0, w_pts * h_pts)))
    W, H = int(w_pts * zoom) + 2, int(h_pts * zoom) + 2
    img = QImage(W, H, QImage.Format_Grayscale8)
    img.fill(255)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.Antialiasing, False)
    qp.scale(zoom, zoom)
    if m is None:
        T = lambda p: (p[0], p[1])
    segs, arcs, ev_lines, ev_arcs, ev_circ = [], [], [], [], []
    min_len = 0.015 * scale
    layer_kind = {}                  # layer name -> (is_wall, is_open), computed once
    dark_c, grey_c = {}, {}          # colour -> bool, computed once

    def dark(c):
        k = tuple(c) if c else None
        v = dark_c.get(k)
        if v is None:
            v = dark_c[k] = _neutral_dark(c)
        return v

    def grey(c):
        k = tuple(c) if c else None
        v = grey_c.get(k)
        if v is None:
            v = grey_c[k] = _light_grey(c)
        return v

    # furniture / fittings: small blocks filled light grey (wardrobe, WC frame,
    # appliance), on any layer. Their outline and cross may be drawn apart on
    # the wall layer: lines lying inside such a block are not walls.
    fcell = scale
    fgrid = {}
    pad = 0.01 * scale
    for path in data["drawings"]:
        if "f" not in path["type"] or not _light_grey(path.get("fill")):
            continue
        ln_ = _norm(path.get("layer"))
        if _is_wall_layer(ln_) or _is_opening_layer(ln_):
            continue                 # grey walls stay walls
        r = pymupdf.Rect(path["rect"])
        if m is not None:
            r = r * m
        w_, h_ = r.width, r.height
        if (min(w_, h_) < 0.08 * scale or min(w_, h_) > 1.3 * scale
                or w_ * h_ > 6 * scale * scale):
            continue
        box = (r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
        for gx in range(int(box[0] // fcell), int(box[2] // fcell) + 1):
            for gy in range(int(box[1] // fcell), int(box[3] // fcell) + 1):
                fgrid.setdefault((gx, gy), []).append(box)

    def in_furniture(a, b):
        if not fgrid:
            return False
        for bx in fgrid.get((int(a[0] // fcell), int(a[1] // fcell)), ()):
            if (bx[0] <= a[0] <= bx[2] and bx[1] <= a[1] <= bx[3]
                    and bx[0] <= b[0] <= bx[2] and bx[1] <= b[1] <= bx[3]):
                return True
        return False

    import time as _time
    tick = _time.time()
    # painted in drawing order, as on screen: the hatching of the walls is
    # long lines hidden afterwards by white fills, they must stay hidden
    for path in data["drawings"]:
        if _time.time() - tick > 0.02:        # let the window breathe (background)
            _time.sleep(0)
            tick = _time.time()
        lname = path.get("layer") or ""
        kind = layer_kind.get(lname)
        if kind is None:
            n_ = _norm(lname)
            kind = layer_kind[lname] = (_is_wall_layer(n_), _is_opening_layer(n_))
        is_wall, is_open = kind
        if not (is_wall or is_open):
            continue
        items = path.get("items", ())
        ptype = path["type"]
        stroked = "s" in ptype
        for it in items:
            op = it[0]
            if op == "c" and stroked:                    # door swing arcs
                a, b = T(it[1]), T(it[4])
                arcs.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, math.dist(a, b)))
                ev_arcs.append((a, b))
                c1, c2 = T(it[2]), T(it[3])
                # centre = crossing of the normals at both ends (circular arc)
                q = _intersect((a, (a[0] - (c1[1] - a[1]), a[1] + (c1[0] - a[0]))),
                               (b, (b[0] - (b[1] - c2[1]), b[1] + (b[0] - c2[0]))))
                if q is not None:
                    r = (math.dist(q, a) + math.dist(q, b)) / 2
                    if abs(math.dist(q, a) - math.dist(q, b)) < 0.1 * r:
                        ev_circ.append((q[0], q[1], r))
            elif is_open and op == "l":
                ev_lines.append(T(it[1]) + T(it[2]))
            elif is_open and op == "re":
                r = it[1]
                c = [T((r[0], r[1])), T((r[2], r[1])), T((r[2], r[3])), T((r[0], r[3]))]
                ev_lines += [c[i] + c[(i + 1) % 4] for i in range(4)]
        if not is_wall:
            continue
        # a block filled light grey (WC frame, appliance, furniture) is not a
        # wall, even with a black outline: the room goes under it
        filled = "f" in ptype
        furn = filled and grey(path.get("fill"))
        qpath = QPainterPath()
        last = None
        for it in items:
            op = it[0]
            if op == "l":
                a, b = T(it[1]), T(it[2])
                if not filled and in_furniture(a, b):
                    last = None
                    continue                 # outline / cross of a fitting
                if last != a:
                    qpath.moveTo(a[0], a[1])
                qpath.lineTo(b[0], b[1])
                last = b
                if not furn:
                    segs.append((a[0], a[1], b[0], b[1]))
            elif op == "c":
                if not filled:
                    continue                 # stroked arcs: door swings, not walls
                a = T(it[1])
                if last != a:
                    qpath.moveTo(a[0], a[1])
                c1, c2, b = T(it[2]), T(it[3]), T(it[4])
                qpath.cubicTo(c1[0], c1[1], c2[0], c2[1], b[0], b[1])
                last = b
            elif op in ("re", "qu"):
                if op == "re":
                    r = it[1]
                    c = [T((r[0], r[1])), T((r[2], r[1])), T((r[2], r[3])), T((r[0], r[3]))]
                else:
                    q = it[1]
                    c = [T(q[0]), T(q[1]), T(q[3]), T(q[2])]
                if not filled and in_furniture(c[0], c[2]):
                    last = None
                    continue
                qpath.addPolygon(QPolygonF([QPointF(x, y) for x, y in c]))
                qpath.closeSubpath()
                last = None
                if not furn:
                    segs += [(c[i][0], c[i][1], c[(i + 1) % 4][0], c[(i + 1) % 4][1]) for i in range(4)]
        if path.get("closePath"):
            qpath.closeSubpath()
        qpath.setFillRule(Qt.OddEvenFill if path.get("even_odd") else Qt.WindingFill)
        if filled:
            g = 0 if dark(path.get("fill")) else 255   # light fill: floor, furniture
            qp.fillPath(qpath, QBrush(QColor(g, g, g)))
        if stroked and not furn:
            col = path.get("color")
            if dark(col):
                pen = QPen(QColor(0, 0, 0), 2.0)
            elif _gray(col).red() > 200:
                pen = QPen(QColor(255, 255, 255), 1.0)  # white lines erase
            else:
                continue                             # coloured: axes, annotations
            pen.setCosmetic(True)
            qp.strokePath(qpath, pen)
    qp.end()
    arr = np.frombuffer(img.constBits(), np.uint8,
                        count=img.bytesPerLine() * H).reshape(H, img.bytesPerLine())[:, :W]
    mask = arr < 128
    segs = np.array(segs, float).reshape(-1, 4)
    if len(segs):
        segs = segs[np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]) >= min_len]
    segs = _visible(segs, mask, zoom)
    bridges, fillers, kinds = _bridges(segs, scale, (ev_lines, ev_circ))
    closers = np.vstack([bridges, fillers])

    def lines_mask(lines):
        img2 = QImage(W, H, QImage.Format_Grayscale8)
        img2.fill(255)
        if len(lines):
            qp = QPainter(img2)
            qp.setRenderHint(QPainter.Antialiasing, False)
            qp.scale(zoom, zoom)
            pen = QPen(QColor(0, 0, 0), 2.0)
            pen.setCosmetic(True)
            qp.setPen(pen)
            qp.drawLines([QLineF(*b) for b in lines])
            qp.end()
        a2 = np.frombuffer(img2.constBits(), np.uint8,
                           count=img2.bytesPerLine() * H).reshape(H, img2.bytesPerLine())[:, :W]
        return a2 < 128

    passage = np.array([k == "passage" for k in kinds], bool)
    strong = np.vstack([bridges[~passage], fillers]) if len(bridges) else fillers
    mask_strong = mask | lines_mask(strong)
    mask_all = mask_strong | lines_mask(bridges[passage]) if passage.any() else mask_strong
    prep = _Prep()
    prep.zoom = zoom
    prep.mask = mask_strong
    prep.mask_all = mask_all
    prep.labels = []
    for x, y in data["labels"]:
        if m is not None:
            x, y = tuple(pymupdf.Point(x, y) * m)
        prep.labels.append((int(y * zoom), int(x * zoom)))
    prep.segs = segs
    prep.bridges = bridges
    prep.kinds = kinds
    prep.lines = np.vstack([segs, closers])
    prep.arcs = arcs
    prep.ev_arcs = ev_arcs
    prep.scale = scale
    prep.runs = {}
    _runs(prep)                        # flood tables ready before the first click
    return prep


def _visible(segs, mask, zoom):
    """Only the lines really visible in the wall mask (not hidden hatching)."""
    if not len(segs):
        return segs
    H, W = mask.shape
    k = 9
    t = (np.arange(k) + 0.5) / k
    xs = (segs[:, 0:1] + (segs[:, 2:3] - segs[:, 0:1]) * t) * zoom
    ys = (segs[:, 1:2] + (segs[:, 3:4] - segs[:, 1:2]) * t) * zoom
    xi = np.clip(xs.astype(int), 0, W - 1)
    yi = np.clip(ys.astype(int), 0, H - 1)
    near = dilate(mask, 1)             # the line may be drawn one pixel aside
    cover = near[yi, xi].mean(axis=1)
    return segs[cover >= 0.85]


def _bridges(segs: np.ndarray, scale: float, evidence=((), ())):
    """Doors and windows interrupt the wall faces: the gap between two
    pieces of the SAME straight line (collinear wall lines) is closed by a
    'bridge', exactly on the wall face, when both ends are wall ends (a
    jamb line leaves each end across the face)."""
    if not len(segs):
        return np.zeros((0, 4)), np.zeros((0, 4)), []
    x0, y0, x1, y1 = segs.T
    th = np.arctan2(y1 - y0, x1 - x0) % math.pi
    th[th > math.pi - 0.002] -= math.pi
    ux, uy = np.cos(th), np.sin(th)
    rho = -uy * x0 + ux * y0
    t0 = ux * x0 + uy * y0
    t1 = ux * x1 + uy * y1
    lo, hi = np.minimum(t0, t1), np.maximum(t0, t1)
    ang_tol, rho_tol = 0.004, 0.006 * scale
    gmin, gmax = BRIDGE_MIN_M * scale, BRIDGE_MAX_M * scale
    cell = 0.02 * scale
    ends = {}
    for k in range(len(segs)):
        for (px, py), (qx, qy) in (((x0[k], y0[k]), (x1[k], y1[k])),
                                   ((x1[k], y1[k]), (x0[k], y0[k]))):
            ends.setdefault((int(px // cell), int(py // cell)), []).append((px, py, qx - px, qy - py))
    jt = 0.01 * scale
    # door / window drawing at the gap: glazing / sill lines along it (window)
    # or a swing arc hinged at one end with the gap's width (door). A gap
    # without any is a corridor or a coincidence, not an opening.
    ev_lines, ev_arcs = evidence
    EL = np.array(ev_lines, float).reshape(-1, 4)
    need_evidence = bool(len(EL) or ev_arcs)
    near_end = 0.2 * scale
    # door swings: centre (hinge) and radius (leaf)
    AR = np.array(ev_arcs, float).reshape(-1, 3)

    def has_evidence(pa, pb):
        L = math.dist(pa, pb)
        dx, dy = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
        if len(EL):
            ex0, ey0, ex1, ey1 = EL.T
            vx, vy = ex1 - ex0, ey1 - ey0
            vl = np.hypot(vx, vy) + 1e-9
            par = np.abs(vx * dy - vy * dx) / vl < 0.05
            d0 = np.abs((ex0 - pa[0]) * dy - (ey0 - pa[1]) * dx)
            d1 = np.abs((ex1 - pa[0]) * dy - (ey1 - pa[1]) * dx)
            t0 = (ex0 - pa[0]) * dx + (ey0 - pa[1]) * dy
            t1 = (ex1 - pa[0]) * dx + (ey1 - pa[1]) * dy
            ov = np.minimum(np.maximum(t0, t1), L) - np.maximum(np.minimum(t0, t1), 0)
            ok = par & (d0 < 0.4 * scale) & (d1 < 0.4 * scale) & (ov > 0.5 * L)
            if ok.any():
                return "fenêtre"
        if len(AR):
            # hinge at one end of the gap, leaf = the gap (single) or half (double)
            ok = (AR[:, 2] >= 0.4 * L) & (AR[:, 2] <= 1.2 * L)
            if ok.any():
                A = AR[ok]
                d = np.minimum(np.hypot(A[:, 0] - pa[0], A[:, 1] - pa[1]),
                               np.hypot(A[:, 0] - pb[0], A[:, 1] - pb[1]))
                if (d <= near_end).any():
                    return "porte"

        return None

    def has_jamb(px, py, dx, dy):
        """Far ends of the jamb lines leaving (px, py) across the face
        (empty list = no jamb)."""
        cx, cy = int(px // cell), int(py // cell)
        found = []
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for qx, qy, vx, vy in ends.get((gx, gy), ()):
                    if abs(qx - px) > jt or abs(qy - py) > jt:
                        continue
                    L = math.hypot(vx, vy) or 1e-9
                    if abs(vx * dx + vy * dy) / L < 0.5:      # across the face
                        found.append((qx + vx, qy + vy))
        return found

    dash_len, dash_gap = 0.35 * scale, 0.1 * scale
    order = np.argsort(th, kind="stable")
    out, fill, kinds = [], [], []
    breaks = np.nonzero(np.diff(th[order]) > ang_tol)[0] + 1
    for grp in np.split(order, breaks):
        if len(grp) < 2:
            continue
        g2 = grp[np.argsort(rho[grp], kind="stable")]
        b2 = np.nonzero(np.diff(rho[g2]) > rho_tol)[0] + 1
        for line in np.split(g2, b2):
            if len(line) < 2:
                continue
            ln = line[np.argsort(lo[line], kind="stable")]
            a_th = float(np.mean(th[ln]))
            a_rho = float(np.mean(rho[ln]))
            cx, cy = math.cos(a_th), math.sin(a_th)
            pt = lambda t: (t * cx - a_rho * cy, t * cy + a_rho * cx)
            # dashed lines (lintels over the openings): short pieces with
            # short gaps; their gaps are filled, but they are no wall face
            short = (hi[ln] - lo[ln]) < dash_len
            dash = np.zeros(len(ln), bool)
            # a real dashed line: at least 3 short pieces with real gaps
            link = [short[k] and short[k + 1] and 0.002 * scale < lo[ln[k + 1]] - hi[ln[k]] < dash_gap
                    for k in range(len(ln) - 1)]
            k = 0
            while k < len(link):
                if link[k]:
                    j = k
                    while j < len(link) and link[j]:
                        j += 1
                    if j - k >= 2:                 # k .. j : j - k + 1 pieces
                        dash[k:j + 1] = True
                    k = j
                else:
                    k += 1
            end = hi[ln[0]]
            for j in ln[1:]:
                gap = lo[j] - end
                if 0 < gap < dash_gap:
                    fill.append(pt(end) + pt(lo[j]))
                end = max(end, hi[j])
            solid = ln[~dash]
            if len(solid) < 2:
                continue
            end = hi[solid[0]]
            for j in solid[1:]:
                s = lo[j]
                gap = s - end
                if gmin <= gap <= gmax:
                    pa, pb = pt(end), pt(s)
                    ja, jb = has_jamb(pa[0], pa[1], cx, cy), has_jamb(pb[0], pb[1], cx, cy)
                    if ja and jb:
                        kind = has_evidence(pa, pb) if need_evidence else "ouverture"
                        if not kind and gap <= PASSAGE_MAX_M * scale:
                            kind = "passage"     # open passage between two rooms
                        if kind:
                            out.append(pa + pb)
                            kinds.append(kind)
                            # same opening on the other face of the wall: the
                            # far ends of both jambs, if they face each other
                            for qa in ja:
                                for qb in jb:
                                    if (abs(math.dist(qa, qb) - gap) <= 0.03 * scale
                                            and abs(math.dist(qa, pa) - math.dist(qb, pb)) <= 0.03 * scale
                                            and math.dist(qa, pa) <= 0.6 * scale):
                                        out.append(tuple(qa) + tuple(qb))
                                        kinds.append(kind)
                end = max(end, hi[j])
    # the same opening is often found several times (overlapping lines)
    uniq, ukinds, seen = [], [], set()
    for b, k in zip(out, kinds):
        key = tuple(round(v, 1) for v in b)
        if key not in seen and key[2:] + key[:2] not in seen:
            seen.add(key)
            uniq.append(b)
            ukinds.append(k)
    return np.array(uniq, float).reshape(-1, 4), np.array(fill, float).reshape(-1, 4), ukinds


_AREA_RE = __import__("re").compile(r"^\s*\d+[.,]\d+\s*m(²|2)\s*$")


def _room_labels(page, m, zoom):
    """Pixel positions of the room stamps of the plan ('11.44 m²'): one per
    room, they tell when two rooms were merged."""
    out = []
    try:
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", ()):
                t = "".join(sp["text"] for sp in ln["spans"])
                if _AREA_RE.match(t):
                    r = pymupdf.Rect(ln["bbox"])
                    c = pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                    if m is not None:
                        c = c * m
                    out.append((int(c.y * zoom), int(c.x * zoom)))
    except Exception:
        pass
    return out


CLOSET_MAX_M2 = 3.0        # small closed space behind a door, without room stamp
PASSAGE_ZONE_M2 = 15.0     # unstamped zone behind an open passage (rest of a hall)


def _add_closets(prep, reg, ox, oy, px_m, which="strong"):
    """A wardrobe / niche behind doors belongs to the room: through each
    door of the room, a small closed space without a room stamp of its own
    is added. A WC or a storeroom has its own stamp and stays apart."""
    B = prep.bridges
    if not len(B):
        return reg, ox, oy
    z = prep.zoom
    H, W = prep.mask.shape
    h, w = reg.shape
    near = dilate(reg, 4)
    pieces = []
    seen = set()
    mask = prep.mask if which == "strong" else prep.mask_all
    for (x0, y0, x1, y1), kind in zip(B, prep.kinds):
        # behind a door: a closet; behind an open passage: an alcove / the
        # rest of a hall. Never a space with its own room stamp.
        if kind == "passage" and which != "all":
            continue
        max_px = (PASSAGE_ZONE_M2 if kind == "passage" else CLOSET_MAX_M2) / (px_m * px_m)
        mx, my = (x0 + x1) / 2 * z, (y0 + y1) / 2 * z
        iy, ix = int(my) - oy, int(mx) - ox
        if not (0 <= iy < h and 0 <= ix < w and near[iy, ix]):
            continue
        L = math.hypot(x1 - x0, y1 - y0) or 1e-9
        nx, ny = -(y1 - y0) / L, (x1 - x0) / L
        for sgn in (1, -1):
            sx = int(mx + sgn * nx * 5)
            sy = int(my + sgn * ny * 5)
            if not (0 <= sx < W and 0 <= sy < H) or mask[sy, sx]:
                continue
            ly, lx = sy - oy, sx - ox
            if 0 <= ly < h and 0 <= lx < w and reg[ly, lx]:
                continue                  # the room side
            if (sy, sx) in seen:
                continue
            f = _flood_page(prep, (sy, sx), max_px, which)
            if f is None or _count_labels(prep, *f) > 0:
                continue
            r2, x2, y2 = f
            # a real closet is at least 40 cm deep; a door reveal (inside the
            # thickness of the wall) is not
            rr = max(1, int(round(0.2 / px_m)))
            if not opening(np.pad(r2, rr + 1), rr).any():
                continue
            ys, xs = np.nonzero(r2)
            seen.update(zip((ys + y2).tolist()[:1], (xs + x2).tolist()[:1]))
            pieces.append(f)
    if not pieces:
        return reg, ox, oy
    X0 = min([ox] + [p[1] for p in pieces])
    Y0 = min([oy] + [p[2] for p in pieces])
    X1 = max([ox + w] + [p[1] + p[0].shape[1] for p in pieces])
    Y1 = max([oy + h] + [p[2] + p[0].shape[0] for p in pieces])
    out = np.zeros((Y1 - Y0, X1 - X0), bool)
    out[oy - Y0:oy - Y0 + h, ox - X0:ox - X0 + w] |= reg
    for r2, x2, y2 in pieces:
        out[y2 - Y0:y2 - Y0 + r2.shape[0], x2 - X0:x2 - X0 + r2.shape[1]] |= r2
    return out, X0, Y0


def _count_labels(prep, reg, ox, oy):
    h, w = reg.shape
    n = 0
    for y, x in prep.labels:
        if 0 <= y - oy < h and 0 <= x - ox < w and reg[y - oy, x - ox]:
            n += 1
    return n


def _runs(prep, which="strong"):
    if which not in prep.runs:
        prep.runs[which] = _row_runs(~(prep.mask if which == "strong" else prep.mask_all))
    return prep.runs[which]


def _flood_page(prep, seed, max_px, which="strong"):
    """Room = free pixels connected to the seed, on the whole page mask.
    None if it grows over ``max_px`` (not closed)."""
    free = ~(prep.mask if which == "strong" else prep.mask_all)
    H, W = free.shape
    y, x = seed
    starts, ends = _runs(prep, which)
    if not free[y, x]:
        return None
    i = int(np.searchsorted(ends[y], x, side="right"))
    stack = [(y, i)]
    seen = {(y, i)}
    rows = []
    total = 0
    while stack:
        y, i = stack.pop()
        s, e = int(starts[y][i]), int(ends[y][i])
        if y == 0 or y == H - 1 or s == 0 or e == W:
            return None
        total += e - s
        if total > max_px:
            return None
        rows.append((y, s, e))
        for ny in (y - 1, y + 1):
            st, en = starts[ny], ends[ny]
            j0 = int(np.searchsorted(en, s, side="right"))
            j1 = int(np.searchsorted(st, e, side="left"))
            for j in range(j0, j1):
                if (ny, j) not in seen:
                    seen.add((ny, j))
                    stack.append((ny, j))
    ys = [r[0] for r in rows]
    y0, y1 = min(ys), max(ys) + 1
    x0 = min(r[1] for r in rows)
    x1 = max(r[2] for r in rows)
    reg = np.zeros((y1 - y0, x1 - x0), bool)
    for y, s, e in rows:
        reg[y - y0, s - x0:e - x0] = True
    return reg, x0, y0


def _flood_closed(prep, seed, px_m):
    """Fallback for an opening without a bridge (door at a corner...):
    close the gaps of the mask around the click, growing the gap size."""
    sy, sx = seed
    H, W = prep.mask.shape
    for win_m in (14.0, 30.0):
        half = int(win_m / px_m / 2)
        y0, y1 = max(0, sy - half), min(H, sy + half)
        x0, x1 = max(0, sx - half), min(W, sx + half)
        sub = prep.mask[y0:y1, x0:x1]
        for g in (0.3, 0.5, 0.7, 0.95):
            r = max(1, int(round(g / px_m)))
            closed = closing(sub, r)
            if closed[sy - y0, sx - x0]:
                break
            reg = flood(~closed, (sy - y0, sx - x0), stop_at_border=True)
            if reg is not None:
                ys, xs = np.nonzero(reg)
                return reg[ys.min():ys.max() + 1, xs.min():xs.max() + 1], x0 + xs.min(), y0 + ys.min()
    return None


def _snap_edges(poly, lines, tol, scale):
    """Every outline edge is moved onto the drawing line it follows (wall
    face or bridge): exact lengths and areas, not pixel ones."""
    n = len(poly)
    if not len(lines):
        return poly
    lx0, ly0, lx1, ly1 = lines.T
    ldx, ldy = lx1 - lx0, ly1 - ly0
    lL = np.hypot(ldx, ldy)
    eqs = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        L = math.dist(a, b)
        if L < 1e-6:
            eqs.append(None)
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        cross = np.abs(ux * ldy - uy * ldx) / lL
        d0 = np.abs((lx0 - a[0]) * uy - (ly0 - a[1]) * ux)
        d1 = np.abs((lx1 - a[0]) * uy - (ly1 - a[1]) * ux)
        t0 = (lx0 - a[0]) * ux + (ly0 - a[1]) * uy
        t1 = (lx1 - a[0]) * ux + (ly1 - a[1]) * uy
        ov = np.minimum(np.maximum(t0, t1), L) - np.maximum(np.minimum(t0, t1), 0)
        ok = (cross < 0.035) & (d0 < tol) & (d1 < tol) & (ov > np.minimum(0.3 * L, 0.5 * lL))
        if not ok.any():
            # no drawing line: an edge almost horizontal / vertical is made exact
            ang = math.degrees(math.atan2(uy, ux)) % 180
            if min(ang, 180 - ang) < 6:
                ux, uy = (1.0 if ux >= 0 else -1.0), 0.0
            elif abs(ang - 90) < 6:
                ux, uy = 0.0, (1.0 if uy >= 0 else -1.0)
            eqs.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, ux, uy, False))
            continue
        idx = np.nonzero(ok)[0]
        score = ov[idx] - 4 * (d0[idx] + d1[idx])
        k = idx[int(np.argmax(score))]
        vx, vy = ldx[k] / lL[k], ldy[k] / lL[k]
        if vx * ux + vy * uy < 0:
            vx, vy = -vx, -vy
        eqs.append((lx0[k], ly0[k], vx, vy, True))
    out = []
    for i in range(n):
        e1, e2 = eqs[i - 1], eqs[i]
        p = poly[i]
        if e1 is None or e2 is None:
            out.append(p)
            continue
        q = _intersect(((e1[0], e1[1]), (e1[0] + e1[2], e1[1] + e1[3])),
                       ((e2[0], e2[1]), (e2[0] + e2[2], e2[1] + e2[3])))
        if q is None or abs(e1[2] * e2[3] - e1[3] * e2[2]) < 0.05:
            # (nearly) parallel neighbours: same wall face -> drop the corner
            if e1[4] and e2[4] and abs((e2[0] - e1[0]) * e1[3] - (e2[1] - e1[1]) * e1[2]) < tol:
                continue
            # project the corner onto the snapped edge
            if e2[4]:
                t = (p[0] - e2[0]) * e2[2] + (p[1] - e2[1]) * e2[3]
                q = (e2[0] + t * e2[2], e2[1] + t * e2[3])
            else:
                q = p
        elif math.dist(q, p) > 6 * tol:
            q = p
        out.append(q)
    return out


def _clean(poly, min_edge):
    """Remove zero / tiny edges and collinear points."""
    pts = list(poly)
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            if math.dist(pts[i], pts[(i + 1) % len(pts)]) < min_edge:
                del pts[(i + 1) % len(pts)]
                changed = True
                break
    return drop_collinear(pts, tol=0.05)


def _parallel(e1, e2, tol=0.04):
    (a, b), (c, d) = e1, e2
    l1, l2 = math.dist(a, b), math.dist(c, d)
    if l1 < 1e-9 or l2 < 1e-9:
        return False
    return abs((b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])) / (l1 * l2) < tol


def _restore_wedges(full, kept):
    """The thin cut also removes sharp corners of the room (slanted walls).
    A removed piece is given back when it touches the room along a long
    side (a corner), not through a narrow neck (inside of a wall)."""
    removed = full & ~kept
    if not removed.any():
        return kept
    out = kept.copy()
    touch = dilate(kept, 1)
    todo = removed.copy()
    for _ in range(400):
        ys, xs = np.nonzero(todo)
        if not len(ys):
            break
        comp = flood(todo, (int(ys[0]), int(xs[0])))
        todo &= ~comp
        cy, cx = np.nonzero(comp)
        side = max(cy.max() - cy.min(), cx.max() - cx.min()) + 1
        contact = int((comp & touch).sum())
        if contact >= 0.5 * side:
            out |= comp
    return out


def _line_dist(p, seg):
    (a, b) = seg
    L = math.dist(a, b) or 1e-9
    return abs((p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])) / L


def _area(pts):
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                   for i in range(n))) / 2


def _drawn(a, b, lines, tol):
    """True when a line of the drawing runs along the edge a-b (a real wall
    face, e.g. a cut corner), False for a pixel artefact."""
    if not len(lines):
        return False
    L = math.dist(a, b)
    if L < 1e-9:
        return False
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    x0, y0, x1, y1 = lines.T
    d0 = np.abs((x0 - a[0]) * uy - (y0 - a[1]) * ux)
    d1 = np.abs((x1 - a[0]) * uy - (y1 - a[1]) * ux)
    t0 = (x0 - a[0]) * ux + (y0 - a[1]) * uy
    t1 = (x1 - a[0]) * ux + (y1 - a[1]) * uy
    ov = np.minimum(np.maximum(t0, t1), L) - np.maximum(np.minimum(t0, t1), 0)
    return bool(((d0 < tol) & (d1 < tol) & (ov > 0.7 * L)).any())


def _regularize(poly, scale, lines=np.zeros((0, 4)), tol=1.0):
    """Generic clean-up of the outline, whatever the plan:
    - a short edge cutting a corner (chamfer) -> the real corner;
    - a micro step (two parallel edges offset by a few cm) -> one straight
      wall face, on the line of the longer edge."""
    short, chamfer, micro, reach = 0.12 * scale, 0.3 * scale, 0.035 * scale, 0.3 * scale
    pts = list(poly)
    for _ in range(4 * len(pts) + 4):
        n = len(pts)
        if n < 4:
            break
        changed = False
        for i in range(n):
            p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
            lc = math.dist(p1, p2)
            if lc >= chamfer:
                continue
            prev, cur, nxt = (p0, p1), (p1, p2), (p2, p3)
            if not _parallel(prev, nxt):
                if _parallel(prev, cur) or _parallel(cur, nxt):
                    continue
                if lc >= short and _drawn(p1, p2, lines, tol):
                    continue                 # a real cut corner of the wall
                q = _intersect(prev, nxt)
                if q is not None and math.dist(q, p1) <= reach and math.dist(q, p2) <= reach:
                    j = (i + 1) % n
                    pts[i] = q
                    del pts[j]
                    changed = True
                    break
            elif lc < short and _line_dist(p3, prev) <= micro:
                # keep the line of the longer neighbour
                if math.dist(p0, p1) >= math.dist(p2, p3):
                    a, b = prev
                    L = math.dist(a, b)
                    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                    t = (p3[0] - a[0]) * ux + (p3[1] - a[1]) * uy
                    new_p3 = (a[0] + ux * t, a[1] + uy * t)
                    idx = sorted({i % n, (i + 1) % n}, reverse=True)
                    pts[(i + 2) % n] = new_p3
                else:
                    a, b = nxt
                    L = math.dist(a, b)
                    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
                    t = (p0[0] - a[0]) * ux + (p0[1] - a[1]) * uy
                    pts[i - 1] = (a[0] + ux * t, a[1] + uy * t)
                    idx = sorted({i % n, (i + 1) % n}, reverse=True)
                for k in idx:
                    del pts[k]
                changed = True
                break
        if not changed:
            break
    return drop_collinear(pts, tol=0.05)


def _remove_frames(poly, marks, scale):
    """Door frames / casings jut a few centimetres into the room next to
    the openings; plans measure the room without them. Steps and bumps of
    at most 15 cm next to an opening (bridge end or door hinge) are removed."""
    if not marks:
        return poly
    step, near, reveal = 0.15 * scale, 0.25 * scale, 0.6 * scale

    def near_mark(p):
        return any(math.dist(p, m) <= near for m in marks)

    pts = list(poly)
    for _ in range(12):
        changed = False
        for rev in (False, True):
            if rev:
                pts.reverse()
            n = len(pts)
            if n < 5:
                break
            for i in range(n):
                P = [pts[(i + k) % n] for k in range(-1, 4)]   # p[i-1] .. p[i+3]
                a, b, c, d = (P[0], P[1]), (P[1], P[2]), (P[2], P[3]), (P[3], P[4])
                lb, lc = math.dist(*b), math.dist(*c)
                # step: a, short b, c parallel to a, then d -> extend a to d
                if lb <= step and lc <= 1.2 * scale and _parallel(a, c) and not _parallel(a, d)                         and (near_mark(P[2]) or near_mark(P[3])):
                    q = _intersect(a, d)
                    if q is not None and math.dist(q, P[3]) <= step * 1.5:
                        idx = sorted({(i + k) % n for k in (0, 1, 2)}, reverse=True)
                        for k in idx:
                            del pts[k]
                        pts.insert(min(idx) if min(idx) < len(pts) + 1 else len(pts), q)
                        changed = True
                        break
                # reveal of a door / window left open: a, out b, c, back d, e on
                # the line of a -> the wall face goes straight on
                if n >= 6 and i + 1 < n:
                    Q = [pts[(i + k) % n] for k in range(-1, 5)]  # p[i-1] .. p[i+4]
                    a, b, c, d, e = [(Q[k], Q[k + 1]) for k in range(5)]
                    lb, ld, lc = math.dist(*b), math.dist(*d), math.dist(*c)
                    if (lb <= reveal and ld <= reveal and lc <= 2.8 * scale and abs(lb - ld) <= step
                            and _parallel(a, c) and _parallel(a, e)
                            and _line_dist(Q[4], a) <= 0.03 * scale
                            and (near_mark(Q[2]) or near_mark(Q[3]) or near_mark(Q[1]) or near_mark(Q[4]))):
                        trial = [p for k, p in enumerate(pts)
                                 if k not in {(i + j) % n for j in (0, 1, 2, 3)}]
                        if len(trial) >= 3 and _area(trial) < _area(pts):   # outward only
                            pts = trial
                            changed = True
                            break
            if rev:
                pts.reverse()
            if changed:
                break
        if not changed:
            break
    return drop_collinear(pts, tol=0.05)


def detect_room(doc, page_no: int, click_xy: tuple[float, float]):
    """``click_xy`` in visual page points. Needs a plan exported with its
    layers (walls on a "Mur"-like layer). Returns {"polygon": [(x, y)],
    "openings": [{"edge", "a", "b", "kind"}]} in visual page points."""
    scale = doc.scale_points_per_meter
    if not scale:
        raise RoomError("Indiquez d'abord l'échelle du plan.")
    if not has_wall_layers(doc):
        try:
            names = sorted({(v.get("name") or "").strip() for v in doc.doc.get_ocgs().values()} - {""})
        except Exception:
            names = []
        if names:
            shown = ", ".join(names[:25]) + (" …" if len(names) > 25 else "")
            why = ("Aucun de ses calques ne s'appelle comme un mur (Mur, Cloison, Poteau, Voile…).\n"
                   f"Calques trouvés : {shown}")
        else:
            why = "Ce PDF a été exporté sans calques : les murs ne se distinguent pas du reste du dessin."
        raise RoomError("Pièce automatique impossible sur ce plan.\n\n" + why + "\n\n"
                        "Utilisez Périmètre ou Surface (clic sur chaque coin) : les cotes et "
                        "ouvertures sont alors calculées automatiquement.")
    prep = prepare(doc, page_no)
    z = prep.zoom
    px_m = 1.0 / (z * scale)
    H, W = prep.mask.shape
    sx, sy = int(click_xy[0] * z), int(click_xy[1] * z)
    if not (0 <= sx < W and 0 <= sy < H):
        raise RoomError("Cliquez à l'intérieur d'une pièce.")
    if prep.mask[sy, sx]:
        # clicked on a line / label: nearest free point within 30 cm
        r0 = max(2, int(0.3 / px_m))
        y0, y1, x0, x1 = max(0, sy - r0), min(H, sy + r0), max(0, sx - r0), min(W, sx + r0)
        ys, xs = np.nonzero(~prep.mask[y0:y1, x0:x1])
        if len(ys) == 0:
            raise RoomError("Cliquez à l'intérieur d'une pièce (pas sur un mur).")
        k = np.argmin((ys + y0 - sy) ** 2 + (xs + x0 - sx) ** 2)
        sy, sx = int(ys[k] + y0), int(xs[k] + x0)
    max_px = MAX_ROOM_M2 / (px_m * px_m)
    which = "strong"
    found = _flood_page(prep, (sy, sx), max_px)
    if (found is None or _count_labels(prep, *found) >= 2) and prep.mask_all is not prep.mask             and not prep.mask_all[sy, sx]:
        # several room stamps inside: open passages between rooms are closed too
        alt = _flood_page(prep, (sy, sx), max_px, "all")
        if alt is not None and (found is None or _count_labels(prep, *alt) < _count_labels(prep, *found)):
            found = alt
            which = "all"
    if found is None:
        found = _flood_closed(prep, (sy, sx), px_m)
    if found is None:
        raise RoomError("Pièce non fermée ou trop grande : cliquez bien à l'intérieur "
                        "d'une pièce fermée par des murs.")
    reg, ox, oy = _add_closets(prep, *found, px_m, which)
    # padding so the morphology / outline never touch the border
    pad = 6
    region = np.zeros((reg.shape[0] + 2 * pad, reg.shape[1] + 2 * pad), bool)
    region[pad:-pad, pad:-pad] = reg
    ox, oy = ox - pad, oy - pad
    # thin strips reached through an opening (inside of a wall between its
    # faces / hatch lines): the room never goes there
    r_thin = max(1, int(round(THIN_M / 2 / px_m)))
    full = region
    thin_cut = opening(region, r_thin)
    seed = (sy - oy, sx - ox)
    if thin_cut[seed]:
        region = flood(thin_cut, seed)
    elif thin_cut.any():
        ys_, xs_ = np.nonzero(thin_cut)
        k = np.argmin((ys_ - seed[0]) ** 2 + (xs_ - seed[1]) ** 2)
        region = flood(thin_cut, (int(ys_[k]), int(xs_[k])))
    # back to the exact pixels of the room (the opening rounds the corners)
    region = full & dilate(region, r_thin + 1)
    region = _restore_wedges(full, region)
    region = fill_holes(region)
    # door leaves, frames and thin furniture lines stuck to the walls
    region = fill_holes(closing(region, max(1, int(round(0.06 / px_m)))))
    region = opening(region, 1)
    if not region.any():
        raise RoomError("Contour de pièce introuvable.")
    region = fill_holes(region)

    outline = trace_outline(region)
    poly = simplify(outline, 1.2)
    poly = [((ox + p[0]) / z, (oy + p[1]) / z) for p in poly]
    tol = SNAP_TOL_PX / z
    # candidate lines near the room only
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    L = prep.lines
    near = ((np.maximum(L[:, 0], L[:, 2]) > min(xs) - 3 * tol) & (np.minimum(L[:, 0], L[:, 2]) < max(xs) + 3 * tol)
            & (np.maximum(L[:, 1], L[:, 3]) > min(ys) - 3 * tol) & (np.minimum(L[:, 1], L[:, 3]) < max(ys) + 3 * tol))
    lines = L[near]
    poly = drop_collinear(square_up(poly, tol_deg=2.0), tol=0.6 / z)
    for _ in range(2):
        poly = _snap_edges(poly, lines, tol, scale)
        poly = _clean(poly, 0.02 * scale)
    marks = [tuple(b[:2]) for b in prep.bridges] + [tuple(b[2:]) for b in prep.bridges]
    marks += [p for a, b in prep.ev_arcs for p in (a, b)]
    cx0, cx1, cy0, cy1 = min(xs) - 50, max(xs) + 50, min(ys) - 50, max(ys) + 50
    marks = [m for m in marks if cx0 < m[0] < cx1 and cy0 < m[1] < cy1]
    poly = _remove_frames(poly, marks, scale)
    poly = _regularize(poly, scale, lines, tol)
    if len(poly) < 3:
        raise RoomError("Contour de pièce introuvable.")
    openings = _bridge_openings(prep, poly, scale)
    return {"polygon": poly, "openings": openings}


def _bridge_openings(prep, pts, scale):
    """Openings of each side = the bridges (closed doors / windows) lying on
    it. Door when a swing arc is near, else window."""
    out = []
    B = prep.bridges
    n = len(pts)
    tol = 0.012 * scale
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        L = math.dist(a, b)
        if L < MIN_OPENING_M * scale or not len(B):
            continue
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        d0 = np.abs((B[:, 0] - a[0]) * uy - (B[:, 1] - a[1]) * ux)
        d1 = np.abs((B[:, 2] - a[0]) * uy - (B[:, 3] - a[1]) * ux)
        t0 = (B[:, 0] - a[0]) * ux + (B[:, 1] - a[1]) * uy
        t1 = (B[:, 2] - a[0]) * ux + (B[:, 3] - a[1]) * uy
        lo = np.clip(np.minimum(t0, t1), 0, L)
        hi = np.clip(np.maximum(t0, t1), 0, L)
        ok = (d0 < tol) & (d1 < tol) & (hi - lo >= MIN_OPENING_M * scale * 0.8)
        spans = sorted((lo[k], hi[k], prep.kinds[k]) for k in np.nonzero(ok)[0])
        merged = []
        for s, e, kind in spans:
            if merged and s <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e, kind])
        for s, e, kind in merged:
            pa = (a[0] + ux * s, a[1] + uy * s)
            pb = (a[0] + ux * e, a[1] + uy * e)
            out.append({"edge": i, "a": pa, "b": pb, "kind": kind})
    return out


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
    if layers and doc.scale_points_per_meter:
        return _bridge_openings(prepare(doc, page_no), pts, scale)
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
