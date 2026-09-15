import sys
import os

sys.path.insert(0, os.path.abspath("."))

from PySide6.QtWidgets import QApplication
from pdfsuite.main_window import MainWindow
from pdfsuite.tools import Tool
import pymupdf

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1280, 860)
win.show()

win.open_file(os.path.abspath(".smoke/sample.pdf"))
app.processEvents()
tab = win.current_tab()
assert tab is not None, "no tab opened"
print("Tab opened, pages =", tab.pdf_document.page_count)

# force render of all pages (bypass virtualization) for the screenshot
for i in range(tab.pdf_document.page_count):
    tab.view.refresh_page(i)
app.processEvents()

win.grab().save(".smoke/01_opened.png")

# -- annotation tools ------------------------------------------------
win._select_tool(Tool.HIGHLIGHT)
win.pick_color  # not invoking dialog (headless); set color directly
tab.view.set_color((1.0, 0.85, 0.2))
rect = pymupdf.Rect(72, 145, 300, 165)
words = tab.pdf_document.words_in_rect(0, rect)
print("words in rect:", len(words))
from pdfsuite.page_view import _rect_to_quad
quads = [_rect_to_quad(w) for w in words] or [_rect_to_quad(rect)]
tab.pdf_document.add_highlight(0, quads, (1.0, 0.85, 0.2))
tab.view.refresh_page(0)

tab.pdf_document.add_note(0, pymupdf.Point(500, 100), "Ceci est une note de test")
tab.view.refresh_page(0)

tab.pdf_document.add_rect(1, pymupdf.Rect(100, 300, 300, 400), (0.9, 0.1, 0.1))
tab.view.refresh_page(1)

tab.pdf_document.add_ink(2, [[pymupdf.Point(100, 500), pymupdf.Point(150, 550), pymupdf.Point(200, 500)]], (0.1, 0.6, 0.1))
tab.view.refresh_page(2)

app.processEvents()
win.grab().save(".smoke/02_annotations.png")

# -- text edit (simulate the flow directly) --------------------------
blocks = tab.pdf_document.text_blocks(0)
block = [b for b in blocks if b.get("type") == 0][0]
bbox = pymupdf.Rect(block["bbox"])
tab.view.apply_text_edit(0, bbox, "Texte remplace via PDF Suite", 14)
app.processEvents()
win.grab().save(".smoke/03_text_edit.png")

# -- page operations --------------------------------------------------
tab.pdf_document.insert_blank_page(1)
tab.pdf_document.rotate_page(2, 90)
tab.pdf_document.delete_pages([4])
tab.thumbnails.rebuild(tab.pdf_document)
tab.view.refresh_all()
app.processEvents()
print("pages after ops:", tab.pdf_document.page_count)
win.grab().save(".smoke/04_page_ops.png")

# -- save and reload to verify persistence -----------------------------
out_path = os.path.abspath(".smoke/output.pdf")
tab.pdf_document.save(out_path)
print("saved to", out_path)

check = pymupdf.open(out_path)
print("reopened pages:", check.page_count)
p0 = check[0]
annots_p0 = list(p0.annots() or [])
print("annots on page 0:", [a.type[1] for a in annots_p0])
p2 = check[2]
print("page2 rotation:", p2.rotation)
check.close()

# -- forms + widgets smoke (empty doc, just check no crash) -----------
tab.view.set_form_mode(True)
app.processEvents()
tab.view.set_form_mode(False)
app.processEvents()

print("SMOKE TEST OK")
