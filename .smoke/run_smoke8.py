"""Zoom instantané + barre de propriétés Mesure + règles + barre d'état."""
import os as _os; _os.environ["PDFSUITE_SETTINGS"] = "PDFSuiteTests"
from PySide6.QtCore import QSettings as _QS; _QS("PDFSuite", "PDFSuiteTests").clear()  # fresh test settings
import sys, os, time
sys.path.insert(0, os.path.abspath("."))

from PySide6.QtCore import Qt, QPointF, QPoint, QEvent
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog
import pymupdf

from pdfsuite.main_window import MainWindow
from pdfsuite.tools import Tool
from pdfsuite import annotation_items as ai
from pdfsuite import dialogs

OUT = os.path.abspath(".smoke")
fails = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name, extra)
    if not cond:
        fails.append(name)


if not os.path.exists(os.path.join(OUT, "heavy.pdf")):
    import subprocess
    subprocess.run([sys.executable, os.path.join(OUT, "make_heavy.py")], check=True)

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()
app.processEvents()

# ---------------------------------------------------------------- zoom speed
win.open_file(os.path.join(OUT, "heavy.pdf"))
app.processEvents()
tab = win.current_tab()
view = tab.view
view._render_pending()
items_before = list(view.page_items)


def wheel(v, up=True):
    c = v.viewport().rect().center()
    ev = QWheelEvent(QPointF(c), QPointF(v.viewport().mapToGlobal(c)), QPoint(),
                     QPoint(0, 120 if up else -120), Qt.NoButton, Qt.ControlModifier,
                     Qt.NoScrollPhase, False)
    app.sendEvent(v.viewport(), ev)


times = []
for i in range(8):
    t = time.perf_counter()
    wheel(view, up=i < 5)
    view.viewport().repaint()
    times.append((time.perf_counter() - t) * 1000)
check("wheel zoom < 40 ms per notch", max(times) < 40, [f"{x:.0f}" for x in times])
check("zoom does not rebuild the scene", view.page_items == items_before)
t = time.perf_counter()
view._render_pending()
check("sharp tile after pause < 0.6 s", time.perf_counter() - t < 0.6, f"{time.perf_counter() - t:.2f}s")
z0 = view.zoom
win.zoom_by(1.25)
check("zoom + button", abs(view.zoom - z0 * 1.25) < 1e-6)
win.zoom_combo.setEditText("200 %")
win._on_zoom_combo()
check("status zoom combo 200 %", abs(view.zoom - 2.66) < 1e-6, view.zoom)
win.fit_page()
check("fit page", view.zoom < 1.0, view.zoom)
win.close_tab(win.tabs.currentIndex())

# ---------------------------------------------------------------- measure bar
d = pymupdf.open()
d.new_page(width=842, height=595)
plan = os.path.join(OUT, "plan_mesure.pdf")
d.save(plan)
d.close()
win.open_file(plan)
app.processEvents()
tab = win.current_tab()
view = tab.view
doc = tab.pdf_document
item = view.page_items[0]
bar = win.measure_bar


def send(pt, kind, button=Qt.LeftButton, mods=Qt.NoModifier):
    sp = view._pdf_to_scene(item, pymupdf.Point(pt))
    vp = view.mapFromScene(sp)
    ev = QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                     button, button, mods)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()


