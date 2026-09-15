import sys, os
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
from pdfsuite.main_window import MainWindow
from pdfsuite.tools import Tool

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1300, 860)
win.show()
win.open_file(os.path.abspath(".smoke/sample.pdf"))
app.processEvents()

tab = win.current_tab()
for i in range(tab.pdf_document.page_count):
    tab.view.refresh_page(i)
app.processEvents()

# light theme (default) screenshot
win.grab().save(".smoke/10_light_toolbar.png")

# ctrl+wheel zoom simulation
from PySide6.QtCore import QPoint, QPointF, Qt as QtNS
from PySide6.QtGui import QWheelEvent
view = tab.view
center = view.viewport().rect().center()
before_zoom = view.zoom
ev = QWheelEvent(
    QPointF(center), QPointF(view.mapToGlobal(center)),
    QPoint(0, 0), QPoint(0, 120),
    QtNS.NoButton, QtNS.ControlModifier, QtNS.ScrollUpdate, False,
)
app.sendEvent(view.viewport(), ev)
app.processEvents()
print("zoom before/after ctrl+wheel:", before_zoom, view.zoom)

# dark theme
win.set_theme(True)
app.processEvents()
win.grab().save(".smoke/11_dark_toolbar.png")

# back to light
win.set_theme(False)
app.processEvents()
win.grab().save(".smoke/12_light_again.png")

print("SMOKE 4 OK")
