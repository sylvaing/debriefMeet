"""Tests unitaires — MoteurMLX : gate RMS anti-hallucination + arrêt propre du pool.

MoteurMLX a des imports paresseux (mlx_whisper chargé seulement dans le sous-processus),
donc la classe est importable et testable sans Apple Silicon ni modèle, en injectant
de faux workers dans le pool.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from debrief_meet.platform.macos.moteur_mlx import MoteurMLX


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


# ── Gate RMS (anti-hallucination Whisper) ────────────────────────────────────

def test_gate_rms_silence_retourne_vide_sans_worker():
    """Audio silencieux (RMS < seuil) → texte vide, le pool n'est jamais sollicité."""
    moteur = MoteurMLX()
    silence = np.zeros(16_000, dtype=np.float32)

    resultat = moteur.transcrire(silence, None)

    assert resultat.texte == ""
    assert resultat.segments == []
    # Aucun worker créé ni consommé : le court-circuit a opéré avant le pool.
    assert moteur._pool.qsize() == 0
    assert moteur._n_workers == 0


def test_audio_vide_retourne_vide_sans_warning():
    """Tranche vide (0 échantillon, ex. dernière tranche à l'arrêt) → texte vide, et
    surtout **aucun RuntimeWarning numpy** (le RMS n'est plus calculé sur un slice vide)."""
    import warnings

    moteur = MoteurMLX()
    vide = np.array([], dtype=np.float32)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)   # un warning numpy ferait échouer le test
        resultat = moteur.transcrire(vide, None)

    assert resultat.texte == ""
    assert resultat.segments == []
    assert moteur._n_workers == 0                          # court-circuit avant le pool


def test_gate_rms_souffle_quasi_nul_court_circuite():
    """Un souffle quasi nul (sous le plancher anti-amplification) reste ignoré, le
    pool n'est jamais sollicité."""
    moteur = MoteurMLX()
    souffle = np.full(16_000, 5e-6, dtype=np.float32)

    resultat = moteur.transcrire(souffle, None)

    assert resultat.texte == ""
    assert moteur._n_workers == 0


def test_gate_rms_faible_mais_normalisable_sollicite_le_pool():
    """RMS 0.004 (sous le seuil brut) est remonté par la normalisation centrale du
    moteur → transcrit — comportement volontairement changé, aligné sur le pipeline
    réunion (docs/27 §1.6) : avant, ce niveau était rejeté comme silence."""
    moteur = MoteurMLX()
    moteur._nom_charge = "large-v3"
    faux = _FauxWorker({"ok": True, "texte": "salut", "langue": "fr", "segments": []})
    moteur._n_workers = 1
    moteur._pool.put(faux)

    faible = np.full(16_000, 0.004, dtype=np.float32)
    resultat = moteur.transcrire(faible, None)

    assert len(faux.appels_transcrire) == 1
    assert resultat.texte == "salut"


def test_gate_rms_au_dessus_du_seuil_appelle_le_worker():
    """Audio au-dessus du seuil → le worker est bien sollicité et le texte remonte."""
    moteur = MoteurMLX()
    moteur._nom_charge = "large-v3"
    faux = _FauxWorker({"ok": True, "texte": "salut", "langue": "fr", "segments": []})
    moteur._n_workers = 1
    moteur._pool.put(faux)

    fort = np.ones(16_000, dtype=np.float32)  # RMS = 1.0 ≫ seuil
    resultat = moteur.transcrire(fort, None)

    assert len(faux.appels_transcrire) == 1
    assert resultat.texte == "salut"
    assert resultat.langue_detectee == "fr"
    # Le worker est rendu au pool après usage.
    assert moteur._pool.qsize() == 1


# ── Arrêt propre du pool (fix segfault Metal) ────────────────────────────────

def test_terminer_recupere_et_termine_tous_les_workers():
    moteur = MoteurMLX()
    w1, w2 = _FauxWorker(), _FauxWorker()
    moteur._n_workers = 2
    moteur._pool.put(w1)
    moteur._pool.put(w2)

    moteur.terminer()

    assert w1.termine and w2.termine
    assert moteur._pool.qsize() == 0
    assert moteur._n_workers == 0          # état remis à zéro (permet un rechargement propre)


