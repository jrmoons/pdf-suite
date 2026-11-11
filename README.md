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

Double-cliquer sur `creer_raccourci.bat` : construit `dist\PDFSuite\PDFSuite.exe`
(PyInstaller, version dossier qui démarre vite) puis crée le raccourci « PDF Suite » sur le Bureau.
L'exe est aussi construit automatiquement par GitHub Actions à chaque push
(onglet Actions → artefact `PDFSuite-windows`).

## Interface

Ruban à onglets : **Accueil · Commentaires · Mesures · Pages · Protéger ·
Affichage** (l'onglet affiché est mémorisé). Un outil reste actif après usage
pour enchaîner les annotations / mesures ; **Échap** revient à « Sélectionner ».

**Enregistrer (Ctrl+S) = toujours « Enregistrer sous »** : le fichier ouvert
n'est jamais écrasé (nom proposé : `…_modifié.pdf`).

## Fonctionnalités

- **Ouvrir** : menu, ou **glisser-déposer** un ou plusieurs PDF sur la fenêtre.
- **Se déplacer** : **clic molette maintenu** + glisser, quel que soit l'outil.
- **Accélération matérielle** (carte graphique, onglet Affichage, activée par
  défaut — à décocher en cas de souci d'affichage).
- **Visionneuse** : multi-onglets, défilement continu, **zoom instantané**
  (Ctrl + molette sous le curseur, boutons, curseur et liste de zoom dans la
  barre d'état, Ctrl+0 / Ctrl+1 / Ctrl+2) même sur de gros plans A0/A1 —
  seule la zone visible est recalculée en haute définition, vignettes réorganisables, thème clair / sombre.
- **Commentaires** : surligner, souligner, barrer, texte libre, note, dessin,
  rectangle, ellipse, ligne, **flèche**, **nuage de révision**, **légende**
  (texte + trait vers le point visé, pointe déplaçable), **tampons de chantier**
  (APPROUVÉ, BON POUR EXÉCUTION, VU, À REVOIR, REFUSÉ ou texte personnalisé,
  avec la date du jour et le nom Windows), gomme, couleur.
  Les formes, flèches, nuages, légendes et tampons sont des objets vectoriels
  déplaçables (clic droit → Verrouiller / Supprimer).
- **Mesures (plans)** :
  - **Cote** (outil principal) : clic sur A, clic sur B (ou glisser de A à B,
    Maj = 0° / 45° / 90°), puis déplacer la souris pour **décaler la cote**
    et cliquer pour la poser — lignes de rappel, traits obliques, longueur
    écrite le long de la ligne. Une cote posée se **fait coulisser** à la
    souris (décalage), ses points A / B se déplacent par leurs poignées,
    clic droit → Changer de côté / Verrouiller / Supprimer ;
  - Périmètre, **Surface (m²)** ;
  - **Barre « Mesure »** sous le ruban (visible avec un outil de mesure ou
    l'onglet Mesures) : échelle « 1 cm sur le plan = 0,5 m en réel »,
    préréglages 1:50, 1:100…, unité des longueurs (mm / cm / m), précision,
    couleur, **Calibrer** (tracer une cote connue). Tout est **enregistré dans
    le PDF** ; tant que l'échelle n'est pas saisie, la barre la réclame ;
  - pendant le tracé, panneau en direct : distance, angle, ΔX, ΔY, échelle,
    précision ; **Maj** bloque à 0° / 45° / 90° ; pour un contour, recliquer
    sur le premier point (ou clic droit / Entrée) ferme la forme,
    Retour arrière enlève le dernier point ;
  - cotes lisibles à tous les zooms ; surfaces toujours en m² ;
  - **Règles** graduées en unités réelles + taille de page et position X / Y
    du curseur dans la barre d'état ;
  - **Grille** + **Aimanter** ;
  - **Exporter mesures** : CSV pour Excel (totaux inclus) ;
  - **Comparer** deux versions d'un plan : rouge = supprimé, vert = ajouté
    (les deux plans doivent avoir la même mise en page) ;
  - **Capture** : copie une zone (avec les cotes) dans le presse-papiers.
- **Affichage** : **loupe** qui suit la souris, **inverser les couleurs**
  (page sombre), **vue fractionnée** (deux vues du même document).
- **Pages** : insérer une page vierge, supprimer, pivoter, réordonner,
  insérer un PDF, extraire, diviser.
- **Édition de texte** bloc par bloc (garde position, taille, couleur et sens
  du texte d'origine, y compris les petits textes et textes verticaux des plans), **formulaires** AcroForm,
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
`set QT_QPA_PLATFORM=offscreen` puis `.venv\Scripts\python .smoke
un_smoke7.py`
(lancer `make_sample.py` d'abord pour les tests 1 à 6).
