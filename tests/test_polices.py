from __future__ import annotations

import pytest
from PySide6.QtGui import QFontDatabase

from debrief_meet.ui.polices import _FICHIERS, FONT_DIR, MONO, SANS, charger_polices


def test_charger_polices_definit_la_police_par_defaut(qapp):
    charger_polices(qapp)
    assert qapp.font().family() == SANS


def test_charger_polices_enregistre_sans_et_mono(qapp):
    charger_polices(qapp)
    familles = QFontDatabase.families()
    assert SANS in familles
    assert MONO in familles


@pytest.mark.parametrize("nom", _FICHIERS)
def test_fichier_police_present(nom):
    assert (FONT_DIR / nom).exists(), f"Police IBM Plex manquante : {nom}"


def test_charger_polices_tolere_les_fichiers_absents(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("debrief_meet.ui.polices.FONT_DIR", tmp_path)
    charger_polices(qapp)  # ne doit pas lever, juste se rabattre sur une police système
