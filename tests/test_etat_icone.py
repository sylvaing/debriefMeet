from __future__ import annotations

import sys

import pytest

from debrief_meet.core.modes import EtatVisuel
from debrief_meet.ui.etat_icone import icone_wavemark_pour_etat


@pytest.mark.parametrize("etat", list(EtatVisuel))
def test_icone_non_vide(qapp, etat):
    icone = icone_wavemark_pour_etat(etat)
    assert not icone.isNull()


def test_repos_est_template(qapp):
    """Le REPOS n'est un « template » (masque reteint par l'OS) que là où la barre
    est claire. `setIsMask` est un mécanisme macOS : sous Linux il est ignoré, donc
    l'icône doit porter sa couleur explicitement (cf. `test_repos_barre_sombre`)."""
    attendu_masque = not sys.platform.startswith("linux")
    assert icone_wavemark_pour_etat(EtatVisuel.REPOS).isMask() is attendu_masque


@pytest.mark.parametrize(
    "etat",
    [EtatVisuel.ENREGISTREMENT, EtatVisuel.TRANSCRIPTION, EtatVisuel.TERMINE, EtatVisuel.ERREUR],
)
def test_etats_actifs_ne_sont_pas_template(qapp, etat):
    assert icone_wavemark_pour_etat(etat).isMask() is False


def test_couleurs_distinctes_par_etat(qapp):
    rouge = icone_wavemark_pour_etat(EtatVisuel.ENREGISTREMENT).pixmap(22, 22).toImage()
    orange = icone_wavemark_pour_etat(EtatVisuel.TRANSCRIPTION).pixmap(22, 22).toImage()
    vert = icone_wavemark_pour_etat(EtatVisuel.TERMINE).pixmap(22, 22).toImage()
    assert rouge != orange
    assert orange != vert
    assert rouge != vert


# ── Barre système sombre (GNOME) — docs/49 ────────────────────────────────────

def test_repos_barre_sombre_est_un_contour_blanc(qapp):
    """Sur le bandeau noir de GNOME, le gris ardoise `TRAY_IDLE` était invisible.
    La règle ne dépend PAS du thème de l'application : sous Ubuntu le bandeau reste
    noir en thème clair. Le `masque` est explicitement False — la couleur est déjà
    la bonne, il n'y a rien à faire reteindre."""
    from debrief_meet.ui.etat_icone import repos_pour
    from debrief_meet.ui.theme import C

    assert repos_pour(barre_sombre=True) == (C.TRAY_IDLE_BARRE_SOMBRE, False, False)
    assert C.TRAY_IDLE_BARRE_SOMBRE == "#FFFFFF"
    # Barre claire : contour aussi, mais laissé en template pour que macOS le reteigne.
    assert repos_pour(barre_sombre=False) == (C.TRAY_IDLE, False, True)


def test_repos_reste_la_marque_pas_un_pave(qapp):
    """LE test qui aurait évité la livraison du 2026-08-18 : `wavemark_icon` peint les
    barres en BLANC sur le carré coloré, donc `filled=True` + couleur blanche donne un
    carré blanc uni — la marque disparaît. Mesuré : 18 % de pixels opaques pour le
    contour, 92 % pour un plein. Le seuil de 40 % sépare les deux sans ambiguïté."""
    from debrief_meet.ui.etat_icone import repos_pour
    from debrief_meet.ui.wavemark import wavemark_icon

    for barre_sombre in (False, True):
        couleur, rempli, masque = repos_pour(barre_sombre)
        assert rempli is False, "le REPOS doit rester un contour, quelle que soit la barre"
        image = wavemark_icon(22, couleur, filled=rempli, masque=masque).pixmap(22, 22).toImage()
        opaques = sum(1 for x in range(image.width()) for y in range(image.height())
                      if image.pixelColor(x, y).alpha() > 200)
        part = opaques / (image.width() * image.height())
        assert 0.05 < part < 0.40, (
            f"barre_sombre={barre_sombre} : {part:.0%} de pixels opaques — "
            "un contour tourne autour de 18 %, un carré plein autour de 92 %")


def test_icone_barre_sombre_visible_sur_fond_noir(qapp):
    """Vérification par les pixels : l'icône du REPOS sur barre sombre doit contenir
    des pixels clairs, sinon elle se confond avec le bandeau."""
    from debrief_meet.ui.etat_icone import repos_pour
    from debrief_meet.ui.wavemark import wavemark_icon

    couleur, rempli, masque = repos_pour(barre_sombre=True)
    image = wavemark_icon(22, couleur, filled=rempli, masque=masque).pixmap(22, 22).toImage()

    luminances = [
        max(image.pixelColor(x, y).red(), image.pixelColor(x, y).green(),
            image.pixelColor(x, y).blue())
        for x in range(image.width()) for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 200
    ]
    assert luminances, "icône entièrement transparente"
    assert min(luminances) > 200, f"pixels trop sombres pour un bandeau noir : {min(luminances)}"
