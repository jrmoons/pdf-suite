import sys, os, math, glob, re
sys.path.insert(0, r"C:\Users\JérémyMoons\.local\bin\pdf-suite")
from PySide6.QtWidgets import QApplication
app = QApplication([])
import pymupdf
from pdfsuite.pdf_document import PdfDocument
from pdfsuite import room_detect as rd
tot = short = diag = rooms = 0
for f in sorted(glob.glob(os.environ["TEMP"] + "/claude_arlon/10*.pdf")):
    doc = PdfDocument(f); doc.set_ratio_scale(50); s = doc.scale_points_per_meter
    p = doc.page(0)
    for b in p.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(x["text"] for x in l["spans"]).strip()
            if re.fullmatch(r"\d+\.\d\d m.", t):
                r = pymupdf.Rect(l["bbox"])
                try:
                    poly = rd.detect_room(doc, 0, ((r.x0+r.x1)/2, (r.y0+r.y1)/2))["polygon"]
                except Exception:
                    continue
                rooms += 1
                n = len(poly)
                for i in range(n):
                    a, c = poly[i], poly[(i+1) % n]
                    L = math.dist(a, c); tot += 1
                    ang = math.degrees(math.atan2(c[1]-a[1], c[0]-a[0])) % 90
                    if L < 0.12 * s: short += 1
                    if L < 0.3 * s and 3 < ang < 87:
                        diag += 1; print(os.path.basename(f), round(a[0]), round(a[1]), round(c[0]), round(c[1]), round(L/s*100), "cm")
print("rooms", rooms, "edges", tot, "short<12cm", short, "short diagonal", diag)
