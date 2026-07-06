from __future__ import annotations

import pytest

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.dictee_view import DicteeView


@pytest.fixture
def machine(qapp):
    return MachineEtats()


def _config(tmp_path):
    return Config(chemin=tmp_path / "config.json")


def test_bouton_bascule_declenche_toggle_dictee(qapp, machine, tmp_path):
    vue = DicteeView(_config(tmp_path), machine)
    vue._action_bar._bouton.click()
    assert machine.mode == Mode.DICTEE


def test_definir_etat_enregistrement_repercute_sur_la_barre(qapp, machine, tmp_path):
    vue = DicteeView(_config(tmp_path), machine)
    vue.definir_etat_enregistrement(Mode.DICTEE, 12)
    assert vue._action_bar._chrono.text() == "00:12"


def test_pas_de_recherche(qapp, machine, tmp_path):
    vue = DicteeView(_config(tmp_path), machine)
    assert vue._action_bar._recherche is None
