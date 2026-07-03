from __future__ import annotations

import pytest

from debrief_meet.core.modes import MachineEtats, Mode


@pytest.fixture
def machine(qapp):
    """MachineEtats fraîche (QObject — nécessite une QApplication)."""
    return MachineEtats()


class TestEtatInitial:
    def test_mode_initial_idle(self, machine):
        assert machine.mode == Mode.IDLE

    def test_non_actif_initialement(self, machine):
        assert not machine.est_actif


class TestToggleDictee:
    def test_toggle_demarre_dictee(self, machine):
        resultat = machine.toggle_dictee()
        assert resultat is True
        assert machine.mode == Mode.DICTEE

    def test_toggle_deux_fois_retourne_idle(self, machine):
        machine.toggle_dictee()
        machine.toggle_dictee()
        assert machine.mode == Mode.IDLE

    def test_actif_pendant_dictee(self, machine):
        machine.toggle_dictee()
        assert machine.est_actif


class TestToggleReunion:
    def test_toggle_demarre_reunion(self, machine):
        machine.toggle_reunion()
        assert machine.mode == Mode.REUNION

    def test_toggle_deux_fois_retourne_idle(self, machine):
        machine.toggle_reunion()
        machine.toggle_reunion()
        assert machine.mode == Mode.IDLE


class TestToggleJournal:
    def test_toggle_demarre_journal(self, machine):
        machine.toggle_journal()
        assert machine.mode == Mode.JOURNAL

    def test_toggle_deux_fois_retourne_idle(self, machine):
        machine.toggle_journal()
        machine.toggle_journal()
        assert machine.mode == Mode.IDLE


class TestExclusivite:
    def test_reunion_bloquee_si_dictee_active(self, machine):
        machine.toggle_dictee()
        resultat = machine.toggle_reunion()
        assert resultat is False
        assert machine.mode == Mode.DICTEE

    def test_dictee_bloquee_si_reunion_active(self, machine):
        machine.toggle_reunion()
        resultat = machine.toggle_dictee()
        assert resultat is False
        assert machine.mode == Mode.REUNION

    def test_journal_bloque_si_dictee_active(self, machine):
        machine.toggle_dictee()
        resultat = machine.toggle_journal()
        assert resultat is False
        assert machine.mode == Mode.DICTEE

    def test_dictee_possible_apres_arret_reunion(self, machine):
        machine.toggle_reunion()
        machine.toggle_reunion()   # arrêt
        resultat = machine.toggle_dictee()
        assert resultat is True
        assert machine.mode == Mode.DICTEE


class TestSignaux:
    def test_signal_mode_change_emis(self, machine, qtbot):
        with qtbot.waitSignal(machine.mode_change, timeout=1000) as blocker:
            machine.toggle_dictee()
        assert blocker.args[0] == Mode.DICTEE

    def test_signal_idle_emis_au_stop(self, machine, qtbot):
        machine.toggle_dictee()
        with qtbot.waitSignal(machine.mode_change, timeout=1000) as blocker:
            machine.toggle_dictee()
        assert blocker.args[0] == Mode.IDLE

    def test_signal_erreur_emis_si_mode_conflit(self, machine, qtbot):
        machine.toggle_dictee()
        with qtbot.waitSignal(machine.erreur, timeout=1000) as blocker:
            machine.toggle_reunion()
        assert "DICTEE" in blocker.args[0]
