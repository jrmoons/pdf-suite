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
- Perf (2026-11-11) : `PageItem` n'est PAS rendu au zoom complet. Image de base plafonnée
  (`BASE_MAX_PX`) étirée à la taille de la page + tuile nette de la zone visible au zoom exact
  (`_render_pending`, différé `DETAIL_DELAY_MS`). Ctrl+molette = transformation de vue
  instantanée puis `set_zoom` différé. Vignettes rendues une par une (QTimer).
  Ne jamais revenir à un rendu pleine page au zoom (plans A0/A1 = centaines de Mo, secondes).
  Plan lourd de test : `.smoke/make_heavy.py`.
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
