"""Lot « Plans / chantier » + ruban : surface, échelles mémorisées dans le PDF,
export CSV des mesures, nuage / flèche / légende, tampons, grille + aimant,
capture, inversion, vue fractionnée, comparaison, Enregistrer sous seulement."""
import os as _os; _os.environ["PDFSUITE_SETTINGS"] = "PDFSuiteTests"
from PySide6.QtCore import QSettings as _QS; _QS("PDFSuite", "PDFSuiteTests").clear()  # fresh test settings
import sys, os, csv
sys.path.insert(0, os.path.abspath("."))

from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QInputDialog
import pymupdf

from pdfsuite.main_window import MainWindow
from pdfsuite.tools import Tool
from pdfsuite.pdf_document import PdfDocument
from pdfsuite import annotation_items as ai

OUT = os.path.abspath(".smoke")
fails = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name, extra)
    if not cond:
        fails.append(name)


# a fake "plan": a few lines; v2 has one wall moved and one added
def make_plan(path, variant):
    d = pymupdf.open()
    p = d.new_page(width=842, height=595)
    p.draw_rect(pymupdf.Rect(100, 100, 700, 500), color=(0, 0, 0), width=2)
    p.draw_line((400, 100), (400, 500) if variant == 1 else (400, 300), color=(0, 0, 0), width=2)
    if variant == 2:
        p.draw_line((100, 300), (700, 300), color=(0, 0, 0), width=2)
    p.insert_text((110, 90), "Plan RDC - indice " + ("A" if variant == 1 else "B"), fontsize=12)
    d.save(path)
    d.close()


plan_a = os.path.join(OUT, "plan_A.pdf")
plan_b = os.path.join(OUT, "plan_B.pdf")
make_plan(plan_a, 1)
make_plan(plan_b, 2)

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 850)
win.show()
win.open_file(plan_a)
app.processEvents()
tab = win.current_tab()
view = tab.view
doc = tab.pdf_document
view.refresh_page(0)
item = view.page_items[0]
win.measure_bar.auto_cotes.setChecked(False)   # this test counts only its own measures

check("ribbon tabs", win.ribbon.page_titles() ==
      ["Accueil", "Commentaires", "Mesures", "Pages", "Protéger", "Affichage"],
      win.ribbon.page_titles())


def send(pdf_point, button, kind, v=None):
    v = v or view
    it = v.page_items[0]
    page = v.doc.page(0)
    vis = pymupdf.Point(pdf_point) * ~page.derotation_matrix
    scene_pos = it.pos() + QPointF(vis.x, vis.y)
    vp = v.mapFromScene(scene_pos)
    ev = QMouseEvent(kind, QPointF(vp), QPointF(v.viewport().mapToGlobal(vp)),
                     button, button, Qt.NoModifier)
    app.sendEvent(v.viewport(), ev)
    app.processEvents()


def click(pt, button=Qt.LeftButton):
    send(pt, button, QEvent.MouseButtonPress)
    send(pt, button, QEvent.MouseButtonRelease)


def drag(p1, p2):
    send(p1, Qt.LeftButton, QEvent.MouseButtonPress)
    send(p2, Qt.LeftButton, QEvent.MouseMove)
    send(p2, Qt.LeftButton, QEvent.MouseButtonRelease)


def items_of(cls, v=None):
    v = v or view
    return [o for o in v.page_items[0].annot_items if isinstance(o, cls)]


# -- 17. scale preset 1:50, stored in the PDF -----------------------------
doc.set_ratio_scale(50)
check("scale 1:50 description", doc.scale_description() == "Échelle 1:50", doc.scale_description())
# 1:50 -> 20 mm of paper = 1 m real
pts_per_m = 20 * 72 / 25.4
check("scale value", abs(doc.scale_points_per_meter - pts_per_m) < 0.01)

# -- 16. area tool --------------------------------------------------------
view.setFocus()
win._activate_tool(Tool.MEASURE_AREA)
square = [(100, 100), (100 + 2 * pts_per_m, 100), (100 + 2 * pts_per_m, 100 + 3 * pts_per_m),
          (100, 100 + 3 * pts_per_m)]
