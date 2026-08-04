"""Tests — section Préférences « Remote IA » (docs/42 §9.1). Bloc Mistral, extensible
(un seul bloc en v1). Sans réseau réel pour le test de connexion (respx)."""
from __future__ import annotations

import pytest

import httpx
import respx

from debrief_meet.core.config import Config
from debrief_meet.ui.remote_ia_view import RemoteIAView


@pytest.fixture(autouse=True)
def _edition(edition_complete_sauf_si_lite):
    """Sujet du module : dont la case « forcer Voxtral », absente en lite — édition complète épinglée sauf test lite explicite
    (docs/44)."""

URL = "https://api.mistral.ai"


def _config(tmp_path):
    return Config(chemin=tmp_path / "config.json")


def test_cle_api_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("s3cr3t")
    vue._edit_cle.editingFinished.emit()
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_cle_api") == "s3cr3t"


def test_combo_modele_transcription_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert vue._combo_modele_transcription.currentData() == "voxtral-mini-latest"


def test_combo_modele_cr_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    idx = vue._combo_modele_cr.findData("mistral-medium-latest")
    vue._combo_modele_cr.setCurrentIndex(idx)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_modele_cr") == "mistral-medium-latest"


def test_case_forcer_voxtral_decochee_par_defaut(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert vue._check_forcer_voxtral.isChecked() is False
    assert cfg.get("mistral_source_transcription") == "auto"


def test_case_forcer_voxtral_coche_bascule_la_source(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._check_forcer_voxtral.setChecked(True)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_source_transcription") == "voxtral"


def test_case_forcer_voxtral_decoche_revient_auto(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("mistral_source_transcription", "voxtral")
    vue = RemoteIAView(cfg)
    assert vue._check_forcer_voxtral.isChecked() is True
    vue._check_forcer_voxtral.setChecked(False)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("mistral_source_transcription") == "auto"


def test_tester_connexion_sans_cle_affiche_message(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("")
    vue._tester_connexion()
    assert "requise" in vue._label_statut.text().lower()


@respx.mock
def test_tester_connexion_succes(qapp, qtbot, tmp_path):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("cle-valide")
    vue._tester_connexion()
    qtbot.waitUntil(lambda: "✓" in vue._label_statut.text(), timeout=5000)


@respx.mock
def test_tester_connexion_echec(qapp, qtbot, tmp_path):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(401))
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    vue._edit_cle.setText("mauvaise-cle")
    vue._tester_connexion()
    qtbot.waitUntil(lambda: "Échec" in vue._label_statut.text(), timeout=5000)


# ── Édition lite (docs/44) ───────────────────────────────────────────────────

def test_lite_pas_de_case_forcer_voxtral(qapp, tmp_path, edition_lite):
    """Inerte en lite : il n'y a jamais de transcription locale à ignorer, et
    « auto » y est déjà équivalent à « voxtral »."""
    cfg = _config(tmp_path)
    vue = RemoteIAView(cfg)
    assert not hasattr(vue, "_check_forcer_voxtral")
    assert cfg.get("mistral_source_transcription") == "auto"
    assert vue._edit_cle is not None      # la clé API reste configurable, et obligatoire
