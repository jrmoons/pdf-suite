"""Générateur d'oiseaux animés : fenêtre Windows (PySide6).

On choisit les dimensions de l'image (en pixels), le nombre d'oiseaux et
jusqu'à trois couleurs (rouge, vert, bleu). Les oiseaux sont placés au hasard
et volent sans jamais se toucher ; deux oiseaux de même couleur gardent encore
plus de distance. La taille des oiseaux s'adapte automatiquement. Le résultat
s'exporte en GIF animé.
"""

import copy
import math
import os
import sys

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from simulation import ECART, ECART_MEME_COULEUR, Nuee  # noqa: E402

COULEURS = {
    "Rouge": QColor(220, 40, 40),
    "Vert": QColor(40, 170, 60),
    "Bleu": QColor(40, 90, 220),
}
FOND = QColor(225, 240, 255)

# L'oiseau est dessiné dans une boîte 1 × 0,6 centrée sur (0, 0). Sa
# demi-diagonale vaut ~0,583 : à l'échelle ci-dessous il tient dans le cercle
# de rayon r quelle que soit sa direction de vol.
ECHELLE_DESSIN = 1.7


def _chemin_corps():
    corps = QPainterPath()
    corps.addEllipse(QPointF(0.0, 0.02), 0.26, 0.11)
    tete = QPainterPath()
    tete.addEllipse(QPointF(0.27, -0.04), 0.11, 0.11)
    queue = QPainterPath()
    queue.moveTo(-0.20, -0.02)
    queue.lineTo(-0.49, -0.12)
    queue.lineTo(-0.42, 0.0)
    queue.lineTo(-0.49, 0.12)
    queue.lineTo(-0.20, 0.06)
    queue.closeSubpath()
    return corps.united(tete).united(queue)


CORPS = _chemin_corps()
BEC = QPainterPath()
BEC.moveTo(0.35, -0.08)
BEC.lineTo(0.49, -0.03)
BEC.lineTo(0.35, 0.0)
BEC.closeSubpath()


def _aile(phase):
    # Bout de l'aile qui monte et descend entre le haut et le bas de la boîte.
    bout_y = -0.28 * math.cos(phase)
    aile = QPainterPath()
    aile.moveTo(-0.10, 0.0)
    aile.quadTo(-0.12, bout_y * 0.6, -0.04, bout_y)
    aile.quadTo(0.08, bout_y * 0.5, 0.14, 0.0)
    aile.closeSubpath()
    return aile


def dessiner_oiseau(p: QPainter, o, r, couleur: QColor):
    p.save()
    p.translate(o.x, o.y)
    if o.vx < 0:  # vole vers la gauche : on retourne l'oiseau, tête en haut
        p.scale(-1, 1)
        p.rotate(math.degrees(math.atan2(o.vy, -o.vx)))
    else:
        p.rotate(math.degrees(math.atan2(o.vy, o.vx)))
    s = r * ECHELLE_DESSIN
    p.scale(s, s)

    p.setPen(QPen(couleur.darker(170), 0.02))
    p.setBrush(QBrush(couleur))
    p.drawPath(CORPS)
    p.setBrush(QBrush(couleur.darker(135)))
    p.drawPath(_aile(o.phase))
    p.setPen(QPen(QColor(160, 100, 0), 0.012))
    p.setBrush(QBrush(QColor(255, 170, 0)))
    p.drawPath(BEC)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawEllipse(QPointF(0.29, -0.07), 0.035, 0.035)
    p.setBrush(Qt.black)
    p.drawEllipse(QPointF(0.30, -0.07), 0.018, 0.018)
    p.restore()


def dessiner_scene(p: QPainter, nuee: Nuee, couleurs):
    p.setRenderHint(QPainter.Antialiasing)
    p.fillRect(QRectF(0, 0, nuee.largeur, nuee.hauteur), FOND)
    for o in nuee.oiseaux:
        dessiner_oiseau(p, o, nuee.r, couleurs[o.couleur])


