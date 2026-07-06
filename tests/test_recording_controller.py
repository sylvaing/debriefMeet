from __future__ import annotations

import pytest

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.recording_controller import RecordingController


class FausseVue:
    def __init__(self):
        self.appels: list[tuple[Mode, int]] = []

    def definir_etat_enregistrement(self, mode_actif: Mode, secondes: int) -> None:
        self.appels.append((mode_actif, secondes))


@pytest.fixture
def machine(qapp):
    return MachineEtats()


@pytest.fixture
def vues():
    return {Mode.REUNION: FausseVue(), Mode.DICTEE: FausseVue(), Mode.JOURNAL: FausseVue()}


@pytest.fixture
def ctrl(machine, vues):
    """`RecordingController` avec arrêt garanti de son timer en fin de test —
    `qapp` est partagée entre tous les tests (session pytest-qt) : un timer
    répétitif laissé actif sur un contrôleur devenu non référencé peut tirer
    plus tard, dans un autre test, sur un objet déjà détruit (crash natif)."""
    controller = RecordingController(machine, vues[Mode.REUNION], vues[Mode.DICTEE], vues[Mode.JOURNAL])
    yield controller
    controller._timer.stop()


def test_construction_notifie_les_3_vues_en_idle(qapp, machine, vues, ctrl):
    for vue in vues.values():
        assert vue.appels == [(Mode.IDLE, 0)]


def test_demarrage_notifie_les_3_vues(qapp, machine, vues, ctrl):
    for vue in vues.values():
        vue.appels.clear()
    machine.toggle_reunion()
    for vue in vues.values():
        assert vue.appels[-1][0] == Mode.REUNION


def test_tick_met_a_jour_les_vues(qapp, machine, vues, ctrl, monkeypatch):
    machine.toggle_reunion()
    monkeypatch.setattr(machine, "elapsed_seconds", lambda: 42)
    ctrl._on_tick()  # simule le timeout du timer interne, sans attendre 1 s réelle
    for vue in vues.values():
        assert vue.appels[-1] == (Mode.REUNION, 42)


def test_tick_ignore_si_idle(qapp, machine, vues, ctrl):
    for vue in vues.values():
        vue.appels.clear()
    ctrl._on_tick()
    for vue in vues.values():
        assert vue.appels == []


def test_arret_du_mode_stoppe_le_timer(qapp, machine, ctrl):
    machine.toggle_reunion()
    assert ctrl._timer.isActive()
    machine.toggle_reunion()  # arrêt
    assert not ctrl._timer.isActive()
