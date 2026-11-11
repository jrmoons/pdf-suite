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
