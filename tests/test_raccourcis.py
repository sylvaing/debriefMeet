from __future__ import annotations

import sys

import pytest

from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.core.raccourcis import ACTIONS, appliquer_raccourcis, libelle_modificateurs
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


# ── Défauts (bouton « Réinitialiser », refonte design) ──────────────────────────

def test_defauts_actions_correspondent_aux_defauts_config(tmp_path):
    """`ACTIONS` (utilisé par « Réinitialiser les défauts ») doit rester aligné
    sur `Config._DEFAUTS` — sinon une réinitialisation sur Windows réintroduirait
    Meta (touche Windows, décision D3) au lieu de Ctrl+Alt+<lettre>."""
    from debrief_meet.core.config import Config
    cfg = Config(chemin=tmp_path / "config.json")
    for cle, defaut, _nom in ACTIONS:
        assert defaut == cfg.get(cle)


# ── Libellés de modificateurs par OS (docs/handoff §9) ──────────────────────────

def test_libelle_modificateurs_ne_code_jamais_en_dur_hors_plateforme(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert libelle_modificateurs(("Meta", "Ctrl", "Alt")) == "⌘/⌃/⌥"

    monkeypatch.setattr(sys, "platform", "win32")
    assert libelle_modificateurs(("Meta", "Ctrl", "Alt")) == "Win/Ctrl/Alt"


# ── Mode distant (docs/45) ───────────────────────────────────────────────────

def test_distant_n_enregistre_que_la_reunion(machine, raccourcis_fake, tmp_path, mode_distant):
    """Ne rien enregistrer pour Dictée/Journal garantit que l'OS ne délivrera jamais ces
    combinaisons — donc aucun basculement vers un mode sans orchestrateur à l'écoute."""
    cfg = _config(tmp_path)
    echecs = appliquer_raccourcis(raccourcis_fake, cfg, machine)
    assert set(raccourcis_fake.enregistres) == {_R}
    assert echecs == []


def test_distant_actions_filtrees(mode_distant):
    from debrief_meet.core.raccourcis import actions
    assert [cle for cle, _d, _n in actions()] == ["raccourci_reunion"]


def test_local_actions_non_filtrees(mode_local):
    from debrief_meet.core.raccourcis import actions
    assert actions() == ACTIONS
