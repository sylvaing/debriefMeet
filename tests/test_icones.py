from __future__ import annotations

import pytest

from debrief_meet.ui.icones import icone_application, icone_phosphor

# Jeu Phosphor requis par la refonte design (docs/handoff, IMPLEMENTATION_SPEC.md §1).
NOMS_PHOSPHOR = (
    "microphone", "users-three", "notebook", "clock-counter-clockwise", "gear",
    "magnifying-glass", "copy", "users", "file-text", "folder", "microphone-slash",
    "trash", "caret-up-down", "caret-up", "caret-down", "check", "check-circle",
    "record-fill", "waveform", "stop", "plus", "minus", "brain", "folders",
    "chat-text", "sliders-horizontal", "keyboard", "bug", "arrow-square-out",
    "sign-out", "cursor-click", "list", "warning-circle",
)


@pytest.mark.parametrize("nom", NOMS_PHOSPHOR)
def test_icone_phosphor_existe(nom):
    assert icone_phosphor(nom).exists(), f"SVG Phosphor manquant : {nom}"


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
