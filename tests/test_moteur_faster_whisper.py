"""Tests unitaires — MoteurFasterWhisper : gate RMS anti-hallucination + arrêt propre
du pool (miroir test_moteur_mlx.py). Imports paresseux (faster_whisper chargé
seulement dans le sous-processus) → testable sans faster-whisper installé, en
injectant de faux workers dans le pool."""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
import pytest

from debrief_meet.platform.windows.moteur_faster_whisper import (
    MoteurFasterWhisper,
    _coeurs_physiques_bornes,
    dossier_modeles,
)


class _FauxWorker:
    """Faux _WorkerSubprocess : enregistre les appels, ne lance aucun sous-processus."""

    def __init__(self, reponse: dict | None = None) -> None:
        self.reponse = reponse or {"ok": True, "texte": "bonjour", "langue": "fr", "segments": []}
        self.appels_transcrire: list[tuple] = []
        self.termine = False
        self.tue = False

    def transcrire(self, audio_bytes: bytes, repo: str, langue: str | None) -> dict:
        self.appels_transcrire.append((audio_bytes, repo, langue))
        return self.reponse

    def terminer(self) -> None:
        self.termine = True

    def tuer(self) -> None:
        self.tue = True


# ── Gate RMS (héritée de la classe de base, E-5) ─────────────────────────────

def test_gate_rms_silence_retourne_vide_sans_worker():
    moteur = MoteurFasterWhisper()
    silence = np.zeros(16_000, dtype=np.float32)

    resultat = moteur.transcrire(silence, None)

    assert resultat.texte == ""
    assert resultat.segments == []
    assert moteur._pool.qsize() == 0
    assert moteur._n_workers == 0


def test_gate_rms_au_dessus_du_seuil_appelle_le_worker():
    moteur = MoteurFasterWhisper()
    moteur._nom_charge = "large-v3"
    faux = _FauxWorker({"ok": True, "texte": "salut", "langue": "fr", "segments": []})
    moteur._n_workers = 1
    moteur._pool.put(faux)

    fort = np.ones(16_000, dtype=np.float32)
    resultat = moteur.transcrire(fort, None)

    assert len(faux.appels_transcrire) == 1
    assert resultat.texte == "salut"
    assert resultat.langue_detectee == "fr"
    assert moteur._pool.qsize() == 1


def test_log_debug_tranche_jamais_le_texte(caplog):
    """E-1 (docs/22/31 §3.7.2) : la sonde hallucinations logge durée/RTF/segments/
    longueur — jamais le texte transcrit lui-même."""
    moteur = MoteurFasterWhisper()
    moteur._nom_charge = "large-v3"
    faux = _FauxWorker({"ok": True, "texte": "un secret à ne jamais logger", "langue": "fr", "segments": []})
    moteur._n_workers = 1
    moteur._pool.put(faux)

    with caplog.at_level(logging.DEBUG, logger="debrief_meet"):
        moteur.transcrire(np.ones(16_000, dtype=np.float32), None)

    messages = [r.message for r in caplog.records]
    assert any("Tranche transcrite" in m and "rtf=" in m for m in messages)
    assert not any("secret" in m for m in messages)


def test_transcrire_non_overridee():
    """E-5 (docs/33 §2.5) : normalisation + porte anti-silence héritées, jamais
    réimplémentées par le backend."""
    from debrief_meet.platform.interfaces import MoteurTranscription
    assert MoteurFasterWhisper.transcrire is MoteurTranscription.transcrire


# ── Arrêt propre du pool + registre (E-4, docs/26/33 §2.4) ──────────────────

def test_terminer_recupere_et_termine_tous_les_workers():
    moteur = MoteurFasterWhisper()
    w1, w2 = _FauxWorker(), _FauxWorker()
    moteur._n_workers = 2
    moteur._pool.put(w1)
    moteur._pool.put(w2)

    moteur.terminer()

    assert w1.termine and w2.termine
    assert moteur._pool.qsize() == 0
    assert moteur._n_workers == 0


def test_terminer_attend_un_worker_occupe_rendu_en_retard():
    moteur = MoteurFasterWhisper()
    worker = _FauxWorker()
    moteur._n_workers = 1
    threading.Timer(0.1, lambda: moteur._pool.put(worker)).start()

    debut = time.monotonic()
    moteur.terminer()
    ecoule = time.monotonic() - debut

    assert worker.termine
    assert ecoule >= 0.1


def test_terminer_balaie_les_workers_geles_hors_pool():
    moteur = MoteurFasterWhisper()
    gele = _FauxWorker()
    moteur._workers = [gele]

    moteur.terminer()

    assert gele.tue is True
    assert moteur._workers == []