def test_recharger_modele_arrete_puis_relance(monkeypatch):
    """recharger_modele (à chaud) : arrête les workers du modèle courant et en relance
    avec le nouveau, sans cumuler les anciens (fix du compteur dans terminer)."""
    import time

    from debrief_meet.core.modeles import resoudre_mlx

    moteur = MoteurMLX()
    ancien = _FauxWorker()
    moteur._n_workers = 1
    moteur._pool.put(ancien)

    crees: list[str] = []
    monkeypatch.setattr(moteur, "_creer_worker", lambda repo: crees.append(repo))

    moteur.recharger_modele("medium")

    assert ancien.termine                       # ancien worker arrêté
    assert moteur._nom_charge == "medium"
    for _ in range(100):                         # charger_modele relance des threads → on attend
        if len(crees) >= 2:
            break
        time.sleep(0.01)
    assert crees == [resoudre_mlx("medium")] * 2   # _TAILLE_POOL workers du nouveau modèle


def test_terminer_attend_un_worker_occupe_rendu_en_retard():
    """Le fix : terminer() doit attendre un worker encore en transcription.

    L'ancien code (get_nowait) ratait un worker hors du pool ; le pool était
    détruit pendant que le contexte Metal tournait → SIGSEGV. terminer() bloque
    désormais jusqu'au retour du worker.
    """
    moteur = MoteurMLX()
    worker = _FauxWorker()
    moteur._n_workers = 1
    # Pool vide au départ : le worker est « occupé », rendu après 100 ms.
    threading.Timer(0.1, lambda: moteur._pool.put(worker)).start()

    debut = time.monotonic()
    moteur.terminer()
    ecoule = time.monotonic() - debut

    assert worker.termine
    assert ecoule >= 0.1  # a bien attendu le retour du worker


# ── Registre des workers + arrêt forcé (docs/26) ─────────────────────────────

class _FauxPopen:
    def __init__(self) -> None:
        self.appels_kill = 0
        self.appels_wait = 0

    def kill(self) -> None:
        self.appels_kill += 1

    def wait(self, timeout: float | None = None) -> None:
        self.appels_wait += 1


def test_tuer_idempotent():
    from debrief_meet.platform.macos.moteur_mlx import _WorkerSubprocess

    w = _WorkerSubprocess("repo-test")
    fake_proc = _FauxPopen()
    w._proc = fake_proc

    w.tuer()

    assert fake_proc.appels_kill == 1
    assert fake_proc.appels_wait == 1
    assert w._proc is None

    w.tuer()  # second appel : no-op, pas de nouveau kill()

    assert fake_proc.appels_kill == 1


def test_terminer_balaie_les_workers_geles_hors_pool():
    """Un worker enregistré dans le registre mais jamais rendu au pool (gelé en pleine
    transcription, ex. read() bloqué) doit être tué au balayage final de terminer()."""
    moteur = MoteurMLX()
    gele = _FauxWorker()
    moteur._workers = [gele]
    # n_workers = 0 : le worker gelé n'est comptabilisé ni dans le pool ni comme actif —
    # terminer() ne le récupère donc pas via la boucle pool.get(), seul le balayage l'atteint.

    moteur.terminer()

    assert gele.tue is True
    assert moteur._workers == []


def test_terminer_balaie_seulement_les_restants_apres_recuperation_pool():
    """Un worker rendu au pool est arrêté poliment (terminer()) ; un second worker,
    jamais rendu (gelé), est tué par le balayage — les deux registres ne se chevauchent pas."""
    moteur = MoteurMLX()
    poli = _FauxWorker()
    gele = _FauxWorker()
    moteur._n_workers = 1
    moteur._pool.put(poli)
    moteur._workers = [poli, gele]

    moteur.terminer()

    assert poli.termine is True
    assert gele.tue is True
    assert moteur._workers == []
