from __future__ import annotations

import pytest

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.recording_controller import RecordingController
from debrief_meet.ui.start_group import StartButtonGroup


@pytest.fixture
def machine(qapp):
    return MachineEtats()


@pytest.fixture
def groupe(qapp):
    return StartButtonGroup()


@pytest.fixture
def ctrl(machine, groupe):
    """`RecordingController` avec arrêt garanti de son timer en fin de test —
    `qapp` est partagée entre tous les tests (session pytest-qt) : un timer
    répétitif laissé actif sur un contrôleur devenu non référencé peut tirer
    plus tard, dans un autre test, sur un objet déjà détruit (crash natif)."""
    controller = RecordingController(machine, groupe)
    yield controller
    controller._timer.stop()


def test_clic_en_idle_demarre_et_demande_l_affichage(qapp, machine, groupe, ctrl):
    demandes = []
    ctrl.showRequested.connect(lambda: demandes.append(True))
    groupe.demarrer_demande.emit(Mode.REUNION)
    assert machine.mode == Mode.REUNION
    assert demandes == [True]


def test_reclic_sur_actif_ne_relance_pas_mais_redemande_l_affichage(qapp, machine, groupe, ctrl):
    demandes = []
    ctrl.showRequested.connect(lambda: demandes.append(True))
    groupe.demarrer_demande.emit(Mode.REUNION)
    groupe.demarrer_demande.emit(Mode.REUNION)
    assert machine.mode == Mode.REUNION  # pas repassé à IDLE
    assert demandes == [True, True]


def test_clic_sur_autre_type_actif_est_ignore(qapp, machine, groupe, ctrl):
    demandes = []
    ctrl.showRequested.connect(lambda: demandes.append(True))
    groupe.demarrer_demande.emit(Mode.REUNION)
    demandes.clear()
    groupe.demarrer_demande.emit(Mode.DICTEE)
    assert machine.mode == Mode.REUNION
    assert demandes == []


def test_mode_change_met_a_jour_le_start_group(qapp, machine, groupe, ctrl):
    machine.toggle_journal()
    assert groupe._boutons[Mode.JOURNAL].isEnabled()
    assert not groupe._boutons[Mode.DICTEE].isEnabled()


def test_tick_met_a_jour_le_chrono_du_bouton_actif(qapp, machine, groupe, ctrl, monkeypatch):
    machine.toggle_reunion()
    monkeypatch.setattr(machine, "elapsed_seconds", lambda: 42)
    ctrl._on_tick()  # simule le timeout du timer interne, sans attendre 1 s réelle
    assert groupe._boutons[Mode.REUNION]._chrono.text() == "00:42"


def test_arret_du_mode_stoppe_le_timer(qapp, machine, groupe, ctrl):
    machine.toggle_reunion()
    assert ctrl._timer.isActive()
    machine.toggle_reunion()  # arrêt
    assert not ctrl._timer.isActive()
