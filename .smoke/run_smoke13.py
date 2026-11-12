import os as _os; _os.environ["PDFSUITE_SETTINGS"] = "PDFSuiteTests"
"""Pièce auto, pratique du métré aux ouvertures (plan synthétique) :
- porte : la pièce où elle s'ouvre va tout droit au mur ; le seuil est compté
  dans la pièce de l'autre côté ;
- fenêtre « all. 0.00 » : l'embrasure jusqu'au châssis est comptée ;
- fenêtre « all. 0.90 » : tout droit le long du mur."""
import sys, os
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
import pymupdf

app = QApplication(sys.argv)
from pdfsuite.pdf_document import PdfDocument
from pdfsuite import room_detect as rd

OUT = os.path.abspath(".smoke")
fails = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name, extra)
    if not cond:
        fails.append(name)


S = 72 / 0.0254 / 50                       # 1:50
d = pymupdf.open()
pg = d.new_page(width=1200, height=900)
mur = d.add_ocg("Mur")
fen = d.add_ocg("Fenêtre")
por = d.add_ocg("Porte")


def wall(x0, y0, x1, y1):
    pg.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), fill=(1, 1, 1), width=0.3, oc=mur)


X, Y, T, TE = 200.0, 200.0, 0.2 * S, 0.3 * S
A = 3.0 * S                                  # both rooms 3 m x 3 m
XB = X + A + T                               # room B starts after the middle wall
# outer walls
wall(X - TE, Y - TE, XB + A + TE, Y)                      # top
wall(X - TE, Y, X, Y + A)                                 # left
wall(XB + A, Y, XB + A + TE, Y + A)                       # right
# middle wall with a 0.90 m door (from 1.0 m to 1.9 m)
wall(X + A, Y, XB, Y + 1.0 * S)
wall(X + A, Y + 1.9 * S, XB, Y + A)
# bottom wall (0.30 m) with a 1.20 m window in each room
for x0 in (X, XB):
    pass
wall(X - TE, Y + A, X + 0.9 * S, Y + A + TE)
wall(X + 2.1 * S, Y + A, XB + 0.9 * S, Y + A + TE)
wall(XB + 2.1 * S, Y + A, XB + A + TE, Y + A + TE)
for x0, sill in ((X, "all. 0.00"), (XB, "all. 0.90")):
    for dd in (0.08, 0.14):                 # frame lines inside the wall
        pg.draw_line((x0 + 0.9 * S, Y + A + dd * S), (x0 + 2.1 * S, Y + A + dd * S),
                     color=(0, 0, 0), width=0.2, oc=fen)
    pg.insert_text((x0 + 1.1 * S, Y + A - 0.15 * S), sill, fontsize=5)
# door leaf hinged on room B's face, opening into room B
hx, hy, r = XB, Y + 1.0 * S, 0.9 * S
k = 0.5523 * r
pg.draw_bezier((hx + r, hy), (hx + r, hy + k), (hx + k, hy + r), (hx, hy + r),
               color=(0, 0, 0), width=0.2, oc=por)
pg.draw_line((hx, hy), (hx + r, hy), color=(0, 0, 0), width=0.2, oc=por)
pg.insert_text((X + 1.2 * S, Y + 1.5 * S), "9.00 m²", fontsize=6)
pg.insert_text((XB + 1.2 * S, Y + 1.5 * S), "9.00 m²", fontsize=6)
path = os.path.join(OUT, "plan_seuil_embrasure.pdf")
d.save(path)
d.close()

doc = PdfDocument(path)
doc.set_ratio_scale(50)
s = doc.scale_points_per_meter

ra = rd.detect_room(doc, 0, (X + 1.5 * S, Y + 2.0 * S))
core = doc.poly_area(ra["polygon_nu"]) / s / s
area = doc.poly_area(ra["polygon"]) / s / s
per = doc.poly_perimeter(ra["polygon"]) / s
want = 9.0 + 0.9 * 0.2 + 1.2 * 0.08
check("room A at the wall faces = 9.00 m²", abs(core - 9.0) < 0.05, round(core, 3))
check("room A + threshold + recess", abs(area - want) < 0.03, f"{area:.3f} (attendu {want:.3f})")
check("room A perimeter goes round the threshold and the recess",
      abs(per - (12.0 + 2 * 0.2 + 2 * 0.08)) < 0.05, round(per, 3))

rb = rd.detect_room(doc, 0, (XB + 1.5 * S, Y + 2.0 * S))
area = doc.poly_area(rb["polygon"]) / s / s
check("room B (door opens into it, sill 0.90) straight along the walls",
      abs(area - 9.0) < 0.05, round(area, 3))

print()
print("SMOKE 13 OK" if not fails else f"SMOKE 13 FAILED: {fails}")