for pt in square:
    click(pt)
click(square[0], Qt.RightButton)
areas = [o for o in items_of(ai.MeasurePolygonItem) if o.is_area]
check("area item created", len(areas) == 1)
check("area label ~6 m² (pixel rounding)", areas and abs(float(areas[0].label.split()[2].replace(",", ".")) - 6) < 0.08, areas and areas[0].label)
check("tool stays selected after use", view.tool == Tool.MEASURE_AREA)

# measure line 4 m
win._activate_tool(Tool.MEASURE_LINE)
drag((150, 450), (150 + 4 * pts_per_m, 450))
lines = items_of(ai.MeasureLineItem)
check("measure line 4 m without asking (pixel rounding)",
      lines and abs(float(lines[0].label.split()[0].replace(",", ".")) - 4.0) <= 0.02, lines and lines[0].label)

# -- 20. arrow / cloud / callout -----------------------------------------
win._activate_tool(Tool.ARROW)
drag((500, 150), (600, 220))
check("arrow item", any(o.kind == "arrow" for o in items_of(ai.ShapeItem)))

win._activate_tool(Tool.CLOUD)
drag((450, 350), (650, 450))
clouds = [o for o in items_of(ai.ShapeItem) if o.kind == "cloud"]
check("cloud item", len(clouds) == 1)
cloud = clouds[0]
before = doc.get_geom(cloud.annot)
cloud._apply_delta(QPointF(10, 5)); cloud._sync_to_pdf()
after = doc.get_geom(cloud.annot)
check("cloud moved, same size", abs((after[2] - after[0]) - (before[2] - before[0])) < 0.01
      and abs(after[0] - before[0] - 10) < 0.01, f"{before} -> {after}")

QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: ("Cloison déplacée\nvoir indice B", True))
win._activate_tool(Tool.CALLOUT)
drag((400, 250), (520, 280))
callouts = items_of(ai.CalloutItem)
check("callout item", len(callouts) == 1)
check("callout has tip handle", callouts and len(callouts[0].handles) == 1)

# -- 22. stamps -------------------------------------------------------------
win.stamp_combo.setCurrentText("BON POUR EXÉCUTION")
win._on_stamp_chosen(0)
check("stamp tool active", view.tool == Tool.STAMP)
click((700, 540))
stamps = items_of(ai.StampItem)
check("stamp item", len(stamps) == 1)
check("stamp text has date", stamps and "BON POUR EXÉCUTION" in stamps[0].text
      and "/20" in stamps[0].text, stamps and stamps[0].text)

