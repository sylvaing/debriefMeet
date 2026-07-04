from __future__ import annotations

import pytest

from debrief_meet.core.modes import EtatVisuel
from debrief_meet.ui.etat_icone import icone_wavemark_pour_etat


@pytest.mark.parametrize("etat", list(EtatVisuel))
def test_icone_non_vide(qapp, etat):
    icone = icone_wavemark_pour_etat(etat)
    assert not icone.isNull()


def test_repos_est_template(qapp):
    assert icone_wavemark_pour_etat(EtatVisuel.REPOS).isMask() is True


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
