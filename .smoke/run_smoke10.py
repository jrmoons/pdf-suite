import os as _os; _os.environ["PDFSUITE_SETTINGS"] = "PDFSuiteTests"
from PySide6.QtCore import QSettings as _QS; _QS("PDFSuite", "PDFSuiteTests").clear()  # fresh test settings
"""Suppr, boutons en français, échelle 1:50 par défaut, aimant sur le dessin,
Maj sur les poignées de cote, surlignage des espaces, couleur en direct."""
import sys, os
sys.path.insert(0, os.path.abspath("."))

from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent, QKeyEvent, QColor
from PySide6.QtWidgets import QApplication, QMessageBox
import pymupdf

from pdfsuite.main_window import MainWindow
from pdfsuite.main import install_french
from pdfsuite.tools import Tool
from pdfsuite import annotation_items as ai

OUT = os.path.abspath(".smoke")
fails = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name, extra)
    if not cond:
        fails.append(name)


plan = os.path.join(OUT, "plan_lot3.pdf")
d = pymupdf.open()
pg = d.new_page(width=1190, height=842)
pg.draw_line((100, 400), (500, 400), color=(0, 0, 0), width=1)     # wall to snap on
pg.draw_line((500, 400), (500, 700), color=(0, 0, 0), width=1)
pg.insert_text((100, 200), "Local technique avec des espaces", fontsize=12)
d.save(plan)
d.close()

app = QApplication(sys.argv)
check("French Qt translation available", install_french(app) is None and app.translate(
    "QPlatformTheme", "Cancel") in ("Annuler",), app.translate("QPlatformTheme", "Cancel"))
win = MainWindow()
win.resize(1300, 850)
win.show()
win.open_file(plan)
app.processEvents()
tab = win.current_tab()
view = tab.view
doc = tab.pdf_document
item = view.page_items[0]


def send(pt, kind, button=Qt.LeftButton, buttons=None):
    vp = view.mapFromScene(view._pdf_to_scene(item, pymupdf.Point(pt)))
    ev = QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                     button, buttons if buttons is not None else button, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()


def click(pt):
    send(pt, QEvent.MouseButtonPress)
    send(pt, QEvent.MouseButtonRelease)


def move(pt):
    send(pt, QEvent.MouseMove, Qt.NoButton, Qt.NoButton)


# -- default scale 1:50 ------------------------------------------------------
check("default scale 1:50", doc.ratio() and abs(doc.ratio() - 50) < 1e-6, doc.ratio())
check("bar shows 1 cm = 0,5 m", abs(win.measure_bar.real.value() - 0.5) < 1e-6
      and win.measure_bar.paper_unit.currentText() == "cm", win.measure_bar.real.value())
check("default scale not marked as a modification", not doc.dirty)

# -- snap to the drawing -----------------------------------------------------
check("snap on by default", view.snap_to_grid and win.act_snap.isChecked())
win._activate_tool(Tool.DIMENSION)
click((103, 402))                     # 3-4 pt away from the wall end (100, 400)
move((497, 398))
check("snap marker shown", view._snap_marker is not None and view._snap_marker.isVisible())
click((497, 398))                     # near (500, 400)
move((497, 360))
click((497, 360))
dims = [o for o in view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)]
check("cote snapped exactly on wall ends", dims and abs(dims[0].a.x() - 100) < 0.01
      and abs(dims[0].b.x() - 500) < 0.01 and abs(dims[0].a.y() - 400) < 0.01,
      dims and (dims[0].a, dims[0].b))
# 400 pt at 1:50 = 400 / (72/0.0254/50) m
expected = 400 / (72 / 0.0254 / 50)
check("cote length exact", dims and dims[0].label == f"{expected:.2f}".replace(".", ",") + " m",
      dims and dims[0].label)

# -- Shift on a cote handle = orthogonal ----------------------------------------
dim = dims[0]
orig = QApplication.keyboardModifiers
QApplication.keyboardModifiers = staticmethod(lambda: Qt.ShiftModifier)
adj = dim.handles[1]._adjust(QPointF(620, 437))     # B dragged slightly off-horizontal
QApplication.keyboardModifiers = orig
check("Shift keeps the cote horizontal", abs(adj.y() - dim.a.y()) < 1e-6, adj)
adj2 = dim.handles[1]._adjust(QPointF(503, 703))    # without Shift: snaps to the corner (500,700)
check("handle snaps to drawing", abs(adj2.x() - 500) < 0.01 and abs(adj2.y() - 700) < 0.01, adj2)

# -- Delete key -----------------------------------------------------------------
win._activate_tool(Tool.SELECT)
dim = [o for o in view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)][0]
dim.setSelected(True)
n0 = len(doc.annotations(0))
view.setFocus()
app.sendEvent(view, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
app.processEvents()
check("Delete removes the selected cote", len(doc.annotations(0)) == n0 - 1
      and not [o for o in view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)])
check("its handles are gone too", not [o for o in view.page_items[0].annot_items
                                       if isinstance(o, ai.VertexHandle)])

# -- highlight covers spaces ------------------------------------------------------
win._activate_tool(Tool.HIGHLIGHT)
send((95, 188), QEvent.MouseButtonPress)
send((400, 205), QEvent.MouseMove)
send((400, 205), QEvent.MouseButtonRelease)
hl = [a for a in doc.annotations(0) if a.type[1] == "Highlight"]
v = hl[0].vertices if hl else []
check("one highlight quad per line (spaces included)", len(v) == 4, len(v))
words = [w for w in doc.page(0).get_text("words")]
check("quad spans first to last word", v and abs(min(p[0] for p in v) - words[0][0]) < 0.5
      and abs(max(p[0] for p in v) - words[-1][2]) < 0.5)

# -- colour window: live, no validation --------------------------------------------
win.pick_color()
app.processEvents()
dlg = win._color_dlg
check("colour window stays open (non modal)", dlg.isVisible() and not dlg.isModal())
dlg.setCurrentColor(QColor(0, 200, 0))
app.processEvents()
check("colour applied without validating", abs(view.current_color[1] - 200 / 255) < 1e-3 and view.current_color[0] < 1e-3, view.current_color)
send((95, 188), QEvent.MouseButtonPress)
send((300, 205), QEvent.MouseMove)
send((300, 205), QEvent.MouseButtonRelease)
hl = [a for a in doc.annotations(0) if a.type[1] == "Highlight"]
check("highlight while the window is open uses the new colour",
      hl and abs(hl[-1].colors["stroke"][1] - 200 / 255) < 0.01, hl and hl[-1].colors)
check("colour window still open", dlg.isVisible())
dlg.close()

# -- close prompt in French ---------------------------------------------------------
seen = []
orig_exec = QMessageBox.exec


def fake_exec(box):
    seen.extend(b.text() for b in box.buttons())
    [b for b in box.buttons() if b.text() == "Annuler"][0].click()
    return 0


QMessageBox.exec = fake_exec
win.close_tab(win.tabs.currentIndex())
QMessageBox.exec = orig_exec
check("close prompt buttons in French", set(seen) >= {"Enregistrer…", "Ne pas enregistrer", "Annuler"}, seen)
check("Annuler keeps the tab open", win.tabs.count() == 1)

print()
print("SMOKE 10 OK" if not fails else f"SMOKE 10 FAILED: {fails}")
