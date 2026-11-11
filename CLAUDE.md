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
- Règle : ne citer aucun logiciel PDF tiers comme source ou inspiration (code, README, commits).
- Pas encore fait : annuler/refaire, OCR, recherche plein texte, impression, conversions,
  combiner des fichiers, mesure de surface, compression.
