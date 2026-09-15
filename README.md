# PDF Suite

Application PDF de bureau pour Windows (Python + PySide6 + PyMuPDF + pikepdf),
pensée pour remplacer un lecteur PDF limité par un outil que l'on enrichit
au fur et à mesure des besoins.

## Lancer l'application

```
pdfsuite.bat
pdfsuite.bat "C:\chemin\vers\document.pdf"
```

(la première ligne suffit depuis n'importe quel dossier, le `.bat` pointe
vers l'environnement virtuel `.venv` du projet)

## Fonctionnalités actuelles (V1)

- **Visionneuse** : ouverture multi-documents par onglets, défilement continu,
  zoom, panneau de vignettes (réorganisation par glisser-déposer).
- **Annotations vectorielles** : rectangle, ellipse, ligne, dessin à main
  levée restent des objets vectoriels déplaçables (outil « Sélectionner »,
  glisser pour repositionner) — clic droit dessus → Verrouiller/Déverrouiller
  la position ou Supprimer. Surligner, souligner, barrer, texte libre, note
  collante, gomme sont aussi disponibles (affichage + suppression).
- **Mesures** : outils « Mesurer une ligne » et « Périmètre » (clic à chaque
  coin de la pièce, clic droit ou Entrée pour terminer, Échap pour annuler).
  La première mesure demande l'échelle réelle du plan (longueur réelle
  représentée), puis elle est réutilisée automatiquement — « Réinitialiser
  l'échelle » dans la barre d'outils pour la redéfinir. Chaque mesure garde
  ses poignées de coin déplaçables pour recadrer la pièce si besoin.
- **Pages** : insérer une page vierge, supprimer, faire pivoter, réordonner
  (glisser les vignettes), insérer un autre PDF, extraire des pages vers un
  nouveau fichier, diviser un document en plusieurs fichiers.
- **Édition de texte** : outil « Modifier texte », clic sur un bloc de texte
  existant → boîte de dialogue d'édition (remplace le texte en place via
  rédaction + réinsertion, taille de police ajustable).
- **Formulaires** : mode « Formulaire » qui superpose des champs interactifs
  (texte, case à cocher, liste) sur les champs AcroForm du PDF.
- **Signature** : dessiner une signature à la souris et la déposer sur la page.
- **Sécurité** : ajout d'un mot de passe (chiffrement AES-256) à
  l'enregistrement ; ouverture de PDF déjà protégés par mot de passe.
- **Interface** : thème clair / sombre (bouton dans la barre d'outils ou menu
  Affichage, préférence mémorisée entre les lancements), barre d'outils avec
  icônes au-dessus du texte façon PDF-XChange, zoom Ctrl + molette centré
  sur le curseur.

## Limitations connues / à améliorer ensuite

- Pas d'undo/redo pour l'instant.
- L'édition de texte fonctionne bloc par bloc (police approximative, pas
  d'édition caractère par caractère avec la police d'origine garantie).
- Texte libre et note ne sont pas encore déplaçables (juste supprimables) —
  seuls rectangle/ellipse/ligne/dessin/mesures le sont.
- L'échelle du plan n'est mémorisée que pour la session en cours (pas encore
  écrite dans le fichier PDF).
- Pas encore de : OCR, conversion PDF ↔ Word/Excel/Image, impression,
  recherche de texte plein document, sélection/copie de texte libre,
  compression avancée, comparaison de documents.
- Pas encore packagé en .exe autonome (nécessite Python + venv pour l'instant).

Dis-moi quelles fonctionnalités ajouter en priorité et je les intègre.

## Développement

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pdfsuite.main
```

Tests de fumée (rendu hors écran, sans interface visible) dans `.smoke/`.
