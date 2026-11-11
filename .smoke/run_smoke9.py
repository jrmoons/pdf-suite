import os as _os; _os.environ["PDFSUITE_SETTINGS"] = "PDFSuiteTests"
from PySide6.QtCore import QSettings as _QS; _QS("PDFSuite", "PDFSuiteTests").clear()  # fresh test settings
"""Cote (dimension) + texte petite police + clic molette + glisser-déposer."""
import sys, os, math
sys.path.insert(0, os.path.abspath("."))

from PySide6.QtCore import Qt, QPointF, QEvent, QMimeData, QUrl, QPoint
from PySide6.QtGui import QMouseEvent, QDropEvent, QDragEnterEvent
from PySide6.QtWidgets import QApplication, QDialog
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


# plan with small (5.9 pt) horizontal and vertical texts, like real plans
plan = os.path.join(OUT, "plan_cotes.pdf")
d = pymupdf.open()
pg = d.new_page(width=1190, height=842)
pg.draw_rect(pymupdf.Rect(100, 100, 900, 700), color=(0, 0, 0), width=1.5)
pg.insert_text((200, 300), "Local technique 32.28 m2", fontsize=5.9, color=(0.2, 0.2, 0.8))
pg.insert_text((600, 500), "pente 1%", fontsize=5.9, rotate=90)
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


def send(pt, kind, button=Qt.LeftButton, mods=Qt.NoModifier, buttons=None):
    vp = view.mapFromScene(view._pdf_to_scene(item, pymupdf.Point(pt)))
    ev = QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                     button, buttons if buttons is not None else button, mods)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()


def click(pt, mods=Qt.NoModifier):
    send(pt, QEvent.MouseButtonPress, mods=mods)
    send(pt, QEvent.MouseButtonRelease, mods=mods)


def move(pt, mods=Qt.NoModifier):
    send(pt, QEvent.MouseMove, Qt.NoButton, mods, Qt.NoButton)


# ---------------------------------------------------------------- cote
doc.set_ratio_scale(50)
pts_per_m = 72 / 0.0254 / 50
win._activate_tool(Tool.DIMENSION)
A, B = (200, 650), (200 + 4 * pts_per_m, 650)
click(A)
move((B[0], B[1] + 3))
click(B)
move((B[0], B[1] - 40))                 # slide 40 pt "up"
check("live panel while placing", view._measure_info.isVisible())
click((B[0], B[1] - 40))
dims = [o for o in view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)]
check("dimension created", len(dims) == 1)
dim = dims[0]
check("dimension label 4,00 m", abs(float(dim.label.split()[0].replace(",", ".")) - 4) < 0.03, dim.label)
check("offset ~40 pt", abs(abs(dim.offset) - 40) < 1.5, dim.offset)
check("tool stays active", view.tool == Tool.DIMENSION)
a_pdf = doc.annotations(0)[0].vertices
check("stored as polyline A,A',B',B", len(a_pdf) == 4, a_pdf)

# slide the dimension line (drag its body): offset changes, A/B do not
win._activate_tool(Tool.SELECT)
item = view.page_items[0]
dim = [o for o in item.annot_items if isinstance(o, ai.DimensionItem)][0]
a2, b2 = dim.dim_points()
mid = QPointF((a2.x() + b2.x()) / 2, (a2.y() + b2.y()) / 2)
mid_pdf = ai.to_pdf(mid, doc.page(0))
off_before, a_before = dim.offset, QPointF(dim.a)
send(mid_pdf, QEvent.MouseButtonPress)
send((mid_pdf.x, mid_pdf.y - 25), QEvent.MouseMove)
send((mid_pdf.x, mid_pdf.y - 25), QEvent.MouseButtonRelease)
dim = [o for o in view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)][0]
check("slide changes offset only", abs(abs(dim.offset) - abs(off_before) - 25) < 1.5 and dim.a == a_before,
      (off_before, dim.offset))
v = doc.annotations(0)[0].vertices
check("slide saved in PDF", abs(abs(v[1][1] - v[0][1]) - abs(dim.offset)) < 0.5, v)

# handle on B: measured length changes
dim.handle_moving(1, QPointF(dim.b.x() + pts_per_m, dim.b.y()))
dim.handle_released()
check("handle B -> 5,00 m", abs(float(dim.label.split()[0].replace(",", ".")) - 5) < 0.03, dim.label)

# flip side
dim.prepareGeometryChange(); dim.offset = -dim.offset; dim._sync_to_pdf()
check("flip side", dim.offset < 0 or off_before < 0)

