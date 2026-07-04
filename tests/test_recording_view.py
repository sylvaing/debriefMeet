from __future__ import annotations

import pytest

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.recording_view import RecordingView


@pytest.fixture
def machine(qapp):
    return MachineEtats()


def test_titre_selon_le_mode(qapp, machine):
    machine.toggle_reunion()
    vue = RecordingView(machine)
    assert vue._titre.text() == "Réunion en cours"


def test_chrono_suit_le_tick(qapp, machine, monkeypatch):
    machine.toggle_dictee()
    vue = RecordingView(machine)
    monkeypatch.setattr(machine, "elapsed_seconds", lambda: 65)
    vue._on_tick()
    assert vue._chrono.text() == "01:05"


def test_bouton_arreter_appelle_le_bon_toggle(qapp, machine):
    machine.toggle_journal()
    vue = RecordingView(machine)
    vue._sur_arreter()
    assert machine.mode == Mode.IDLE


def test_texte_live_modifiable(qapp, machine):
    machine.toggle_reunion()
    vue = RecordingView(machine)
    vue.definir_texte_live("bonjour tout le monde")
    assert vue._texte_live.text() == "bonjour tout le monde"


def test_titre_change_si_mode_change_pendant_l_affichage(qapp, machine):
    machine.toggle_dictee()
    vue = RecordingView(machine)
    machine.toggle_dictee()  # arrêt
    machine.toggle_journal()
    assert vue._titre.text() == "Journal en cours"
