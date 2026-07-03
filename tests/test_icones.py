from __future__ import annotations

import pytest

from debrief_meet.core.modes import EtatVisuel
from debrief_meet.ui.icones import (
    _GLYPHES,
    icone_application,
    icone_glyphe,
    icone_pour_etat,
    pixmap_glyphe,
)


@pytest.mark.parametrize("etat", list(EtatVisuel))
def test_icone_non_vide(qapp, etat):
    icone = icone_pour_etat(etat)
    assert not icone.isNull()
    pixmap = icone.pixmap(22, 22)
    assert not pixmap.isNull()
    assert pixmap.width() > 0


def test_repos_est_template(qapp):
    """Au repos, l'icône doit être un masque (template) pour s'adapter à la barre."""
    icone = icone_pour_etat(EtatVisuel.REPOS)
    assert icone.isMask() is True


@pytest.mark.parametrize(
    "etat",
    [
        EtatVisuel.ENREGISTREMENT,
        EtatVisuel.TRANSCRIPTION,
        EtatVisuel.TERMINE,
        EtatVisuel.ERREUR,
    ],
)
def test_etats_actifs_ne_sont_pas_template(qapp, etat):
    """Les états colorés ne sont pas des masques (la couleur doit être conservée)."""
    icone = icone_pour_etat(etat)
    assert icone.isMask() is False


def test_taille_respectee(qapp):
    icone = icone_pour_etat(EtatVisuel.ENREGISTREMENT, taille=44)
    pixmap = icone.pixmap(44, 44)
    # En Retina, le pixmap physique vaut 44 × devicePixelRatio ; on vérifie la
    # taille logique (indépendante de l'écran).
    taille_logique = pixmap.deviceIndependentSize()
    assert round(taille_logique.width()) == 44
    assert round(taille_logique.height()) == 44


def test_artwork_remplit_le_cadre(qapp):
    """L'icône ne doit pas avoir de grande marge transparente : le contenu peint
    doit couvrir une large part de la hauteur (sinon elle paraît minuscule)."""
    pixmap = icone_pour_etat(EtatVisuel.ENREGISTREMENT, taille=100).pixmap(100, 100)
    image = pixmap.toImage()
    largeur = image.width()
    hauteur = image.height()
    # bornes verticales des pixels non transparents
    y_min, y_max = hauteur, 0
    for y in range(hauteur):
        for x in range(0, largeur, 3):  # échantillonnage
            if image.pixelColor(x, y).alpha() > 10:
                y_min = min(y_min, y)
                y_max = max(y_max, y)
                break
    couverture = (y_max - y_min) / hauteur
    assert couverture > 0.8, f"contenu trop petit dans le cadre ({couverture:.0%})"


def test_icone_application_pleine_et_coloree(qapp):
    """L'icône d'app (Dock) est non vide, colorée (pas un template) et remplit le cadre."""
    icone = icone_application(taille=128)
    assert not icone.isNull()
    assert icone.isMask() is False
    pixmap = icone.pixmap(128, 128)
    assert not pixmap.isNull()
    image = pixmap.toImage()
    hauteur = image.height()
    y_min, y_max = hauteur, 0
    for y in range(hauteur):
        for x in range(0, image.width(), 3):
            if image.pixelColor(x, y).alpha() > 10:
                y_min = min(y_min, y)
                y_max = max(y_max, y)
                break
    assert (y_max - y_min) / hauteur > 0.8


@pytest.mark.parametrize("nom", sorted(_GLYPHES))
def test_glyphe_non_vide(qapp, nom):
    """Chaque glyphe d'action rend un pixmap non vide (peint dans la couleur du thème)."""
    icone = icone_glyphe(nom)
    assert not icone.isNull()
    pix = icone.pixmap(18, 18)
    assert not pix.isNull() and pix.width() > 0


def test_glyphe_intensite_attenue_lopacite(qapp):
    """Une intensité plus faible doit réduire l'opacité moyenne de l'encre."""
    def opacite_moyenne(intensite):
        img = icone_glyphe("corbeille", 24, intensite=intensite).pixmap(24, 24).toImage()
        vals = [img.pixelColor(x, y).alpha()
                for y in range(img.height()) for x in range(img.width())
                if img.pixelColor(x, y).alpha() > 0]
        return sum(vals) / len(vals) if vals else 0
    assert opacite_moyenne(0.5) < opacite_moyenne(1.0)


