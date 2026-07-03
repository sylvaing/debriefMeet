from __future__ import annotations

import pytest

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.core.raccourcis import appliquer_raccourcis
from tests.fakes.adapters import RaccourcisFake


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
    assert set(raccourcis_fake.enregistres) == {"Meta+Alt+Ctrl+D", "Meta+Alt+Ctrl+R", "Meta+Alt+Ctrl+J"}


def test_callbacks_bascule_bien_la_machine(machine, raccourcis_fake, tmp_path):
    cfg = _config(tmp_path)
    appliquer_raccourcis(raccourcis_fake, cfg, machine)

    raccourcis_fake.enregistres["Meta+Alt+Ctrl+D"]()
    assert machine.mode == Mode.DICTEE
    raccourcis_fake.enregistres["Meta+Alt+Ctrl+D"]()
    assert machine.mode == Mode.IDLE

    raccourcis_fake.enregistres["Meta+Alt+Ctrl+R"]()
    assert machine.mode == Mode.REUNION
    raccourcis_fake.enregistres["Meta+Alt+Ctrl+R"]()
    assert machine.mode == Mode.IDLE

    raccourcis_fake.enregistres["Meta+Alt+Ctrl+J"]()
    assert machine.mode == Mode.JOURNAL
    raccourcis_fake.enregistres["Meta+Alt+Ctrl+J"]()
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
    assert "Meta+Alt+Ctrl+J" not in raccourcis_fake.enregistres
    assert len(raccourcis_fake.enregistres) == 2


def test_combinaison_refusee_reportee_dans_les_echecs(machine, tmp_path):
    fake = RaccourcisFake(refuser={"Meta+Alt+Ctrl+R"})
    cfg = _config(tmp_path)
    echecs = appliquer_raccourcis(fake, cfg, machine)
    assert echecs == ["Meta+Alt+Ctrl+R"]
    assert set(fake.enregistres) == {"Meta+Alt+Ctrl+D", "Meta+Alt+Ctrl+J"}
