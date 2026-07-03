from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes.adapters import (
    DemarrageAutoFake,
    MicroFake,
    MoteurFake,
    PressePapiersFake,
    RaccourcisFake,
    SystemeFake,
)


@pytest.fixture(autouse=True)
def _arret_propre_orchestrateurs(monkeypatch):
    """Joint les QThread des orchestrateurs avant le GC de fin de test.

    Problème : un orchestrateur créé en variable locale d'un test est
    garbage-collecté dès que la fonction retourne. S'il a un QThread de
    transcription encore en cours (thread.quit() est asynchrone), Qt détruit
    ce thread enfant pendant qu'il tourne → « QThread: Destroyed while thread
    is still running » → abort de l'interpréteur (flakiness ~50 %).

    Correctif : on patche le __init__ des trois orchestrateurs pour les
    enregistrer à leur création. La liste les maintient en vie jusqu'au
    teardown, où terminer() joint proprement chaque thread. En production ce
    rôle est tenu par aboutToQuit → terminer().
    """
    try:
        from debrief_meet.core.dictee import OrchestrateurDictee
        from debrief_meet.core.journal import OrchestrateurJournal
        from debrief_meet.core.reunion import OrchestrateurReunion
    except ImportError:
        yield
        return

    instances: list = []

    def _enregistreur(cls):
        original = cls.__init__

        def _init(self, *args, **kwargs):
            original(self, *args, **kwargs)
            instances.append(self)

        return _init

    for cls in (OrchestrateurDictee, OrchestrateurReunion, OrchestrateurJournal):
        monkeypatch.setattr(cls, "__init__", _enregistreur(cls))

    yield

    for orch in instances:
        try:
            orch.terminer()
        except Exception:
            pass


@pytest.fixture
def moteur_fake():
    return MoteurFake()


@pytest.fixture
def micro_fake():
    return MicroFake()


@pytest.fixture
def systeme_fake():
    return SystemeFake()


@pytest.fixture
def presse_papiers_fake():
    return PressePapiersFake()


@pytest.fixture
def demarrage_auto_fake():
    return DemarrageAutoFake()


@pytest.fixture
def raccourcis_fake():
    return RaccourcisFake()


@pytest.fixture
def config_tmp(tmp_path):
    """Config pointant vers un répertoire temporaire."""
    from debrief_meet.core.config import Config
    chemin = tmp_path / "config.json"
    cfg = Config(chemin=chemin)
    return cfg


@pytest.fixture
def config_tmp_avec_fichier(tmp_path):
    """Config avec un fichier JSON pré-existant."""
    def _creer(donnees: dict) -> "Config":
        from debrief_meet.core.config import Config
        chemin = tmp_path / "config.json"
        chemin.write_text(json.dumps(donnees), encoding="utf-8")
        cfg = Config(chemin=chemin)
        cfg.charger()
        return cfg
    return _creer
