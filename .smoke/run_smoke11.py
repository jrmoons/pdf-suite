import os as _os; _os.environ["PDFSUITE_SETTINGS"] = "PDFSuiteTests"
from PySide6.QtCore import QSettings as _QS; _QS("PDFSuite", "PDFSuiteTests").clear()  # fresh test settings
"""Pièce auto (plan avec calques), cotes auto, Ctrl+Z, notes visibles,
zoom centré sous la souris."""
import sys, os, math
sys.path.insert(0, os.path.abspath("."))

from PySide6.QtCore import Qt, QPointF, QPoint, QEvent
from PySide6.QtGui import QMouseEvent, QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QInputDialog
import pymupdf

from pdfsuite.main_window import MainWindow
from pdfsuite.tools import Tool
from pdfsuite import annotation_items as ai

OUT = os.path.abspath(".smoke")
fails = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name, extra)
    if not cond:
        fails.append(name)


# -- a plan exported with layers, 1:50: room 4.00 m x 3.00 m -----------------
S = 72 / 0.0254 / 50          # points per real metre at 1:50
d = pymupdf.open()
pg = d.new_page(width=1190, height=842)
mur = d.add_ocg("Mur")
macro = d.add_ocg("Macro de fenêtre, porte")
x0, y0 = 300.0, 200.0
W, H, T = 4 * S, 3 * S, 0.2 * S            # inner size, wall thickness 20 cm
door_a, door_b = x0 + 1.0 * S, x0 + 1.9 * S  # 90 cm door in the bottom wall
walls = [pymupdf.Rect(x0 - T, y0 - T, x0 + W + T, y0),            # top
         pymupdf.Rect(x0 - T, y0, x0, y0 + H),                     # left
         pymupdf.Rect(x0 + W, y0, x0 + W + T, y0 + H),             # right
         pymupdf.Rect(x0 - T, y0 + H, door_a, y0 + H + T),         # bottom left
         pymupdf.Rect(door_b, y0 + H, x0 + W + T, y0 + H + T)]     # bottom right
for r in walls:
    pg.draw_rect(r, color=(0, 0, 0), fill=(0.6, 0.6, 0.6), width=0.3, oc=mur)
# door: leaf + swing arc (on the wall layer, as in real exports), threshold
pg.draw_line((door_a, y0 + H), (door_a, y0 + H - 0.9 * S), color=(0, 0, 0), width=0.3, oc=mur)
pg.draw_curve((door_a, y0 + H - 0.9 * S), (door_a + 0.9 * S, y0 + H - 0.9 * S),
              (door_b, y0 + H), color=(0, 0, 0), width=0.3, oc=mur)
for k in range(9):                                  # dashed threshold line
    xa = door_a + k * 0.1 * S
    pg.draw_line((xa, y0 + H), (xa + 0.07 * S, y0 + H), color=(0, 0, 0), width=0.3, oc=macro)
# a dimension line inside the room, along the left wall (no layer)
pg.draw_line((x0 + 0.1 * S, y0), (x0 + 0.1 * S, y0 + H), color=(0, 0, 0), width=0.3)
pg.insert_text((x0 + 0.15 * S, y0 + H / 2), "300", fontsize=6)
pg.insert_text((x0 + W / 2 - 20, y0 + H / 2), "Bureau", fontsize=8)
plan = os.path.join(OUT, "plan_calques.pdf")
d.save(plan)
d.close()

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()
win.open_file(plan)
app.processEvents()
tab = win.current_tab()
view = tab.view
doc = tab.pdf_document
item = view.page_items[0]
check("default scale 1:50", abs(doc.ratio() - 50) < 1e-6)

# -- Pièce auto --------------------------------------------------------------------
win._activate_tool(Tool.ROOM)
view.auto_room(item, (x0 + W / 2, y0 + H / 2 + 20))
app.processEvents()
polys = [o for o in view.page_items[0].annot_items if isinstance(o, ai.MeasurePolygonItem)]
check("room outline created", len(polys) == 1)
if polys:
    pts = [(p.x(), p.y()) for p in polys[0].points]
    A = doc.poly_area(pts) / S / S
    P = doc.poly_perimeter(pts) / S
    check("area 12,00 m² (±1 %)", abs(A - 12) < 0.12, f"{A:.3f} m²")
    check("perimeter 14,00 m (±1 %)", abs(P - 14) < 0.14, f"{P:.3f} m")
    check("label shows P and S", "S = " in polys[0].label and "P = " in polys[0].label, polys[0].label)
dims = [o for o in view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)]
labels = sorted(o.label for o in dims)
check("cotes: 4 sides + door chain", len(dims) == 7, labels)
check("door cote 0,90 m", any(l.startswith("0,9") for l in labels), labels)
check("overall bottom 4,00 m present", labels.count("4,00 m") >= 2, labels)
check("one undo step", doc.undo_name() == "Pièce automatique", doc.undo_name())

# -- Ctrl+Z removes the whole room at once, Ctrl+Y brings it back -----------------
n_annots = len(doc.annotations(0))
app.sendEvent(win, QKeyEvent(QEvent.ShortcutOverride, Qt.Key_Z, Qt.ControlModifier))
win.undo()
app.processEvents()
check("Ctrl+Z removes the room and its cotes", len(doc.annotations(0)) == 0, len(doc.annotations(0)))
win.redo()
app.processEvents()
check("Ctrl+Y restores them", len(doc.annotations(0)) == n_annots)

