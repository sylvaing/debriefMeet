"""Mode de transcription figé au démarrage + capacités (docs/45).

Le mode est un état module posé par `initialiser(config)` — les tests le
manipulent via `monkeypatch.setattr(mode_transcription, "_mode", ...)` (auto-
restauré), jamais par `importlib.reload` (dangereux avec Qt, docs/26).
"""
from __future__ import annotations

import logging

from debrief_meet.core import mode_transcription


class _ConfigStub:
    def __init__(self, mode):
        self._mode = mode

    def get(self, cle):
        assert cle == "mode_transcription"
        return self._mode


def _vierge(monkeypatch):
    """État d'avant `initialiser()` : mode non posé, env propre."""
    monkeypatch.setattr(mode_transcription, "_mode", None)
    monkeypatch.delenv(mode_transcription.VAR_ENV, raising=False)


# ── Résolution ───────────────────────────────────────────────────────────────

def test_non_initialise_est_distant(monkeypatch):
    """Défaut sûr : avant `initialiser()`, tout est masqué — jamais de moteur fantôme."""
    _vierge(monkeypatch)
    assert mode_transcription.mode() == mode_transcription.DISTANT
    assert not mode_transcription.avec_transcription_locale()


def test_initialiser_depuis_config_local(monkeypatch):
    _vierge(monkeypatch)
    mode_transcription.initialiser(_ConfigStub("local"))
    assert mode_transcription.mode() == mode_transcription.LOCAL


def test_initialiser_depuis_config_distant(monkeypatch):
    _vierge(monkeypatch)
    mode_transcription.initialiser(_ConfigStub("distant"))
    assert mode_transcription.mode() == mode_transcription.DISTANT


def test_env_prime_sur_config_dans_les_deux_sens(monkeypatch):
    """Contrairement à l'ancien DEBRIEFMEET_EDITION (monotone), l'override est
    bidirectionnel : le bundle unifié contient toute la pile, un « local » forcé
    ne peut plus tomber sur un moteur absent."""
    _vierge(monkeypatch)
    monkeypatch.setenv(mode_transcription.VAR_ENV, "local")
    mode_transcription.initialiser(_ConfigStub("distant"))
    assert mode_transcription.mode() == mode_transcription.LOCAL

    monkeypatch.setenv(mode_transcription.VAR_ENV, "distant")
    mode_transcription.initialiser(_ConfigStub("local"))
    assert mode_transcription.mode() == mode_transcription.DISTANT


def test_env_insensible_a_la_casse_et_aux_espaces(monkeypatch):
    _vierge(monkeypatch)
    monkeypatch.setenv(mode_transcription.VAR_ENV, "  LOCAL  ")
    mode_transcription.initialiser(_ConfigStub("distant"))
    assert mode_transcription.mode() == mode_transcription.LOCAL


def test_env_vide_ignoree(monkeypatch):
    _vierge(monkeypatch)
    monkeypatch.setenv(mode_transcription.VAR_ENV, "")
    mode_transcription.initialiser(_ConfigStub("local"))
    assert mode_transcription.mode() == mode_transcription.LOCAL


def test_fige_pour_la_duree_du_process(monkeypatch):
    """Changer l'env après `initialiser()` est sans effet : le mode est figé
    (cohérent avec le « redémarrage requis » des Préférences)."""
    _vierge(monkeypatch)
    mode_transcription.initialiser(_ConfigStub("local"))
    monkeypatch.setenv(mode_transcription.VAR_ENV, "distant")
    assert mode_transcription.mode() == mode_transcription.LOCAL


# ── Robustesse ───────────────────────────────────────────────────────────────

def test_config_inconnue_repli_distant_avec_avertissement(monkeypatch, caplog):
    """Jamais d'exception : une valeur invalide ne doit pas empêcher l'app de
    démarrer (même philosophie que selection_backend)."""
    _vierge(monkeypatch)
    with caplog.at_level(logging.WARNING,
                         logger="debrief_meet.core.mode_transcription"):
        mode_transcription.initialiser(_ConfigStub("turbo"))
    assert mode_transcription.mode() == mode_transcription.DISTANT
    assert "turbo" in caplog.text


def test_env_inconnue_ignoree_config_maitresse(monkeypatch):
    _vierge(monkeypatch)
    monkeypatch.setenv(mode_transcription.VAR_ENV, "n_importe_quoi")
    mode_transcription.initialiser(_ConfigStub("local"))
    assert mode_transcription.mode() == mode_transcription.LOCAL


def test_config_none_repli_distant(monkeypatch):
    _vierge(monkeypatch)
    mode_transcription.initialiser(_ConfigStub(None))
    assert mode_transcription.mode() == mode_transcription.DISTANT


# ── Capacités ────────────────────────────────────────────────────────────────

def test_capacites_local(monkeypatch):
    monkeypatch.setattr(mode_transcription, "_mode", mode_transcription.LOCAL)
    assert mode_transcription.avec_transcription_locale()
    assert mode_transcription.avec_diarization()
    assert mode_transcription.avec_dictee_journal()


def test_capacites_distant(monkeypatch):
    monkeypatch.setattr(mode_transcription, "_mode", mode_transcription.DISTANT)
    assert not mode_transcription.avec_transcription_locale()
    assert not mode_transcription.avec_diarization()
    assert not mode_transcription.avec_dictee_journal()
