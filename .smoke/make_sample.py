import pymupdf

doc = pymupdf.open()
for i in range(5):
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), f"Page {i + 1}", fontsize=24)
    page.insert_text(
        (72, 150),
        "Ceci est un paragraphe de test pour verifier la selection de mots,\n"
        "le surlignage, le soulignement et l'edition de texte dans PDF Suite.\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        fontsize=12,
    )
doc.save(".smoke/sample.pdf")
print("sample created", doc.page_count)
doc.close()