def test_glyphe_inconnu_leve(qapp):
    with pytest.raises(ValueError):
        icone_glyphe("inexistant")


def test_glyphes_sont_distincts(qapp):
    """Deux glyphes différents ne doivent pas produire le même rendu."""
    a = icone_glyphe("micro").pixmap(40, 40).toImage()
    b = icone_glyphe("corbeille").pixmap(40, 40).toImage()
    c = icone_glyphe("copier").pixmap(40, 40).toImage()
    assert a != b and a != c and b != c


def test_pixmap_glyphe_indicateur(qapp):
    pix = pixmap_glyphe("micro", taille=16)
    assert not pix.isNull()
    assert round(pix.deviceIndependentSize().width()) == 16


def test_couleurs_distinctes_par_etat(qapp):
    """Enregistrement, transcription et terminé doivent produire des pixmaps différents."""
    rouge = icone_pour_etat(EtatVisuel.ENREGISTREMENT).pixmap(22, 22).toImage()
    orange = icone_pour_etat(EtatVisuel.TRANSCRIPTION).pixmap(22, 22).toImage()
    vert = icone_pour_etat(EtatVisuel.TERMINE).pixmap(22, 22).toImage()
    assert rouge != orange
    assert orange != vert
    assert rouge != vert


# ── Glyphe pivoté (spinner animé, doc 11) ────────────────────────────────────

@pytest.mark.parametrize("angle", [0, 30, 90, 180, 330])
def test_icone_glyphe_pivotee_non_vide(qapp, angle):
    from debrief_meet.ui.icones import icone_glyphe_pivotee
    icone = icone_glyphe_pivotee("attente", 20, angle)
    assert not icone.isNull()
    pixmap = icone.pixmap(20, 20)
    assert not pixmap.isNull()
    assert pixmap.width() > 0


def test_icone_glyphe_pivotee_glyphe_inconnu_leve(qapp):
    from debrief_meet.ui.icones import icone_glyphe_pivotee
    with pytest.raises(ValueError):
        icone_glyphe_pivotee("glyphe_qui_nexiste_pas", 20, 45)


# ── Icône d'application (.icns, Dock/Finder) ─────────────────────────────────

@pytest.mark.parametrize("taille", [32, 128, 512, 1024])
def test_dessiner_icone_app_taille_et_non_vide(qapp, taille):
    from debrief_meet.ui.icones import dessiner_icone_app
    pix = dessiner_icone_app(taille)
    assert not pix.isNull()
    assert pix.width() == taille and pix.height() == taille


def test_dessiner_icone_app_couleurs(qapp):
    from debrief_meet.ui.icones import dessiner_icone_app
    img = dessiner_icone_app(186).toImage()      # repère logique 1:1
    # centre = barre d'onde blanche
    centre = img.pixelColor(93, 93)
    assert centre.red() > 200 and centre.green() > 200 and centre.blue() > 200
    # fond du carré, à gauche des ondes = bleu plein (plus de carré blanc)
    fond = img.pixelColor(30, 93)
    assert fond.blue() > 150 and fond.blue() > fond.red()
    coin = img.pixelColor(30, 30)
    assert coin.blue() > 150 and coin.blue() > coin.red()


def test_ecrire_iconset_produit_les_png(qapp, tmp_path):
    from debrief_meet.ui.icones import ecrire_iconset
    fichiers = ecrire_iconset(tmp_path)
    assert len(fichiers) == 10
    for f in fichiers:
        assert f.exists() and f.suffix == ".png" and f.stat().st_size > 0
    # quelques tailles attendues présentes
    noms = {f.name for f in fichiers}
    assert "icon_16x16.png" in noms
    assert "icon_512x512@2x.png" in noms


def test_forme_bulle_est_un_carre_sans_queue(qapp):
    """La silhouette du tray est un carré arrondi (pas de queue qui l'allonge)."""
    from debrief_meet.ui.icones import _chemin_bulle
    r = _chemin_bulle().boundingRect()
    assert abs(r.width() - r.height()) < 1          # carré
    assert abs(r.x() - 6) < 1 and abs(r.y() - 6) < 1
    assert abs(r.height() - 88) < 1                 # pas d'allongement par une queue
