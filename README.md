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

### Exe autonome + raccourci sur le Bureau

Double-cliquer sur `creer_raccourci.bat` : construit `dist\PDFSuite.exe`
(PyInstaller) puis crée le raccourci « PDF Suite » sur le Bureau.
L'exe est aussi construit automatiquement par GitHub Actions à chaque push
(onglet Actions → artefact `PDFSuite-windows`).

## Interface

Ruban à onglets : **Accueil · Commentaires · Mesures · Pages · Protéger ·
Affichage** (l'onglet affiché est mémorisé). Un outil reste actif après usage
pour enchaîner les annotations / mesures ; **Échap** revient à « Sélectionner ».

**Enregistrer (Ctrl+S) = toujours « Enregistrer sous »** : le fichier ouvert
n'est jamais écrasé (nom proposé : `…_modifié.pdf`).

## Fonctionnalités

- **Visionneuse** : multi-onglets, défilement continu, zoom (Ctrl + molette
  centré sur le curseur), vignettes réorganisables, thème clair / sombre.
- **Commentaires** : surligner, souligner, barrer, texte libre, note, dessin,
  rectangle, ellipse, ligne, **flèche**, **nuage de révision**, **légende**
  (texte + trait vers le point visé, pointe déplaçable), **tampons de chantier**
  (APPROUVÉ, BON POUR EXÉCUTION, VU, À REVOIR, REFUSÉ ou texte personnalisé,
  avec la date du jour et le nom Windows), gomme, couleur.
  Les formes, flèches, nuages, légendes et tampons sont des objets vectoriels
  déplaçables (clic droit → Verrouiller / Supprimer).
- **Mesures (plans)** :
  - Longueur, Périmètre, **Surface (m²)** ;
  - **Échelle** : préréglages 1:20, 1:50, 1:100, 1:200… ou calibrage sur une
    ligne de longueur connue ; l'échelle est **enregistrée dans le PDF** et
    retrouvée à la réouverture ;
  - **Grille** (pas en mètres quand l'échelle est connue) + **Aimanter** ;
    coordonnées du curseur en bas à droite ;
  - **Exporter mesures** : toutes les mesures vers un CSV qui s'ouvre dans
    Excel (totaux inclus) ;
  - **Comparer** deux versions d'un plan : rouge = supprimé, vert = ajouté
    (les deux plans doivent avoir la même mise en page) ;
  - **Capture** : copie une zone (avec les cotes) dans le presse-papiers.
- **Affichage** : **loupe** qui suit la souris, **inverser les couleurs**
  (page sombre), **vue fractionnée** (deux vues du même document).
- **Pages** : insérer une page vierge, supprimer, pivoter, réordonner,
  insérer un PDF, extraire, diviser.
- **Édition de texte** bloc par bloc, **formulaires** AcroForm,
  **signature** dessinée.
- **Protéger** : mot de passe AES-256 ; ouverture de PDF protégés.

## Limitations connues / à venir

- Pas encore d'annuler / refaire (prochain lot).
- Texte libre et note : pas encore déplaçables.
- Comparaison : pas de recalage automatique (plans supposés superposables).
- Lots suivants prévus : indispensables (annuler/refaire, combiner, compresser,
  recherche, impression, filigrane, numérotation…), organisation des pages,
  OCR, conversion PDF → Word / Excel, signets, commentaires, etc.

## Développement

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pdfsuite.main
```

Tests de fumée (rendu hors écran, sans interface visible) dans `.smoke/` :
`set QT_QPA_PLATFORM=offscreen` puis `.venv\Scripts\python .smokeun_smoke7.py`
(lancer `make_sample.py` d'abord pour les tests 1 à 6).