def test_terminer_balaie_seulement_les_restants_apres_recuperation_pool():
    moteur = MoteurFasterWhisper()
    poli = _FauxWorker()
    gele = _FauxWorker()
    moteur._n_workers = 1
    moteur._pool.put(poli)
    moteur._workers = [poli, gele]

    moteur.terminer()

    assert poli.termine is True
    assert gele.tue is True
    assert moteur._workers == []


def test_recharger_modele_arrete_puis_relance(monkeypatch):
    from debrief_meet.core.modeles import resoudre_faster_whisper

    moteur = MoteurFasterWhisper()
    ancien = _FauxWorker()
    moteur._n_workers = 1
    moteur._pool.put(ancien)

    crees: list[str] = []
    monkeypatch.setattr(moteur, "_creer_worker", lambda repo: crees.append(repo))

    moteur.recharger_modele("medium")

    assert ancien.termine
    assert moteur._nom_charge == "medium"
    for _ in range(100):
        if len(crees) >= 1:
            break
        time.sleep(0.01)
    assert crees == [resoudre_faster_whisper("medium")]


# ── tuer() idempotent (registre docs/26) ─────────────────────────────────────

class _FauxPopen:
    def __init__(self) -> None:
        self.appels_kill = 0
        self.appels_wait = 0

    def kill(self) -> None:
        self.appels_kill += 1

    def wait(self, timeout: float | None = None) -> None:
        self.appels_wait += 1


def test_tuer_idempotent():
    from debrief_meet.platform.windows.moteur_faster_whisper import _WorkerSubprocess

    w = _WorkerSubprocess("repo-test")
    fake_proc = _FauxPopen()
    w._proc = fake_proc

    w.tuer()

    assert fake_proc.appels_kill == 1
    assert fake_proc.appels_wait == 1
    assert w._proc is None

    w.tuer()
    assert fake_proc.appels_kill == 1


# ── Détails Windows spécifiques ──────────────────────────────────────────────

def test_dossier_modeles_sous_user_data_dir(monkeypatch, tmp_path):
    import platformdirs
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **kw: str(tmp_path))
    assert dossier_modeles() == tmp_path / "modeles"


def test_dossier_modeles_appauthor_false_evite_le_doublon_windows(monkeypatch, tmp_path):
    """Sans `appauthor=False`, platformdirs double le dossier sur Windows
    (`%LOCALAPPDATA%\\debriefMeet\\debriefMeet`, docs/32 §4)."""
    import platformdirs

    appels = []
    monkeypatch.setattr(
        platformdirs, "user_data_dir",
        lambda *a, **kw: appels.append((a, kw)) or str(tmp_path),
    )
    dossier_modeles()
    assert appels[0][1].get("appauthor") is False


def test_coeurs_physiques_bornes_ne_depasse_jamais_le_maximum(monkeypatch):
    import os
    monkeypatch.setattr(os, "cpu_count", lambda: 32)
    assert _coeurs_physiques_bornes(maximum=8) == 8


def test_coeurs_physiques_bornes_au_moins_un(monkeypatch):
    import os
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert _coeurs_physiques_bornes() >= 1


# ── Téléchargement de modèles (download_root forcé, docs/34 §1.3) ───────────

def test_est_telecharge_true_quand_snapshot_present(monkeypatch, tmp_path):
    # `huggingface_hub` sort du bundle en édition lite (docs/44) : ce test porte
    # sur du code qui en dépend, il se saute plutôt que de casser la gate lite.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda *a, **kw: str(tmp_path))
    assert MoteurFasterWhisper().est_telecharge("large-v3") is True


def test_est_telecharge_false_si_absent(monkeypatch):
    # `huggingface_hub` sort du bundle en édition lite (docs/44) : ce test porte
    # sur du code qui en dépend, il se saute plutôt que de casser la gate lite.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub

    def _leve(*a, **kw):
        raise FileNotFoundError("pas en cache localement")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", _leve)
    assert MoteurFasterWhisper().est_telecharge("large-v3") is False


def test_telecharger_modele_force_le_cache_dir_et_relaie_la_progression(monkeypatch, tmp_path):
    # `huggingface_hub` sort du bundle en édition lite (docs/44) : ce test porte
    # sur du code qui en dépend, il se saute plutôt que de casser la gate lite.
    pytest.importorskip("huggingface_hub")
    import huggingface_hub
    import platformdirs
    monkeypatch.setattr(platformdirs, "user_data_dir", lambda *a, **kw: str(tmp_path))

    appels: list[tuple] = []
    monkeypatch.setattr(
        huggingface_hub, "snapshot_download", lambda repo, **kw: appels.append((repo, kw))
    )

    progres: list[float] = []
    MoteurFasterWhisper().telecharger_modele("large-v3", progression=progres.append)

    assert len(appels) == 1
    repo, kwargs = appels[0]
    assert repo == "Systran/faster-whisper-large-v3"
    assert kwargs["cache_dir"] == str(tmp_path / "modeles")
    assert progres == [1.0]
