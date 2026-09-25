"""Nuée d'oiseaux qui volent sans jamais se toucher.

Chaque oiseau est contenu dans un cercle de rayon ``r``. Deux oiseaux restent
toujours séparés d'au moins ``ecart`` pixels, et deux oiseaux de même couleur
d'au moins ``ecart_meme_couleur``. Chaque déplacement est vérifié avant
d'être appliqué : s'il violait une distance, l'oiseau rebondit et reste où il
était. La règle est donc respectée à chaque image, pas seulement en moyenne.
"""

import math
import random
from collections import defaultdict
from dataclasses import dataclass

DENSITE = 0.28  # part de l'image occupée par les zones réservées aux oiseaux
RAYON_MAX_RATIO = 1 / 6  # un oiseau seul ne dépasse pas 1/6 du petit côté
RAYON_MIN = 4  # en pixels : en dessous, un oiseau n'est plus lisible
ECART = 0.4  # espace vide minimal entre deux oiseaux, en rayons
ECART_MEME_COULEUR = 1.4  # espace minimal entre deux oiseaux de même couleur


@dataclass
class Oiseau:
    x: float
    y: float
    vx: float
    vy: float
    couleur: int  # indice dans la liste des couleurs choisies
    phase: float  # battement d'ailes


class Nuee:
    def __init__(self, n, largeur, hauteur, nb_couleurs, vitesse, graine=None):
        self.largeur, self.hauteur = largeur, hauteur
        self.nb_couleurs = nb_couleurs
        self.vitesse = vitesse
        self.rnd = random.Random(graine)

        r = self._rayon_ideal(n)
        if r < RAYON_MIN:
            raise ValueError(self._message_trop(n))
        # Placement au hasard ; si ça coince, on réduit un peu la taille.
        while True:
            self._fixer_rayon(r)
            oiseaux = self._placer(n)
            if oiseaux is not None:
                break
            r *= 0.93
            if r < RAYON_MIN:
                raise ValueError(self._message_trop(n))
        self.oiseaux = oiseaux

    # -- géométrie -------------------------------------------------------

    def _rayon_ideal(self, n):
        """Plus grand rayon qui laisse assez de place pour placer tout le monde."""
        aire = DENSITE * self.largeur * self.hauteur
        # Tous les oiseaux entre eux...
        d = 2 + ECART
        r_tous = math.sqrt(aire / (n * math.pi * (d / 2) ** 2))
        # ...et ceux d'une même couleur, plus espacés.
        par_couleur = math.ceil(n / self.nb_couleurs)
        d = 2 + ECART_MEME_COULEUR
        r_couleur = math.sqrt(aire / (par_couleur * math.pi * (d / 2) ** 2))
        return min(r_tous, r_couleur, min(self.largeur, self.hauteur) * RAYON_MAX_RATIO)

    def _fixer_rayon(self, r):
        self.r = r
        self.d_autre = r * (2 + ECART)
        self.d_meme = r * (2 + ECART_MEME_COULEUR)
        # Pas de déplacement maximal par sous-étape : bien plus petit que l'écart.
        self.pas_max = r * ECART / 4
        self.taille_case = self.d_meme + 2 * self.pas_max

    def _message_trop(self, n):
        return (
            f"Trop d'oiseaux ({n}) pour une image {self.largeur}×{self.hauteur} : "
            "ils seraient trop petits. Agrandis l'image, réduis le nombre "
            "d'oiseaux ou ajoute des couleurs."
        )

    def distance_min(self, a, b):
        return self.d_meme if a.couleur == b.couleur else self.d_autre

    def _dans_cadre(self, x, y):
        r = self.r
        return r <= x <= self.largeur - r and r <= y <= self.hauteur - r

    # -- placement initial ----------------------------------------------

    def _placer(self, n):
        # Couleurs réparties équitablement, dans un ordre aléatoire.
        couleurs = [i % self.nb_couleurs for i in range(n)]
        self.rnd.shuffle(couleurs)
        places = []
        grille = defaultdict(list)
        for c in couleurs:
            for _ in range(3000):
                x = self.rnd.uniform(self.r, self.largeur - self.r)
                y = self.rnd.uniform(self.r, self.hauteur - self.r)
                angle = self.rnd.uniform(0, 2 * math.pi)
                o = Oiseau(
                    x, y,
                    math.cos(angle) * self.vitesse, math.sin(angle) * self.vitesse,
                    c, self.rnd.uniform(0, 2 * math.pi),
                )
                if all(
                    math.hypot(x - v.x, y - v.y) >= self.distance_min(o, v)
                    for v in self._voisins(grille, x, y)
                ):
                    places.append(o)
                    grille[self._case(x, y)].append(o)
                    break
            else:
                return None
        return places

    # -- animation -------------------------------------------------------

    def _case(self, x, y):
        return int(x // self.taille_case), int(y // self.taille_case)

    def _voisins(self, grille, x, y):
        cx, cy = self._case(x, y)
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                yield from grille.get((i, j), ())

    def avancer(self, dt):
        """Fait avancer la nuée de dt secondes."""
        distance = self.vitesse * dt
        nb = max(1, math.ceil(distance / self.pas_max)) if distance > 0 else 1
        for _ in range(nb):
            self._sous_etape(dt / nb)

    def _sous_etape(self, dt):
        rnd = self.rnd
        grille = defaultdict(list)
        for o in self.oiseaux:
            grille[self._case(o.x, o.y)].append(o)

        for o in self.oiseaux:
            o.phase = (o.phase + dt * 12) % (2 * math.pi)
            # Petite dérive de cap pour un vol plus naturel.
            a = math.atan2(o.vy, o.vx) + rnd.gauss(0, 1.2) * math.sqrt(dt)
            o.vx, o.vy = math.cos(a) * self.vitesse, math.sin(a) * self.vitesse

            nx, ny = o.x + o.vx * dt, o.y + o.vy * dt
            # Bords de l'image
            if not self.r <= nx <= self.largeur - self.r:
                o.vx = -o.vx
                nx = o.x
            if not self.r <= ny <= self.hauteur - self.r:
                o.vy = -o.vy
                ny = o.y
            # Autres oiseaux : on vérifie la position visée avant d'y aller.
            bloque = False
            for v in self._voisins(grille, nx, ny):
                if v is o:
                    continue
                dx, dy = nx - v.x, ny - v.y
                dist = math.hypot(dx, dy)
                if dist < self.distance_min(o, v):
                    bloque = True
                    # Rebond : on renvoie la vitesse dans l'autre sens le long
                    # de la ligne qui joint les deux oiseaux.
                    ux, uy = (o.x - v.x), (o.y - v.y)
                    norme = math.hypot(ux, uy) or 1.0
                    ux, uy = ux / norme, uy / norme
                    proj = o.vx * ux + o.vy * uy
                    if proj < 0:
                        o.vx -= 2 * proj * ux
                        o.vy -= 2 * proj * uy
            if not bloque:
                ancienne = self._case(o.x, o.y)
                o.x, o.y = nx, ny
                nouvelle = self._case(nx, ny)
                if nouvelle != ancienne:
                    grille[ancienne].remove(o)
                    grille[nouvelle].append(o)

    # -- contrôle ---------------------------------------------------------

    def plus_petits_ecarts(self):
        """(écart minimal entre deux oiseaux, écart minimal entre même couleur),
        mesurés entre les bords des cercles des oiseaux."""
        tous = meme = math.inf
        ois = self.oiseaux
        for i in range(len(ois)):
            for j in range(i + 1, len(ois)):
                e = math.hypot(ois[i].x - ois[j].x, ois[i].y - ois[j].y) - 2 * self.r
                tous = min(tous, e)
                if ois[i].couleur == ois[j].couleur:
                    meme = min(meme, e)
        return tous, meme
