"""Tests de JournalView (refonte design v2) — porte la couverture
comportementale journal de l'ancienne `HistoryView` (v1, disparue).
"""
from __future__ import annotations

import pytest

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.journal_view import JournalView


@pytest.fixture
def machine(qapp):
    return MachineEtats()


def _config(tmp_path):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path))
    cfg.set("dossier_journal", str(tmp_path))
    return cfg


def test_journal_a_quatre_actions(qapp, machine, tmp_path):
    (tmp_path / "2026-02-02.md").write_text("note", encoding="utf-8")
    vue = JournalView(_config(tmp_path), machine)
    index = vue._proxy.mapFromSource(vue._modele.index(0, 3))
    actions = vue._actions_pour_index(index)
    assert len(actions) == 4


def test_bouton_bascule_declenche_toggle_journal(qapp, machine, tmp_path):
    vue = JournalView(_config(tmp_path), machine)
    vue._action_bar._bouton.click()
    assert machine.mode == Mode.JOURNAL


def test_refresh_voit_nouvelle_note(qapp, machine, tmp_path):
    vue = JournalView(_config(tmp_path), machine)
    assert vue._modele.rowCount() == 0
    (tmp_path / "2026-02-02.md").write_text("note", encoding="utf-8")
    vue.recharger()
    assert vue._modele.rowCount() == 1
