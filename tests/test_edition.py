"""Édition compilée + capacités (docs/44).

L'édition doit être résolue **à l'appel** et non figée à l'import : c'est ce qui
permet aux tests (et à `DEBRIEFMEET_EDITION=lite make run`) d'exercer l'édition lite
sans rebuild ni `importlib.reload`.
"""
from __future__ import annotations

import logging

import debrief_meet
from debrief_meet.core import edition


# ── Résolution ───────────────────────────────────────────────────────────────

def test_defaut_est_complete(monkeypatch):
    monkeypatch.delenv(edition.VAR_ENV, raising=False)
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "complete")
    assert edition.edition() == edition.COMPLETE
    assert not edition.est_lite()


def test_edition_compilee_lite_honoree(monkeypatch):
    monkeypatch.delenv(edition.VAR_ENV, raising=False)
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "lite")
    assert edition.edition() == edition.LITE
    assert edition.est_lite()


def test_env_restreint_vers_lite(monkeypatch):
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "complete")
    monkeypatch.setenv(edition.VAR_ENV, "lite")
    assert edition.est_lite()


def test_env_ne_peut_pas_elargir_vers_complete(monkeypatch):
    """Résolution monotone : un bundle lite n'a pas faster-whisper, le laisser se
    croire complet ferait écrire la sortie du stub dans un vrai débrief."""
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "lite")
    monkeypatch.setenv(edition.VAR_ENV, "complete")
    assert edition.est_lite()


def test_resolution_a_lappel_et_non_a_limport(monkeypatch):
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "complete")
    monkeypatch.delenv(edition.VAR_ENV, raising=False)
    assert not edition.est_lite()
    monkeypatch.setenv(edition.VAR_ENV, "lite")
    assert edition.est_lite()


def test_env_insensible_a_la_casse_et_aux_espaces(monkeypatch):
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "complete")
    monkeypatch.setenv(edition.VAR_ENV, "  LITE  ")
    assert edition.est_lite()


def test_env_vide_ignoree(monkeypatch):
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "complete")
    monkeypatch.setenv(edition.VAR_ENV, "")
    assert edition.edition() == edition.COMPLETE


# ── Robustesse ───────────────────────────────────────────────────────────────

def test_valeur_inconnue_repli_complete_avec_avertissement(monkeypatch, caplog):
    """Jamais d'exception : une valeur invalide ne doit pas empêcher l'app de
    démarrer (même philosophie que selection_backend)."""
    monkeypatch.delenv(edition.VAR_ENV, raising=False)
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "turbo")
    with caplog.at_level(logging.WARNING, logger="debrief_meet.core.edition"):
        assert edition.edition() == edition.COMPLETE
    assert "turbo" in caplog.text


def test_env_inconnue_ignoree(monkeypatch):
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "lite")
    monkeypatch.setenv(edition.VAR_ENV, "n_importe_quoi")
    assert edition.est_lite()   # la valeur figée reste maîtresse


# ── Capacités ────────────────────────────────────────────────────────────────

def test_capacites_completes(monkeypatch):
    monkeypatch.delenv(edition.VAR_ENV, raising=False)
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "complete")
    assert edition.avec_transcription_locale()
    assert edition.avec_diarization()
    assert edition.avec_dictee_journal()


def test_capacites_lite(monkeypatch):
    monkeypatch.setattr(debrief_meet, "EDITION_COMPILEE", "lite")
    assert not edition.avec_transcription_locale()
    assert not edition.avec_diarization()
    assert not edition.avec_dictee_journal()
