from __future__ import annotations

import sys

import pytest

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.core.raccourcis import appliquer_raccourcis
from tests.fakes.adapters import RaccourcisFake

# Défauts dépendants de l'OS (décision D3, docs/31 §3.1) : Ctrl+Alt+D/R/J sur
# Windows, Meta+Alt+Ctrl+D/R/J ailleurs — ces tests tournent aussi sur la VM
# Windows (build gate docs/32).
_D, _R, _J = (
    ("Ctrl+Alt+D", "Ctrl+Alt+R", "Ctrl+Alt+J") if sys.platform == "win32"
    else ("Meta+Alt+Ctrl+D", "Meta+Alt+Ctrl+R", "Meta+Alt+Ctrl+J")
)


@pytest.fixture
def machine(qapp):
    return MachineEtats()


def _config(tmp_path, **kv):
    from debrief_meet.core.config import Config
    cfg = Config(chemin=tmp_path / "config.json")
    for k, v in kv.items():
        cfg.set(k, v)
    return cfg


def test_enregistre_les_trois_combinaisons_par_defaut(machine, raccourcis_fake, tmp_path):
    cfg = _config(tmp_path)
    echecs = appliquer_raccourcis(raccourcis_fake, cfg, machine)
    assert echecs == []
    assert set(raccourcis_fake.enregistres) == {_D, _R, _J}


def test_callbacks_bascule_bien_la_machine(machine, raccourcis_fake, tmp_path):
    cfg = _config(tmp_path)
    appliquer_raccourcis(raccourcis_fake, cfg, machine)

    raccourcis_fake.enregistres[_D]()
    assert machine.mode == Mode.DICTEE
    raccourcis_fake.enregistres[_D]()
    assert machine.mode == Mode.IDLE

    raccourcis_fake.enregistres[_R]()
    assert machine.mode == Mode.REUNION
    raccourcis_fake.enregistres[_R]()
    assert machine.mode == Mode.IDLE

    raccourcis_fake.enregistres[_J]()
    assert machine.mode == Mode.JOURNAL
    raccourcis_fake.enregistres[_J]()
    assert machine.mode == Mode.IDLE


def test_reapplication_desactive_avant_de_reenregistrer(machine, raccourcis_fake, tmp_path):
    cfg = _config(tmp_path)
    appliquer_raccourcis(raccourcis_fake, cfg, machine)
    appliquer_raccourcis(raccourcis_fake, cfg, machine)
    assert raccourcis_fake.appels_desactiver_tous == 2
    assert len(raccourcis_fake.enregistres) == 3   # pas de doublon


def test_combinaison_vide_non_enregistree_sans_echec(machine, raccourcis_fake, tmp_path):
    cfg = _config(tmp_path, raccourci_journal="")
    echecs = appliquer_raccourcis(raccourcis_fake, cfg, machine)
    assert echecs == []
    assert _J not in raccourcis_fake.enregistres
    assert len(raccourcis_fake.enregistres) == 2


def test_combinaison_refusee_reportee_dans_les_echecs(machine, tmp_path):
    fake = RaccourcisFake(refuser={_R})
    cfg = _config(tmp_path)
    echecs = appliquer_raccourcis(fake, cfg, machine)
    assert echecs == [_R]
    assert set(fake.enregistres) == {_D, _J}
