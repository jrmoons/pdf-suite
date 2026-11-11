# Notes projet

- Copie locale de l'utilisateur (Windows) : `C:\Users\JérémyMoons\.local\bin\pdf-suite`
- Exe autonome : `launcher.py` + PyInstaller. Construit par GitHub Actions
  (`.github/workflows/build-exe.yml`, artefact `PDFSuite-windows`) ou en local
  via `creer_raccourci.bat`, qui crée aussi le raccourci « PDF Suite » sur le Bureau.
- Lancement en développement : `pdfsuite.bat` (utilise le `.venv` local).
- Stack : Python + PySide6 + PyMuPDF (+ pikepdf). Tests de fumée dans `.smoke/`.
- Branche de travail : `claude/project-status-9a44mn` (`main` = commit initial seulement).
- Piège PyMuPDF : un seul objet `Page` par index (`PdfDocument._page_cache`). Ne jamais
  refaire des `doc[i]` répétés, sinon erreur « annotation not bound to any page ».
- Annotations = items vectoriels Qt (`annotation_items.py`), page rendue avec `annots=False`.
- Perf / zoom (2026-11-11) : **scène en points PDF** (`scene_scale` = 1), le zoom n'est
  qu'une transformation de vue (`set_zoom`), jamais de reconstruction de scène. `PageItem` =
  image de base plafonnée (`BASE_MAX_PX`) + tuile nette de la zone visible au zoom écran
  (`_render_pending`, différé). Poignées en `ItemIgnoresTransformations`, cotes de taille
  écran constante (`zoom_changed`). Ne jamais revenir à un rendu pleine page au zoom.
  Plan lourd de test : `.smoke/make_heavy.py`.
- Mesures : tout libellé passe par `PdfDocument.measure_label` (unité `PDFSuiteUnit`,
  précision `PDFSuiteDecimals`, échelle `PDFSuiteScale`, surfaces toujours en m²).
  Barre de propriétés = `measure_bar.py`. Pas de mesure sans échelle (`scaleRequired`).
- Rendu : `PdfDocument.display_list()` (cache, ~10x plus rapide pour les zones zoomées),
  invalider avec `invalidate_render(i)` à chaque changement de CONTENU de page.
  GPU : `PdfGraphicsView.set_gpu` (QOpenGLWidget) ; `viewport().grab()` rend BLANC avec le
  GPU → utiliser `QGraphicsView.render()` (loupe) ; vérifier visuellement via
  `QScreen.grabWindow`. Changer de viewport détruit ses widgets enfants (MeasureInfo recréé).
- Aimant = `PdfDocument.snap_index/snap_point` (points du dessin via `get_cdrawings`, hachage
  spatial, préparé au repos) ; `view.snap_to_grid` = interrupteur « Aimanter ». Échelle par
  défaut 1:50 en mémoire seulement (`scale_is_default`), pas écrite tant que non modifiée.
  Textes Qt en français : `main.install_french` (qtbase_fr.qm).
- Annuler/Rétablir = journal MuPDF (`PdfDocument.op()`, `_OPS` en bas de pdf_document.py) :
  TOUTE modification du PDF doit passer par une méthode de PdfDocument (sinon erreur « Can't
  alter an object other than in an operation »). `new_page`/`insert_pdf` refusés par le journal
  → `_swap_op` (copie du document). Copier des pages DEPUIS le document journalisé est refusé
  → `_plain_copy()`.
- Pièce auto = `room_detect.py` (numpy) : murs = éléments des CALQUES dont le nom contient
  mur/poteau/…, portes/fenêtres = calque « porte/fenêtre » (traits droits = seuils), arcs de
  porte ignorés. Plan sans calques → refus expliqué (la détection par image a été essayée et
  abandonnée : cotes et cloisons tracées pareil). Validé sur le plan réel Arlon RDC (1:50).
- Cote = `DimensionItem` (annotation_items), stockée en PolyLine A, A', B', B,
  subject `pdfsuite:measure_dimension`.
- Texte modifié : `replace_text_in_rect` réécrit à l'origine/couleur/direction du span
  (ancien bug : rien n'était réécrit sous 6 pt).
- Tests : chaque `.smoke/run_smoke*.py` utilise des réglages séparés
  (`PDFSUITE_SETTINGS=PDFSuiteTests`, `settings.py`) — ne jamais écrire dans les réglages
  réels de Jérémy.
- Exe local = version dossier `dist\PDFSuite\PDFSuite.exe` (démarrage rapide, raccourci Bureau) ;
  GitHub Actions produit toujours un exe fichier unique (portable).
- Règle : ne citer aucun logiciel PDF tiers comme source ou inspiration (code, README, commits).
- Préférences de Jérémy (2026-11-11) : implémenter les 52 idées par lots (testé + commit +
  push à chaque lot) ; ruban à onglets ; Ctrl+S = toujours « Enregistrer sous » (l'original
  n'est jamais écrasé, `PdfDocument.is_original`) ; l'outil reste actif, Échap → Sélection ;
  composants lourds acceptés : OCR Tesseract (fra) et PDF → Word/Excel ; PAS OpenCV ni pyhanko.
- Géométrie exacte des formes stockée dans une clé d'annotation `PDFSuiteGeom`
  (`PdfDocument.set_geom/get_geom`) ; échelle du plan dans la clé de catalogue `PDFSuiteScale`.
  Annotations maison identifiées par `subject` = `pdfsuite:…`.
- Fait : lot 1 « Plans / chantier » (surface, échelles, export CSV, comparaison, nuage,
  flèche, légende, tampons, grille + aimant, loupe, capture, inversion, vue fractionnée).
- À faire : annuler/refaire, combiner, pages vides/doublons, recadrer, redimensionner,
  découper/fusionner pages, en-tête/numérotation, filigrane, aplatir, caviardage,
  compression, OCR, signets, panneau commentaires, export images, impression,
  conversions Word/Excel, etc.
