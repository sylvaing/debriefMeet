from __future__ import annotations

import pytest

from debrief_meet.ui.wavemark import wavemark_icon


@pytest.mark.parametrize("filled", [True, False])
def test_icone_non_vide(qapp, filled):
    icone = wavemark_icon(26, "#3B5BDB", filled=filled)
    assert not icone.isNull()
    pixmap = icone.pixmap(26, 26)
    assert not pixmap.isNull()


def test_contour_est_template(qapp):
    assert wavemark_icon(24, "#3D4351", filled=False).isMask() is True


def test_plein_nest_pas_template(qapp):
    assert wavemark_icon(24, "#FF3B30", filled=True).isMask() is False


def test_taille_respectee(qapp):
    pixmap = wavemark_icon(40, "#FF3B30", filled=True).pixmap(40, 40)
    taille = pixmap.deviceIndependentSize()
    assert round(taille.width()) == 40
    assert round(taille.height()) == 40


def test_artwork_remplit_le_cadre(qapp):
    pixmap = wavemark_icon(100, "#FF3B30", filled=True).pixmap(100, 100)
    image = pixmap.toImage()
    hauteur = image.height()
    largeur = image.width()
    y_min, y_max = hauteur, 0
    for y in range(hauteur):
        for x in range(0, largeur, 3):
            if image.pixelColor(x, y).alpha() > 10:
                y_min = min(y_min, y)
                y_max = max(y_max, y)
                break
    couverture = (y_max - y_min) / hauteur
    assert couverture > 0.8, f"contenu trop petit dans le cadre ({couverture:.0%})"