def drag(p1, p2, mods=Qt.NoModifier):
    send(p1, QEvent.MouseButtonPress, mods=mods)
    send(((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2), QEvent.MouseMove, mods=mods)
    send(p2, QEvent.MouseMove, mods=mods)
    shown = view._measure_info.isVisible()
    send(p2, QEvent.MouseButtonRelease, mods=mods)
    return shown


def click(p, button=Qt.LeftButton):
    send(p, QEvent.MouseButtonPress, button)
    send(p, QEvent.MouseButtonRelease, button)


win._activate_tool(Tool.MEASURE_LINE)
check("measure bar visible with measure tool", win.measure_holder.isVisible())
check("bar asks for the scale", "Saisissez" in bar.warning.text())
required = []
view.scaleRequired.connect(lambda: required.append(1))
drag((100, 100), (300, 100))
check("no scale -> nothing drawn + scaleRequired", required and not doc.annotations(0))

# 1 cm on paper = 0,5 m real  -> 1:50
bar.paper.setValue(1); bar.paper_unit.setCurrentText("cm")
bar.real_unit.setCurrentText("m"); bar.real.setValue(0.5)
bar._apply_scale()
check("scale from bar = 1:50", abs(doc.ratio() - 50) < 1e-6, doc.ratio())
pts_per_m = 72 / 0.0254 / 50
shown = drag((100, 300), (100 + 3 * pts_per_m, 300))
lines = [o for o in item.annot_items if isinstance(o, ai.MeasureLineItem)]
check("live info panel while drawing", shown)
check("line 3,00 m", lines and abs(float(lines[0].label.split()[0].replace(",", ".")) - 3) < 0.03,
      lines and lines[0].label)

# unit -> cm, precision 0,1
bar.real_unit.setCurrentText("cm"); bar._on_unit_changed()
bar.precision.setCurrentIndex(1); bar._on_precision(1)
lines = [o for o in view.page_items[0].annot_items if isinstance(o, ai.MeasureLineItem)]
check("labels follow unit/precision", lines and lines[0].label.endswith(" cm")
      and "," in lines[0].label and len(lines[0].label.split(",")[1].split()[0]) == 1,
      lines and lines[0].label)
stored = (doc.annotations(0)[0].info or {}).get("content", "")
check("stored PDF label rewritten", stored.endswith(" cm"), stored)

# Shift: locked to 0/45/90°
start = (150, 400)
drag(start, (150 + 200, 400 + 30), mods=Qt.ShiftModifier)
annot = doc.annotations(0)[-1]
v = annot.vertices
check("Shift locks angle (horizontal)", abs(v[0][1] - v[1][1]) < 0.5, v)

# polygon area closed by clicking the first point
win._activate_tool(Tool.MEASURE_AREA)
sq = [(500, 100), (500 + 2 * pts_per_m, 100), (500 + 2 * pts_per_m, 100 + 2 * pts_per_m),
      (500, 100 + 2 * pts_per_m)]
for p in sq:
    click(p)
click(sq[0])
areas = [o for o in view.page_items[0].annot_items if isinstance(o, ai.MeasurePolygonItem)]
check("area closed by clicking first point", len(areas) == 1, areas and areas[0].label)

# calibration: 1 line of known length
class FakeCal:
    def __init__(self, *a, **k): pass
    def exec(self): return QDialog.Accepted
    def real_length_meters(self): return 2.0
import pdfsuite.page_view as pv
pv.CalibrationDialog = FakeCal
n_before = len(doc.annotations(0))
win.start_calibration()
drag((100, 500), (300, 500))
check("calibration sets scale (200 pt = 2 m)", abs(doc.scale_points_per_meter - 100) < 1,
      doc.scale_points_per_meter)
check("calibration line not kept", len(doc.annotations(0)) == n_before)

# rulers + status bar
check("rulers visible", view._hruler.isVisible() and view._vruler.isVisible())
check("page size in status bar", win.size_label.text().startswith("L :"), win.size_label.text())
send((200, 200), QEvent.MouseMove)
check("cursor X/Y in status bar", win.cursor_label.text().startswith("X :"), win.cursor_label.text())

# constant on-screen label size: bounding of label shrinks in scene units when zooming in
lab0 = lines[0]._label_rect().height() if lines else 0
view.set_zoom(view.zoom * 4)
lines = [o for o in view.page_items[0].annot_items if isinstance(o, ai.MeasureLineItem)]
lab1 = lines[0]._label_rect().height() if lines else 0
check("label keeps its screen size", lab0 and abs(lab1 * 4 - lab0) < 0.5, (lab0, lab1))
view.set_zoom(1.33)
win._activate_tool(Tool.MEASURE_LINE)
app.processEvents()
win.grab().save(os.path.join(OUT, "40_measure_bar.png"))

print()
print("SMOKE 8 OK" if not fails else f"SMOKE 8 FAILED: {fails}")