# -- Échap -> Sélection ---------------------------------------------------
app.sendEvent(view, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
app.processEvents()
check("Escape returns to Select", view.tool == Tool.SELECT and win._tool_actions[Tool.SELECT].isChecked())

# -- 21. grid + snap --------------------------------------------------------
win.act_snap.setChecked(True); win.toggle_snap(True)
win.act_grid.setChecked(True); win.toggle_grid(True)
check("grid shown + snap on", view.show_grid and view.snap_to_grid)
step = view.grid_spacing()
win._activate_tool(Tool.LINE)
p = view._scene_to_pdf_point(item, view._pdf_to_scene(item, pymupdf.Point(203.3, 207.9)))
check("snap to grid", abs(p.x / step - round(p.x / step)) < 1e-6, f"step={step:.2f} pt -> {p}")
check("grid description in m", "Grille" in view.grid_description(), view.grid_description())
win._activate_tool(Tool.SELECT)
app.processEvents()
win.grab().save(os.path.join(OUT, "30_plans_tools.png"))
win.act_snap.setChecked(False); win.toggle_snap(False)
win.act_grid.setChecked(False); win.toggle_grid(False)

# -- 23. capture -------------------------------------------------------------
img = view.capture_to_clipboard(item, pymupdf.Point(90, 90), pymupdf.Point(400, 300))
clip = QApplication.clipboard().image()
check("capture in clipboard", not clip.isNull() and clip.width() == img.width(), f"{clip.width()}x{clip.height()}")

# -- 24. invert ---------------------------------------------------------------
win.act_invert.setChecked(True); win.toggle_invert(True)
app.processEvents()
view.refresh_page(0)
c = view.page_items[0].base.toImage().pixelColor(5, 5)
check("inverted page is dark", c.lightness() < 40, c.name())
win.act_invert.setChecked(False); win.toggle_invert(False)

# -- 25. split view -----------------------------------------------------------
win.act_split_view.setChecked(True); win.toggle_split_view(True)
app.processEvents()
check("second view", tab.view2 is not None and len(tab.views()) == 2)
n_before = len(items_of(ai.ShapeItem, tab.view2))
win._activate_tool(Tool.RECT)
drag((120, 120), (200, 180))
n_after = len(items_of(ai.ShapeItem, tab.view2))
check("split view synced", n_after == n_before + 1, f"{n_before} -> {n_after}")
win.grab().save(os.path.join(OUT, "31_split_view.png"))
win.act_split_view.setChecked(False); win.toggle_split_view(False)
app.processEvents()
check("split view closed", tab.view2 is None)

# -- 18. export CSV -----------------------------------------------------------
csv_path = os.path.join(OUT, "mesures.csv")
n = doc.export_measurements_csv(csv_path)
with open(csv_path, encoding="utf-8-sig") as f:
    rows = list(csv.reader(f, delimiter=";"))
check("csv rows", n == 2 and rows[1][0] == "N°", rows[:3])
check("csv area value", any(r[2] == "Surface" and abs(float(r[4].replace(",", ".")) - 6) < 0.08
                            for r in rows[1:] if len(r) > 4))

# -- save: never the original, scale persisted -----------------------------
try:
    doc.save(plan_a)
    check("refuses to overwrite original", False)
except PermissionError:
    check("refuses to overwrite original", True)
copy = os.path.join(OUT, "plan_A_modifié.pdf")
doc.save(copy)
d2 = PdfDocument(copy)
check("scale persisted in pdf", d2.scale_description() == "Échelle 1:50", d2.scale_description())
subjects = sorted((a.info or {}).get("subject", "") for a in d2.annotations(0))
check("annotation kinds saved", all(s in subjects for s in (
    "pdfsuite:arrow", "pdfsuite:callout", "pdfsuite:cloud", "pdfsuite:measure_area",
    "pdfsuite:measure_line", "pdfsuite:stamp")), subjects)
d2.close()

# reopen copy in the UI: items rebuilt with the right classes
win.open_file(copy)
app.processEvents()
t2 = win.current_tab()
t2.view.refresh_page(0)
kinds = sorted(type(o).__name__ for o in t2.view.page_items[0].annot_items)
check("reloaded item types", all(k in kinds for k in ("CalloutItem", "StampItem", "MeasurePolygonItem",
                                                      "MeasureLineItem", "ShapeItem")), kinds)
win.grab().save(os.path.join(OUT, "32_reloaded.png"))

# -- 19. compare -----------------------------------------------------------
win.tabs.setCurrentIndex(0)
from pdfsuite.compare import build_comparison_pdf
other = pymupdf.open(plan_b)
data, n = build_comparison_pdf(doc, other, "plan_A.pdf", "plan_B.pdf")
cmp_doc = PdfDocument(data=data, title="Comparaison")
check("comparison pages", n == 1 and cmp_doc.page_count == 1)
pix = cmp_doc.page(0).get_pixmap(dpi=40)
pix.save(os.path.join(OUT, "33_compare.png"))
# removed segment (400,300)-(400,500) must be red, added (100..700, 300) green
def px(x, y):
    zx = pix.width / cmp_doc.page(0).rect.width
    s = pix.pixel(int(x * zx), int((y + 34) * zx))
    return s
red = px(400, 420)
green = px(250, 300)
check("removed wall red", red[0] > 150 and red[1] < 120, red)
check("added wall green", green[1] > 100 and green[0] < 120, green)
other.close()

print()
print("SMOKE 7 OK" if not fails else f"SMOKE 7 FAILED: {fails}")