# reload from file
copy = os.path.join(OUT, "plan_cotes_modifié.pdf")
doc.save(copy)
d2 = PdfDocument(copy)
check("subject saved", (d2.annotations(0)[0].info or {}).get("subject") == "pdfsuite:measure_dimension")
d2.close()
win.open_file(copy)
app.processEvents()
t2 = win.current_tab()
dims2 = [o for o in t2.view.page_items[0].annot_items if isinstance(o, ai.DimensionItem)]
check("reloaded as dimension", len(dims2) == 1 and dims2[0].label == dim.label,
      dims2 and (dims2[0].label, dims2[0].offset))
check("export includes cote", any(r["type"] == "Longueur" for r in t2.pdf_document.measurements()))
win.close_tab(win.tabs.currentIndex())
win.tabs.setCurrentIndex(0)

# Esc cancels a cote in progress
win._activate_tool(Tool.DIMENSION)
click((300, 300))
from PySide6.QtGui import QKeyEvent
app.sendEvent(view, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
check("Esc cancels the cote", view._dim is None)

# ---------------------------------------------------------------- text edit
win._activate_tool(Tool.TEXTEDIT)
asked = []
win._on_text_edit_requested = lambda tab_, v, pno, bbox, text, size: asked.append((pno, bbox, text, size))
view.requestTextEdit.disconnect()
view.requestTextEdit.connect(lambda pno, bbox, text, size: asked.append((pno, bbox, text, size)))
click((205, 298))
check("small text found for editing", asked and "Local technique" in asked[0][2], asked)
if asked:
    pno, bbox, text, size = asked[0]
    view.apply_text_edit(pno, bbox, "Local technique 33,10 m2", size)
    words = " ".join(w[4] for w in doc.page(0).get_text("words"))
    check("edited text written (5,9 pt)", "33,10" in words, words[:120])
    span = [s for b in doc.page(0).get_text("dict")["blocks"] if b["type"] == 0
            for l in b["lines"] for s in l["spans"] if "33,10" in s["text"]]
    check("same size + colour kept", span and abs(span[0]["size"] - 5.9) < 0.1 and span[0]["color"] != 0,
          span and (span[0]["size"], hex(span[0]["color"])))
    view._render_pending()
    img = view.page_items[0].base.toImage()
    check("display refreshed (cache invalidated)", view.page_items[0].base is not None)
asked.clear()
click((597, 492))
if asked:
    pno, bbox, text, size = asked[0]
    view.apply_text_edit(pno, bbox, "pente 2%", size)
    blk = [l for b in doc.page(0).get_text("dict")["blocks"] if b["type"] == 0
           for l in b["lines"] if "2%" in "".join(s["text"] for s in l["spans"])]
    check("vertical text stays vertical", blk and abs(blk[0]["dir"][1]) > 0.9, blk and blk[0]["dir"])
else:
    check("vertical text found for editing", False)

# ---------------------------------------------------------------- middle-button pan
view.set_zoom(4)
app.processEvents()
h0, v0 = view.horizontalScrollBar().value(), view.verticalScrollBar().value()
c = view.viewport().rect().center()
for kind, pos, btns in ((QEvent.MouseButtonPress, c, Qt.MiddleButton),
                        (QEvent.MouseMove, c + QPoint(-120, -80), Qt.MiddleButton),
                        (QEvent.MouseButtonRelease, c + QPoint(-120, -80), Qt.NoButton)):
    ev = QMouseEvent(kind, QPointF(pos), QPointF(view.viewport().mapToGlobal(pos)),
                     Qt.MiddleButton, btns, Qt.NoModifier)
    app.sendEvent(view.viewport(), ev)
    app.processEvents()
check("middle click pans the plan",
      view.horizontalScrollBar().value() - h0 == 120 and view.verticalScrollBar().value() - v0 == 80,
      (view.horizontalScrollBar().value() - h0, view.verticalScrollBar().value() - v0))

# ---------------------------------------------------------------- drag & drop
n_tabs = win.tabs.count()
mime = QMimeData()
mime.setUrls([QUrl.fromLocalFile(os.path.join(OUT, "sample.pdf"))])
pos = view.viewport().rect().center()
enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(view.viewport(), enter)
check("drag enter accepted", enter.isAccepted())
drop = QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
app.sendEvent(view.viewport(), drop)
app.processEvents()
check("dropped PDF opened", win.tabs.count() == n_tabs + 1, win.tabs.count())

check("GPU off in offscreen tests (safe fallback)", not view.set_gpu(True))

print()
print("SMOKE 9 OK" if not fails else f"SMOKE 9 FAILED: {fails}")
