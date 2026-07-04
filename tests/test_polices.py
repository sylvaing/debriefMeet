from __future__ import annotations

from debrief_meet.ui.polices import SANS, charger_polices


def test_charger_polices_definit_la_police_par_defaut(qapp):
    charger_polices(qapp)
    assert qapp.font().family() == SANS


def test_charger_polices_tolere_les_fichiers_absents(qapp, caplog):
    # Les .ttf ne sont pas encore fournis dans le dépôt (cf. ui/assets/fonts/) —
    # ne doit pas lever, juste logger en debug et se rabattre sur une police système.
    charger_polices(qapp)
