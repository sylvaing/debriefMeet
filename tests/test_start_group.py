from __future__ import annotations

import pytest

from debrief_meet.core.modes import Mode
from debrief_meet.ui.start_group import StartButtonGroup, formater_chrono


@pytest.mark.parametrize(
    "secondes, attendu",
    [(0, "00:00"), (42, "00:42"), (125, "02:05"), (3661, "61:01")],
)
def test_formater_chrono(secondes, attendu):
    assert formater_chrono(secondes) == attendu


def test_etat_repos_tous_actifs(qapp):
    groupe = StartButtonGroup()
    groupe.definir_etat(Mode.IDLE)
    for bouton in groupe._boutons.values():
        assert bouton.isEnabled()
        assert bouton._chrono.isHidden()


def test_etat_actif_grise_les_autres(qapp):
    groupe = StartButtonGroup()
    groupe.definir_etat(Mode.REUNION, secondes=90)

    actif = groupe._boutons[Mode.REUNION]
    assert actif.isEnabled()
    assert not actif._chrono.isHidden()
    assert actif._chrono.text() == "01:30"

    for mode, bouton in groupe._boutons.items():
        if mode is not Mode.REUNION:
            assert not bouton.isEnabled()


def test_clic_emet_demarrer_demande(qapp, qtbot):
    groupe = StartButtonGroup()
    with qtbot.waitSignal(groupe.demarrer_demande, timeout=1000) as bloqueur:
        groupe._boutons[Mode.DICTEE].clicked.emit()
    assert bloqueur.args == [Mode.DICTEE]