# -- highlight then undo ---------------------------------------------------------------
before = len(doc.annotations(0))
doc.add_highlight(0, [pymupdf.Rect(x0, y0 + 50, x0 + 100, y0 + 60).quad])
view.rebuild_annotations()
check("highlight added", len(doc.annotations(0)) == before + 1)
win.undo()
check("Ctrl+Z removes the last highlight", len(doc.annotations(0)) == before)

# -- manual area polygon -> automatic cotes (no layer needed) ---------------------------
win._activate_tool(Tool.MEASURE_AREA)
view.snap_to_grid = True


def send(pt, kind, button=Qt.LeftButton):
    vp = view.mapFromScene(view._pdf_to_scene(view.page_items[0], pymupdf.Point(pt)))
    ev = QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                     button, button, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()


win.undo()          # remove the room to start clean
n0 = len(doc.annotations(0))
for pt in ((x0 + 1, y0 + 1), (x0 + W - 1, y0 + 1), (x0 + W - 1, y0 + H - 1), (x0 + 1, y0 + H - 1)):
    send(pt, QEvent.MouseButtonPress); send(pt, QEvent.MouseButtonRelease)
send((x0 + 1, y0 + 1), QEvent.MouseButtonPress); send((x0 + 1, y0 + 1), QEvent.MouseButtonRelease)
dims = [o for o in view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)]
check("manual contour gets its cotes + door", len(dims) >= 5, sorted(o.label for o in dims))
check("contour snapped on the wall corners", any(isinstance(o, ai.MeasurePolygonItem) and
      abs(doc.poly_area([(p.x(), p.y()) for p in o.points]) / S / S - 12) < 0.05
      for o in view.page_items[0].annot_items))

# -- the P / S label of a room can be dragged, it stays where it was put ----------------
polys = [o for o in view.page_items[0].annot_items if isinstance(o, ai.MeasurePolygonItem)]
check("room outline present for the label test", bool(polys))
if polys:
    poly = polys[0]
    win._activate_tool(Tool.SELECT)
    c0 = poly._label_rect().center()
    target = c0 + QPointF(0.5 * S, 0.8 * S)

    def mouse(kind, scene_pt, buttons):
        vp = view.mapFromScene(view.page_items[0].pos() + scene_pt)
        ev = QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                         Qt.LeftButton, buttons, Qt.NoModifier)
        app.sendEvent(view.viewport(), ev)
        app.processEvents()

    before_pts = [QPointF(p) for p in poly.points]
    mouse(QEvent.MouseButtonPress, c0, Qt.LeftButton)
    mouse(QEvent.MouseMove, (c0 + target) / 2, Qt.LeftButton)
    mouse(QEvent.MouseMove, target, Qt.LeftButton)
    mouse(QEvent.MouseButtonRelease, target, Qt.NoButton)
    moved = poly._label_rect().center()
    check("label follows the mouse", (moved - target).manhattanLength() < 2, (moved, target))
    check("the room outline itself did not move",
          all((a - b).manhattanLength() < 0.01 for a, b in zip(before_pts, poly.points)))
    view.rebuild_annotations()
    polys2 = [o for o in view.page_items[0].annot_items if isinstance(o, ai.MeasurePolygonItem)]
    check("label position kept in the PDF", polys2 and
          (polys2[0]._label_rect().center() - target).manhattanLength() < 2)

# -- plan without layers: clear message, nothing created ----------------------------------
win.open_file(os.path.join(OUT, "plan_A.pdf") if os.path.exists(os.path.join(OUT, "plan_A.pdf"))
              else plan)
app.processEvents()
t2 = win.current_tab()
from pdfsuite import room_detect as rd
# a PDF without layers is now analysed too (walls = heaviest pen): either a
# room is found or a clear message is given, never a crash
try:
    res = rd.detect_room(t2.pdf_document, 0, (400, 300))
    check("flat PDF -> room found or explained", len(res["polygon"]) >= 3)
except rd.RoomError as e:
    check("flat PDF -> room found or explained", len(str(e)) > 20, str(e)[:60])
win.tabs.setCurrentIndex(0)

# -- notes: the text is visible ------------------------------------------------------------
QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("Prévoir une prise ici", True))
win._activate_tool(Tool.NOTE)
send((x0 + 50, y0 + 50), QEvent.MouseButtonPress)
notes = [o for o in view.page_items[0].annot_items if isinstance(o, ai.NoteItem)]
check("note created", len(notes) == 1)
if notes:
    icon, bubble = notes[0]._geometry()
    check("note text bubble shown next to the icon", bubble.width() > icon.width() * 3
          and notes[0].content == "Prévoir une prise ici")

# -- wheel zoom keeps the point under the mouse ------------------------------------------------
view.set_zoom(2.0)
app.processEvents()
pos = QPoint(300, 250)
before_pt = view.mapToScene(pos)
for up in (False, False, False, True):
    ev = QWheelEvent(QPointF(pos), QPointF(view.viewport().mapToGlobal(pos)), QPoint(),
                     QPoint(0, 120 if up else -120), Qt.NoButton, Qt.ControlModifier,
                     Qt.NoScrollPhase, False)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()
after_pt = view.mapToScene(pos)
check("zoom out/in stays under the mouse", (after_pt - before_pt).manhattanLength() < 2 / view.zoom + 1,
      (before_pt, after_pt))

print()
print("SMOKE 11 OK" if not fails else f"SMOKE 11 FAILED: {fails}")
