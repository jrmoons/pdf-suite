import sys, os, re, time, glob, json
sys.path.insert(0, r"C:\Users\JérémyMoons\.local\bin\pdf-suite")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from pdfsuite.pdf_document import PdfDocument
import importlib
rd = importlib.import_module(os.environ.get("RD", "pdfsuite.room_detect"))
_op = rd._patterns
if os.environ.get("NOGRID"):
    rd._patterns = lambda *a: (set(), _op(*a)[1])
if os.environ.get("NOSTAIR"):
    rd._patterns = lambda *a: (_op(*a)[0], [])
if os.environ.get("SCRAMBLE"):
    rd._is_wall_layer = lambda n: False
    rd._is_opening_layer = lambda n: False

def rooms(doc):
    """(area, perimeter or None, centre of the area stamp) for every room stamp."""
    p = doc.page(0)
    lines = []
    for b in p.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            lines.append((t, pymupdf.Rect(l["bbox"])))
    out = []
    for t, r in lines:
        m = re.fullmatch(r"(\d+[.,]\d+)\s*m(²|2)", t)
        if not m:
            continue
        area = float(m.group(1).replace(",", "."))
        if area < 0.3:
            continue
        per = None
        for t2, r2 in lines:
            m2 = re.fullmatch(r"(\d+[.,]\d+)\s*m", t2)
            if m2 and abs(r2.y0 - r.y1) < 12 and abs(r2.x0 - r.x0) < 40:
                per = float(m2.group(1).replace(",", "."))
        out.append((area, per, ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)))
    return out
import pymupdf
files = sorted(glob.glob(os.environ["TEMP"] + "/claude_arlon/" + (sys.argv[1] if len(sys.argv) > 1 else "10*.pdf")))
tot = ok = 0; ttot = 0; res = []
for f in files:
    doc = PdfDocument(f); doc.set_ratio_scale(50)
    t0 = time.time(); doc.snap_index(0); doc.segments(0, rd.WALL_WORDS); tprep = time.time() - t0
    for area, per, (x, y) in rooms(doc):
        t = time.time()
        try:
            r = rd.detect_room(doc, 0, (x, y)); err = None
        except Exception as e:
            r = None; err = type(e).__name__ + ":" + str(e)[:40]
        dt = time.time() - t; ttot += dt; tot += 1
        s = doc.scale_points_per_meter
        if r:
            A = doc.poly_area(r["polygon"]) / s / s; P = doc.poly_perimeter(r["polygon"]) / s
            good = abs(A - area) <= max(0.05, 0.01 * area)
            ok += good
            res.append((os.path.basename(f), round(x), round(y), area, round(A, 2), per, round(P, 2), round(dt, 2), "OK" if good else "BAD", len(r["openings"])))
        else:
            res.append((os.path.basename(f), round(x), round(y), area, None, per, None, round(dt, 2), err, 0))
    print(f, "prep", round(tprep, 2), file=sys.stderr)
for r in res: print(*r, sep="\t")
print(f"OK {ok}/{tot}  temps moyen {ttot/max(1,tot):.2f}s  max {max(r[7] for r in res):.2f}s")
