"""Tests — mini-didacticiel clé API Mistral (docs/42 §9.4). Miroir de
`test_assistant_diarization.py` : navigation + worker via QThread réel (qtbot),
aucun réseau réel (respx)."""
from __future__ import annotations

import httpx
import respx

from debrief_meet.ui.assistant_mistral import _PAGE_CLE, _PAGE_TEST, AssistantMistral

URL = "https://api.mistral.ai"


def _config(tmp_path):
    from debrief_meet.core.config import Config
    return Config(chemin=tmp_path / "config.json")


# ── Navigation ───────────────────────────────────────────────────────────────────

def test_navigation_avance_et_recule(qapp, tmp_path):
    a = AssistantMistral(_config(tmp_path))
    assert a._stack.currentIndex() == 0
    a._suivant()
    a._suivant()
    assert a._stack.currentIndex() == _PAGE_CLE
    a._precedent()
    assert a._stack.currentIndex() == 1
    assert a._btn_prec.isEnabled() is True


def test_precedent_desactive_a_la_premiere_etape(qapp, tmp_path):
    a = AssistantMistral(_config(tmp_path))
    assert a._btn_prec.isEnabled() is False
    assert a._btn_suiv.text() == "Suivant"


def test_cle_vide_ne_lance_pas_de_test(qapp, tmp_path):
    a = AssistantMistral(_config(tmp_path))
    a._stack.setCurrentIndex(_PAGE_CLE)
    a._champ_cle.setText("")
    a._suivant()
    assert a._thread is None


# ── Test de connexion (worker en arrière-plan) ──────────────────────────────────

@respx.mock
def test_verifier_teste_puis_succes(qapp, qtbot, tmp_path):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
    config = _config(tmp_path)
    a = AssistantMistral(config)
    a._stack.setCurrentIndex(_PAGE_CLE)
    a._champ_cle.setText("cle-valide")
    a._suivant()
    assert a._stack.currentIndex() == _PAGE_TEST
    qtbot.waitUntil(lambda: a._succes, timeout=5000)
    assert "réussie" in a._label_resultat.text().lower()
    assert a._btn_suiv.text() == "Terminer"
    assert config.get("mistral_cle_api") == "cle-valide"     # persistée sur succès


@respx.mock
def test_echec_permet_de_reessayer(qapp, qtbot, tmp_path):
    respx.get(f"{URL}/v1/models").mock(return_value=httpx.Response(401))
    config = _config(tmp_path)
    a = AssistantMistral(config)
    a._stack.setCurrentIndex(_PAGE_CLE)
    a._champ_cle.setText("mauvaise-cle")
    a._suivant()
    qtbot.waitUntil(lambda: not a._thread.isRunning(), timeout=5000)
    assert a._succes is False
    assert a._btn_suiv.text() == "Réessayer"
    assert config.get("mistral_cle_api") == ""                # pas persistée sur échec
