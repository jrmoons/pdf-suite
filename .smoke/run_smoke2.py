import sys, os
sys.path.insert(0, os.path.abspath("."))
import pymupdf
from pdfsuite.pdf_document import PdfDocument

# -- build a PDF with an AcroForm text field + checkbox ----------------
doc = pymupdf.open()
page = doc.new_page(width=400, height=300)
page.insert_text((20, 30), "Formulaire de test", fontsize=14)

w1 = pymupdf.Widget()
w1.field_name = "nom"
w1.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
w1.field_value = ""
w1.rect = pymupdf.Rect(20, 50, 220, 75)
page.add_widget(w1)

w2 = pymupdf.Widget()
w2.field_name = "accepte"
w2.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
w2.field_value = False
w2.rect = pymupdf.Rect(20, 90, 40, 110)
page.add_widget(w2)

form_path = os.path.abspath(".smoke/form.pdf")
doc.save(form_path)
doc.close()

pdoc = PdfDocument(form_path)
widgets = pdoc.widgets(0)
print("widgets found:", [(w.field_name, w.field_type_string) for w in widgets])
for w in widgets:
    if w.field_type_string == "Text":
        w.field_value = "Jean Dupont"
        w.update()
    elif w.field_type_string == "CheckBox":
        w.field_value = True
        w.update()
pdoc.save(os.path.abspath(".smoke/form_filled.pdf"))

check = pymupdf.open(".smoke/form_filled.pdf")
cw = list(check[0].widgets())
print("after fill:", [(w.field_name, w.field_value) for w in cw])
check.close()

# -- merge / extract / split -------------------------------------------
main = PdfDocument(os.path.abspath(".smoke/sample.pdf"))
print("before insert:", main.page_count)
main.insert_pdf(form_path, at_index=1)
print("after insert:", main.page_count)
main.extract_pages([0, 1], os.path.abspath(".smoke/extract_out.pdf"))
ex = pymupdf.open(".smoke/extract_out.pdf")
print("extracted pages:", ex.page_count)
ex.close()

paths = main.split_at(os.path.abspath(".smoke"), "split", [(0, 1), (2, main.page_count - 1)])
print("split files:", [os.path.basename(p) for p in paths])
for p in paths:
    d = pymupdf.open(p)
    print(" ", os.path.basename(p), d.page_count, "pages")
    d.close()

# -- password protect roundtrip -----------------------------------------
main.set_password("secret123")
pw_path = os.path.abspath(".smoke/protected.pdf")
main.save_with_pending_encryption(pw_path)
reopened = pymupdf.open(pw_path)
print("needs_pass:", reopened.needs_pass)
print("auth wrong:", reopened.authenticate("bad"))
reopened2 = pymupdf.open(pw_path)
print("auth right:", reopened2.authenticate("secret123"))
reopened2.close()
reopened.close()

print("SMOKE 2 OK")
