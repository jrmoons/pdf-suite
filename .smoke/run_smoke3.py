import sys, os
sys.path.insert(0, os.path.abspath("."))
from PySide6.QtWidgets import QApplication
from pdfsuite.main_window import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1000, 700)
win.show()
win.open_file(os.path.abspath(".smoke/form.pdf"))
app.processEvents()
tab = win.current_tab()
tab.view.refresh_page(0)
app.processEvents()

win.act_form_mode.setChecked(True)
win.toggle_form_mode(True)
app.processEvents()
print("form proxies:", len(tab.view._form_proxies))

# simulate typing into the text field widget
from PySide6.QtWidgets import QLineEdit, QCheckBox
for proxy in tab.view._form_proxies:
    w = proxy.widget()
    if isinstance(w, QLineEdit):
        w.setText("Jean Dupont")
        w.editingFinished.emit()
    elif isinstance(w, QCheckBox):
        w.setChecked(True)
app.processEvents()

win.grab().save(".smoke/05_form_mode.png")

win.act_form_mode.setChecked(False)
win.toggle_form_mode(False)
app.processEvents()
win.grab().save(".smoke/06_form_flattened_view.png")

out = os.path.abspath(".smoke/form_from_app.pdf")
tab.pdf_document.save(out)

import pymupdf
d = pymupdf.open(out)
ws = list(d[0].widgets())
print("saved values:", [(w.field_name, w.field_value) for w in ws])
d.close()
print("SMOKE 3 OK")