def image_pil(nuee: Nuee, couleurs):
    img = QImage(nuee.largeur, nuee.hauteur, QImage.Format_RGB32)
    p = QPainter(img)
    dessiner_scene(p, nuee, couleurs)
    p.end()
    donnees = bytes(img.constBits())
    return Image.frombuffer(
        "RGB", (img.width(), img.height()), donnees, "raw", "BGRX", img.bytesPerLine(), 1
    )


class Apercu(QWidget):
    """Affiche la nuée à l'échelle de la fenêtre, en gardant les proportions."""

    def __init__(self):
        super().__init__()
        self.nuee, self.couleurs = None, []
        self.setMinimumSize(300, 200)

    def definir(self, nuee, couleurs):
        self.nuee, self.couleurs = nuee, couleurs
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(60, 60, 60))
        if self.nuee is None:
            return
        n = self.nuee
        echelle = min(self.width() / n.largeur, self.height() / n.hauteur)
        p.translate(
            (self.width() - n.largeur * echelle) / 2,
            (self.height() - n.hauteur * echelle) / 2,
        )
        p.scale(echelle, echelle)
        p.setClipRect(QRectF(0, 0, n.largeur, n.hauteur))
        dessiner_scene(p, n, self.couleurs)


class Fenetre(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Générateur d'oiseaux animés")
        self.resize(1150, 720)

        self.sp_largeur = self._spin(100, 4000, 800, " px")
        self.sp_hauteur = self._spin(100, 4000, 600, " px")
        self.sp_nombre = self._spin(1, 2000, 20, "")
        self.sp_vitesse = self._spin(0, 1000, 80, " px/s", regenerer=False)
        self.sp_vitesse.valueChanged.connect(self._vitesse_changee)
        self.sp_duree = self._spin(1, 60, 5, " s", regenerer=False)
        self.sp_ips = self._spin(5, 50, 20, " images/s", regenerer=False)

        dims = QGroupBox("Dimensions de l'image")
        f = QFormLayout(dims)
        f.addRow("Largeur :", self.sp_largeur)
        f.addRow("Hauteur :", self.sp_hauteur)

        nb = QGroupBox("Oiseaux")
        f = QFormLayout(nb)
        f.addRow("Nombre :", self.sp_nombre)
        f.addRow("Vitesse :", self.sp_vitesse)

        coul = QGroupBox("Couleurs")
        v = QVBoxLayout(coul)
        self.cases_couleurs = {}
        for nom in COULEURS:
            cb = QCheckBox(nom)
            cb.setChecked(True)
            cb.toggled.connect(self._couleur_changee)
            v.addWidget(cb)
            self.cases_couleurs[nom] = cb

        gif = QGroupBox("GIF animé")
        f = QFormLayout(gif)
        f.addRow("Durée :", self.sp_duree)
        f.addRow("Fluidité :", self.sp_ips)

        bt_gen = QPushButton("Nouvelle disposition")
        bt_gen.clicked.connect(self.generer)
        self.bt_pause = QPushButton("Pause")
        self.bt_pause.clicked.connect(self._basculer_pause)
        bt_gif = QPushButton("Exporter en GIF…")
        bt_gif.clicked.connect(self.exporter_gif)

        self.info = QLabel()
        self.info.setWordWrap(True)

        panneau = QVBoxLayout()
        for w in (dims, nb, coul, gif, bt_gen, self.bt_pause, bt_gif, self.info):
            panneau.addWidget(w)
        panneau.addStretch()
        gauche = QWidget()
        gauche.setLayout(panneau)
        gauche.setFixedWidth(260)

        self.apercu = Apercu()
        central = QWidget()
        h = QHBoxLayout(central)
        h.addWidget(gauche)
        h.addWidget(self.apercu, 1)
        self.setCentralWidget(central)

        self.nuee = None
        self.minuterie = QTimer(self)
        self.minuterie.timeout.connect(self._tic)
        self.minuterie.start(40)
        self.generer()

    # -- réglages ---------------------------------------------------------

    def _spin(self, mini, maxi, val, suffixe, regenerer=True):
        s = QSpinBox()
        s.setRange(mini, maxi)
        s.setValue(val)
        s.setSuffix(suffixe)
        if regenerer:
            s.editingFinished.connect(self._si_change)
        return s

    def _parametres(self):
        return (
            self.sp_largeur.value(),
            self.sp_hauteur.value(),
            self.sp_nombre.value(),
            tuple(n for n, cb in self.cases_couleurs.items() if cb.isChecked()),
        )

    def _si_change(self):
        # editingFinished arrive aussi quand on quitte le champ sans rien changer.
        if self._parametres() != getattr(self, "_derniers", None):
            self.generer()

    def _couleur_changee(self):
        if not any(cb.isChecked() for cb in self.cases_couleurs.values()):
            self.sender().setChecked(True)  # au moins une couleur
            return
        self.generer()

    def _vitesse_changee(self, v):
        if self.nuee is not None:
            facteur = v / self.nuee.vitesse if self.nuee.vitesse else 0
            self.nuee.vitesse = v
            for o in self.nuee.oiseaux:
                if facteur:
                    o.vx, o.vy = o.vx * facteur, o.vy * facteur
                else:  # on repart d'une vitesse nulle : direction au hasard
                    a = self.nuee.rnd.uniform(0, 2 * math.pi)
                    o.vx, o.vy = math.cos(a) * v, math.sin(a) * v

    def couleurs_choisies(self):
        return [COULEURS[n] for n in self._parametres()[3]]

    # -- génération et animation -----------------------------------------

    def generer(self):
        self._derniers = self._parametres()
        largeur, hauteur, n, noms = self._derniers
        try:
            self.nuee = Nuee(n, largeur, hauteur, len(noms), self.sp_vitesse.value())
        except ValueError as e:
            self.nuee = None
            self.info.setText(f"<span style='color:#c00'>{e}</span>")
        else:
            r = self.nuee.r
            self.info.setText(
                f"{n} oiseau{'x' if n > 1 else ''} d'environ {2 * r:.0f} px.<br>"
                f"Écart minimal : {r * ECART:.0f} px entre deux oiseaux, "
                f"{r * ECART_MEME_COULEUR:.0f} px entre deux oiseaux de même couleur."
            )
        self.apercu.definir(self.nuee, self.couleurs_choisies())

    def _tic(self):
        if self.nuee is not None:
            self.nuee.avancer(self.minuterie.interval() / 1000)
            self.apercu.update()

    def _basculer_pause(self):
        if self.minuterie.isActive():
            self.minuterie.stop()
            self.bt_pause.setText("Lecture")
        else:
            self.minuterie.start()
            self.bt_pause.setText("Pause")

    # -- export -----------------------------------------------------------

    def exporter_gif(self):
        if self.nuee is None:
            QMessageBox.warning(self, "Rien à exporter", "Les réglages actuels ne permettent pas de placer les oiseaux.")
            return
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter le GIF", "oiseaux.gif", "GIF animé (*.gif)")
        if not chemin:
            return
        if not chemin.lower().endswith(".gif"):
            chemin += ".gif"

        ips = self.sp_ips.value()
        nb_images = self.sp_duree.value() * ips
        nuee = copy.deepcopy(self.nuee)  # l'aperçu continue de son côté
        couleurs = self.couleurs_choisies()

        progression = QProgressDialog("Création du GIF…", "Annuler", 0, nb_images, self)
        progression.setWindowModality(Qt.WindowModal)
        progression.setMinimumDuration(0)
        images = []
        for i in range(nb_images):
            progression.setValue(i)
            QApplication.processEvents()
            if progression.wasCanceled():
                return
            images.append(image_pil(nuee, couleurs).quantize(colors=64))
            nuee.avancer(1 / ips)
        progression.setLabelText("Enregistrement…")
        QApplication.processEvents()
        images[0].save(
            chemin,
            save_all=True,
            append_images=images[1:],
            duration=round(1000 / ips),
            loop=0,
        )
        progression.setValue(nb_images)
        QMessageBox.information(self, "GIF enregistré", f"{nb_images} images enregistrées dans :\n{chemin}")


def main():
    app = QApplication(sys.argv)
    fen = Fenetre()
    fen.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
