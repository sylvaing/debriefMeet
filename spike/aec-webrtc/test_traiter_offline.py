"""Tests des fonctions pures du traitement offline (sans enregistrement ni Whisper).

Lancer depuis la racine du projet :
    .venv/bin/python -m pytest spike/aec-webrtc/test_traiter_offline.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import traiter_offline as t  # noqa: E402
import analyser_drift as ad  # noqa: E402


# ── WER ──────────────────────────────────────────────────────────────────────

def test_wer_identique():
    assert t.wer("bonjour tout le monde", "bonjour tout le monde") == 0.0


def test_wer_insensible_casse():
    assert t.wer("Bonjour Monde", "bonjour monde") == 0.0


def test_wer_une_substitution():
    # 1 mot faux sur 3 → 1/3
    assert abs(t.wer("le chat noir", "le chien noir") - 1 / 3) < 1e-9


def test_wer_reference_vide():
    assert t.wer("", "") == 0.0
    assert t.wer("", "bruit") == 1.0


# ── Similarité ────────────────────────────────────────────────────────────────

def test_similarite_identique():
    assert t.similarite("texte", "texte") == 1.0


def test_similarite_disjointe_plus_faible_quidentique():
    s_ident = t.similarite("le chat dort", "le chat dort")
    s_diff = t.similarite("le chat dort", "voiture rouge")
    assert s_diff < s_ident


# ── Alignement ────────────────────────────────────────────────────────────────

def test_estimer_delai_positif():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 0.3, t.SR_CIBLE * 4).astype(np.float32)
    delai = 800  # échantillons
    mic = np.zeros_like(ref)
    mic[delai:] = ref[:-delai] * 0.5
    assert abs(t.estimer_delai(mic, ref) - delai) <= 2


def test_estimer_delai_borne_plage_plausible():
    # Bruit non corrélé : le délai estimé doit rester dans ±DELAI_MAX_MS,
    # jamais un faux verrou à un lag extrême.
    rng = np.random.default_rng(7)
    mic = rng.normal(0, 0.3, t.SR_CIBLE * 5).astype(np.float32)
    ref = rng.normal(0, 0.3, t.SR_CIBLE * 5).astype(np.float32)
    d = t.estimer_delai(mic, ref)
    assert abs(d) <= t.DELAI_MAX_MS / 1000 * t.SR_CIBLE


def test_aligner_recale_la_reference():
    rng = np.random.default_rng(1)
    ref = rng.normal(0, 0.3, t.SR_CIBLE).astype(np.float32)
    delai = 500
    mic = np.zeros_like(ref)
    mic[delai:] = ref[:-delai]
    mic_a, ref_a = t.aligner(mic, ref, delai)
    # après recalage, l'écho dans le micro et la référence sont corrélés à lag 0
    n = min(len(mic_a), len(ref_a))
    c0 = float(np.corrcoef(mic_a[delai:n], ref_a[delai:n])[0, 1])
    assert c0 > 0.9


def test_derive_nulle_sur_delai_constant():
    rng = np.random.default_rng(2)
    ref = rng.normal(0, 0.3, t.SR_CIBLE * 20).astype(np.float32)
    delai = 320
    mic = np.zeros_like(ref)
    mic[delai:] = ref[:-delai] * 0.5
    delais = t.mesurer_derive(mic, ref, delai)
    assert max(delais) - min(delais) <= 2


# ── Dérive (Étape 2) ──────────────────────────────────────────────────────────

def test_taux_derive_pente_connue():
    # délai croît linéairement de 0 à 60 ms sur 60 s → +60 ms/min
    pts = [(s, s) for s in range(0, 61, 5)]  # (t_s, delai_ms) = identité
    assert abs(ad.taux_derive_ms_min(pts) - 60.0) < 1e-6


def test_taux_derive_stable_est_nul():
    pts = [(s, -250.0) for s in range(0, 60, 4)]
    assert abs(ad.taux_derive_ms_min(pts)) < 1e-6


def test_courbe_delai_dans_la_borne():
    rng = np.random.default_rng(11)
    ref = rng.normal(0, 0.3, t.SR_CIBLE * 12).astype(np.float32)
    delai = 480  # 30 ms
    mic = np.zeros_like(ref)
    mic[delai:] = ref[:-delai] * 0.5
    pts = ad.courbe_delai(mic, ref)
    assert pts and all(abs(d_ms) <= t.DELAI_MAX_MS for _, d_ms in pts)
    # le délai mesuré doit être proche de 30 ms
    assert all(abs(d_ms - 30) < 5 for _, d_ms in pts)


# ── RMS / dB ──────────────────────────────────────────────────────────────────

def test_rms_silence():
    assert t.rms(np.zeros(1000, dtype=np.float32)) == 0.0


def test_db_demi_amplitude():
    assert abs(t.db(0.5) - (-6.02)) < 0.1
