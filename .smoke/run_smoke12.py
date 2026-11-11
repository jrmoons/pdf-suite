import os as _os; _os.environ["PDFSUITE_SETTINGS"] = "PDFSuiteTests"
"""Pièce auto, règles générales : un dallage (quadrillage) n'est pas un mur,
un escalier arrête la pièce comme un mur. Plan synthétique, avec calque Mur
(le dallage et les marches sont sur le calque des murs, cas le plus dur)."""
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
pg = d.new_page(width=1600, height=1000)
mur = d.add_ocg("Mur")


def wall(x0, y0, x1, y1):
    pg.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=(0, 0, 0), fill=(1, 1, 1), width=0.3, oc=mur)


# -- terrace 6.0 m x 3.6 m, tiles 60 cm, closed by walls ---------------------
x0, y0, T = 200.0, 200.0, 0.2 * S
W, H = 6.0 * S, 3.6 * S
wall(x0 - T, y0 - T, x0 + W + T, y0)
wall(x0 - T, y0 + H, x0 + W + T, y0 + H + T)
wall(x0 - T, y0, x0, y0 + H)
wall(x0 + W, y0, x0 + W + T, y0 + H)
step = 0.6 * S
for k in range(1, 10):                      # vertical tile joints, one piece per tile
    for m in range(6):
        pg.draw_line((x0 + k * step, y0 + m * step), (x0 + k * step, y0 + (m + 1) * step),
                     color=(0, 0, 0), width=0.2, oc=mur)
for m in range(1, 6):                       # horizontal tile joints
    for k in range(10):
        pg.draw_line((x0 + k * step, y0 + m * step), (x0 + (k + 1) * step, y0 + m * step),
                     color=(0, 0, 0), width=0.2, oc=mur)
pg.insert_text((x0 + W / 2, y0 + H / 2 + 3), "21.60 m²", fontsize=6)

# -- room 5.0 m x 3.0 m whose right part (1.0 m wide) is a staircase -----------
x1, y1 = 900.0, 200.0
W2, H2 = 5.0 * S, 3.0 * S
wall(x1 - T, y1 - T, x1 + W2 + T, y1)
wall(x1 - T, y1 + H2, x1 + W2 + T, y1 + H2 + T)
wall(x1 - T, y1, x1, y1 + H2)
wall(x1 + W2, y1, x1 + W2 + T, y1 + H2)
sx = x1 + 4.0 * S                            # stairs from 4.0 m to 5.0 m, 10 treads
for k in range(11):
    yy = y1 + k * 0.28 * S
    pg.draw_line((sx, yy), (x1 + W2, yy), color=(0, 0, 0), width=0.2, oc=mur)
path = os.path.join(OUT, "plan_dallage_escalier.pdf")
d.save(path)
d.close()

doc = PdfDocument(path)
doc.set_ratio_scale(50)
s = doc.scale_points_per_meter
res = rd.detect_room(doc, 0, (x0 + 0.3 * S, y0 + 0.3 * S))      # click in one tile
area = doc.poly_area(res["polygon"]) / s / s
check("tiled terrace measured whole, not one tile", abs(area - 21.6) < 0.3, round(area, 2))

res = rd.detect_room(doc, 0, (x1 + 1.0 * S, y1 + 1.5 * S))
area = doc.poly_area(res["polygon"]) / s / s
check("room stops at the staircase", abs(area - 12.0) < 0.4, round(area, 2))

print()
print("SMOKE 12 OK" if not fails else f"SMOKE 12 FAILED: {fails}")
