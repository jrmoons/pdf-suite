import sys, os
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
import pymupdf
from pdfsuite.main_window import MainWindow
from pdfsuite.tools import Tool

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1200, 820)
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
    ev = QMouseEvent(kind, QPointF(viewport_pos), QPointF(global_pos), button, button, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()


def click(p, button=Qt.LeftButton):
    send(p, button, QEvent.MouseButtonPress)
    send(p, button, QEvent.MouseButtonRelease)


def drag(p1, p2):
    send(p1, Qt.LeftButton, QEvent.MouseButtonPress)
    send(p2, Qt.LeftButton, QEvent.MouseMove)
    send(p2, Qt.LeftButton, QEvent.MouseButtonRelease)


view.doc.scale_points_per_meter = 100.0
win._select_tool(Tool.RECT)
view.set_color((0.85, 0.1, 0.1))
drag(pymupdf.Point(60, 400), pymupdf.Point(180, 460))

win._select_tool(Tool.ELLIPSE)
view.set_color((0.1, 0.5, 0.85))
drag(pymupdf.Point(220, 400), pymupdf.Point(320, 460))

win._select_tool(Tool.INK)
view.set_color((0.1, 0.7, 0.2))
send(pymupdf.Point(60, 480), Qt.LeftButton, QEvent.MouseButtonPress)
for x in range(70, 200, 10):
    send(pymupdf.Point(x, 480 + (x % 20)), Qt.LeftButton, QEvent.MouseMove)
send(pymupdf.Point(200, 480), Qt.LeftButton, QEvent.MouseButtonRelease)

win._select_tool(Tool.MEASURE_LINE)
view.set_color((0.0, 0.55, 0.9))
drag(pymupdf.Point(60, 550), pymupdf.Point(320, 550))

win._select_tool(Tool.MEASURE_PERIMETER)
click(pymupdf.Point(60, 620))
click(pymupdf.Point(320, 610))
click(pymupdf.Point(280, 720))
click(pymupdf.Point(80, 700))
click(pymupdf.Point(80, 700), button=Qt.RightButton)

win._select_tool(Tool.SELECT)
app.processEvents()
win.grab().save(".smoke/20_vector_shapes.png")
win.set_theme(True)
app.processEvents()
win.grab().save(".smoke/21_vector_shapes_dark.png")

print("SMOKE 6 OK")
