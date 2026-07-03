"""Tests — assistant guidé d'activation de la diarization (Lot 1).

Aucun réseau : `diarization.telecharger` est monkeypatché. Cf. docs/13.
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from debrief_meet.ui.assistant_diarization import (
    _DOSSIER_ASSETS,
    _PAGE_TELECHARGEMENT,
    _PAGE_TOKEN,
    AssistantDiarization,
    _pixmap_svg,
    _WorkerTelechargement,
)


# ── Navigation entre les étapes ─────────────────────────────────────────────────

def test_navigation_avance_et_recule(qapp):
    a = AssistantDiarization()
    assert a._stack.currentIndex() == 0
    a._suivant()
    a._suivant()
    a._suivant()
    assert a._stack.currentIndex() == _PAGE_TOKEN     # étapes 1→2→3→4 (saisie token)
    a._precedent()
    assert a._stack.currentIndex() == 2
    assert a._btn_prec.isEnabled() is True


def test_precedent_desactive_a_la_premiere_etape(qapp):
    a = AssistantDiarization()
    assert a._btn_prec.isEnabled() is False
    assert a._btn_suiv.text() == "Suivant"


# ── Illustrations (assets SVG rendus) — Lot 2 ───────────────────────────────────

def test_assets_illustrations_presents():
    for i in range(1, 6):
        assert (_DOSSIER_ASSETS / f"diar_etape_{i}.svg").exists()


def test_pixmap_svg_rend_une_image(qapp):
    pm = _pixmap_svg(_DOSSIER_ASSETS / "diar_etape_1.svg")
    assert not pm.isNull() and pm.width() > 0


def test_chaque_etape_a_son_illustration(qapp):
    a = AssistantDiarization()
    for i in range(a._stack.count()):
        labels = a._stack.widget(i).findChildren(QLabel)
        assert any(not lab.pixmap().isNull() for lab in labels), f"étape {i} sans illustration"


# ── Worker de téléchargement (appelé en direct) ─────────────────────────────────

def test_worker_succes(qapp, monkeypatch):
    from debrief_meet.core import diarization
    monkeypatch.setattr(diarization, "telecharger", lambda token: None)
    finis = []
    w = _WorkerTelechargement("hf_x")
    w.fini.connect(lambda: finis.append(True))
    w.executer()
    assert finis == [True]


def test_worker_echec_remonte_le_message(qapp, monkeypatch):
    from debrief_meet.core import diarization

    def _ko(token):
        raise diarization.ErreurLicence("Licence non acceptée — revenez à l'étape 2.")
    monkeypatch.setattr(diarization, "telecharger", _ko)
    msgs = []
    w = _WorkerTelechargement("hf_x")
    w.echec.connect(msgs.append)
    w.executer()
    assert msgs == ["Licence non acceptée — revenez à l'étape 2."]


# ── « Vérifier et télécharger » ─────────────────────────────────────────────────

def test_token_vide_n_appelle_pas_telecharger(qapp, monkeypatch):
    from debrief_meet.core import diarization
    appels = []
    monkeypatch.setattr(diarization, "telecharger", lambda token: appels.append(token))
    a = AssistantDiarization()
    a._stack.setCurrentIndex(_PAGE_TOKEN)
    a._champ_token.setText("")
    a._suivant()
    assert appels == []


def test_verifier_telecharge_puis_succes(qapp, qtbot, monkeypatch):
    from debrief_meet.core import diarization
    appels = []
    monkeypatch.setattr(diarization, "telecharger", lambda token: appels.append(token))
    a = AssistantDiarization()
    a._stack.setCurrentIndex(_PAGE_TOKEN)
    a._champ_token.setText("hf_abc")
    a._suivant()                                      # déclenche le téléchargement
    assert a._stack.currentIndex() == _PAGE_TELECHARGEMENT
    qtbot.waitUntil(lambda: a._succes, timeout=5000)
    a._thread.wait(2000)
    assert appels == ["hf_abc"]
    assert "activée" in a._label_resultat.text().lower()
    assert a._btn_suiv.text() == "Terminer"


def test_echec_permet_de_reessayer(qapp, qtbot, monkeypatch):
    from debrief_meet.core import diarization

    def _ko(token):
        raise diarization.ErreurToken("Token incorrect — vérifiez l'étape 3.")
    monkeypatch.setattr(diarization, "telecharger", _ko)
    a = AssistantDiarization()
    a._stack.setCurrentIndex(_PAGE_TOKEN)
    a._champ_token.setText("mauvais")
    a._suivant()
    qtbot.waitUntil(lambda: not a._thread.isRunning(), timeout=5000)
    assert a._succes is False
    assert "token incorrect" in a._label_resultat.text().lower()
    assert a._btn_suiv.text() == "Réessayer"
