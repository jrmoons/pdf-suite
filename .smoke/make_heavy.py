"""Plan lourd de test : 3 pages A1 avec ~40 000 traits chacune."""
import random, pymupdf
random.seed(1)
d = pymupdf.open()
for n in range(3):
    p = d.new_page(width=2384, height=1684)
    sh = p.new_shape()
    for _ in range(40000):
        x, y = random.uniform(50, 2330), random.uniform(50, 1630)
        sh.draw_line((x, y), (x + random.uniform(-60, 60), y + random.uniform(-60, 60)))
    sh.finish(color=(0, 0, 0), width=0.4)
    sh.commit()
    for k in range(300):
        p.insert_text((random.uniform(50, 2300), random.uniform(50, 1630)), f"Cote {k}", fontsize=6)
d.save(".smoke/heavy.pdf", deflate=True)
print("ok")
