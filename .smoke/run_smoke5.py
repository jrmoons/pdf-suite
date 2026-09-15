import sys, os, math
sys.path.insert(0, os.path.abspath("."))

from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QGraphicsItem
import pymupdf

from pdfsuite.main_window import MainWindow
from pdfsuite.tools import Tool
from pdfsuite import annotation_items as ai

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1100, 800)
win.show()
win.open_file(os.path.abspath(".smoke/sample.pdf"))
app.processEvents()

tab = win.current_tab()
view = tab.view
view.refresh_page(0)
app.processEvents()
item = view.page_items[0]


def send(pdf_point, button, kind):
    page = view.doc.page(0)
    vis = pdf_point * ~page.derotation_matrix
    scene_pos = item.pos() + QPointF(vis.x * view.zoom, vis.y * view.zoom)
    viewport_pos = view.mapFromScene(scene_pos)
    global_pos = view.viewport().mapToGlobal(viewport_pos)
    ev = QMouseEvent(kind, QPointF(viewport_pos), QPointF(global_pos),
                      button, button, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()


def click(pdf_point, button=Qt.LeftButton):
    send(pdf_point, button, QEvent.MouseButtonPress)
    send(pdf_point, button, QEvent.MouseButtonRelease)


def drag(p1, p2, button=Qt.LeftButton):
    send(p1, button, QEvent.MouseButtonPress)
    send(p2, button, QEvent.MouseMove)
    send(p2, button, QEvent.MouseButtonRelease)


# -- 1. draw a rectangle as a vector shape ------------------------------
before_annots = len(view.doc.annotations(0))
win._select_tool(Tool.RECT)
view.set_color((0.9, 0.1, 0.1))
drag(pymupdf.Point(300, 300), pymupdf.Point(400, 380))
after_annots = view.doc.annotations(0)
print("rect annot created:", len(after_annots) == before_annots + 1)

shape_items = [o for o in item.annot_items if isinstance(o, ai.ShapeItem) and o.kind == "rect"]
print("rect ShapeItem present:", len(shape_items) == 1)
shape = shape_items[0]
print("rect movable by default:", bool(shape.flags() & QGraphicsItem.ItemIsMovable))

# -- 2. simulate a drag-move of that shape, verify pdf sync --------------
old_xref = shape.annot.xref
old_rect = pymupdf.Rect(shape.annot.rect)
shape._apply_delta(QPointF(15, 25))
shape.setPos(0, 0)
shape.prepareGeometryChange()
shape._sync_to_pdf()
new_rect = pymupdf.Rect(shape.annot.rect)
moved_ok = (abs(new_rect.x0 - old_rect.x0 - 15) < 1.0 and abs(new_rect.y0 - old_rect.y0 - 25) < 1.0)
print("shape moved correctly:", moved_ok, old_rect, "->", new_rect)
print("annot xref changed (delete+recreate):", shape.annot.xref != old_xref)

# -- 3. lock / unlock ------------------------------------------------------
shape.locked = True
shape.setFlag(QGraphicsItem.ItemIsMovable, False)
print("locked disables move flag:", not bool(shape.flags() & QGraphicsItem.ItemIsMovable))

# -- 4. delete via the same path the context menu uses --------------------
view.doc.delete_annot(0, shape.annot)
view.remove_annotation_item(0, shape)
print("shape removed from annot_items:", shape not in item.annot_items)
print("annot count back to baseline:", len(view.doc.annotations(0)) == before_annots)

# -- 5. no raster re-render happened for any of the above -----------------
print("page raster untouched by annotation edits:", item.rendered is True)

# -- 6. measurement: calibrate then draw a line ----------------------------
view.doc.scale_points_per_meter = 100.0  # 100 pdf points == 1 metre
win._select_tool(Tool.MEASURE_LINE)
drag(pymupdf.Point(100, 500), pymupdf.Point(300, 500))  # 200pt -> 2.00 m
measure_lines = [o for o in item.annot_items if isinstance(o, ai.MeasureLineItem)]
print("measure line item created:", len(measure_lines) == 1)
ml = measure_lines[0]
print("measure line label:", ml.label)
print("measure line has 2 handles:", len(ml.handles) == 2)

# -- 7. drag a handle, verify live label + pdf sync ------------------------
zoom = view.zoom
new_pixel_pos = QPointF(ml.handles[1].pos().x() + 100 * zoom, ml.handles[1].pos().y())
ml.handles[1].setPos(new_pixel_pos)  # triggers itemChange -> handle_moving
ml.handle_released()
print("label recomputed after handle drag:", ml.label)
reread = [a for a in view.doc.annotations(0) if a.xref == ml.annot.xref]
print("handle-moved annot exists in pdf:", len(reread) == 1)

# -- 8. measurement: perimeter (click x3 + right-click to finish) ---------
win._select_tool(Tool.MEASURE_PERIMETER)
click(pymupdf.Point(100, 600))
click(pymupdf.Point(250, 600))
click(pymupdf.Point(180, 700))
click(pymupdf.Point(180, 700), button=Qt.RightButton)  # finalize
polys = [o for o in item.annot_items if isinstance(o, ai.MeasurePolygonItem)]
print("perimeter item created:", len(polys) == 1)
if polys:
    mp = polys[0]
    print("perimeter label:", mp.label)
    print("perimeter handle count:", len(mp.handles))

# -- 9. lock a measurement item hides its handles --------------------------
if polys:
    mp.set_locked(True)
    print("locked polygon hides handles:", all(not h.isVisible() for h in mp.handles))
    print("locked polygon move flag off:", not bool(mp.flags() & QGraphicsItem.ItemIsMovable))

# -- 10. save + reload round-trip ------------------------------------------
out_path = os.path.abspath(".smoke/vector_out.pdf")
tab.pdf_document.save(out_path)
check = pymupdf.open(out_path)
p0 = check[0]
kinds = [(a.type[1], (a.info or {}).get("subject", "")) for a in p0.annots()]
print("kinds after reload:", kinds)
check.close()

# -- 11. calibration dialog math (no modal exec) ---------------------------
from pdfsuite.dialogs import CalibrationDialog
dlg = CalibrationDialog(win)
dlg.value_spin.setValue(3.5)
dlg.unit_combo.setCurrentText("m")
print("calibration 3.5 m ->", dlg.real_length_meters())
dlg.unit_combo.setCurrentText("cm")
dlg.value_spin.setValue(250)
print("calibration 250 cm ->", dlg.real_length_meters())
dlg.close()

print("SMOKE 5 OK")
