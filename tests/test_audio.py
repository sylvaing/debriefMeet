from __future__ import annotations

import threading

import numpy as np
import pytest

from debrief_meet.core.audio import BufferAudio, SEUIL_RMS_SILENCE, preparer_asr, reechantillonner


def test_buffer_accumule_plusieurs_chunks():
    buf = BufferAudio()
    buf.ajouter(np.ones(100, dtype=np.float32))
    buf.ajouter(np.ones(200, dtype=np.float32))
    result = buf.recuperer_et_vider()
    assert result.shape == (300,)


def test_buffer_vide_apres_recuperer():
    buf = BufferAudio()
    buf.ajouter(np.ones(50, dtype=np.float32))
    buf.recuperer_et_vider()
    assert buf.vide()


def test_buffer_thread_safe():
    buf = BufferAudio()
    n_threads = 10
    n_chunks = 100

    def ajouter():
        for _ in range(n_chunks):
            buf.ajouter(np.ones(10, dtype=np.float32))

    threads = [threading.Thread(target=ajouter) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = buf.recuperer_et_vider()
    assert result.shape == (n_threads * n_chunks * 10,)


def test_reechantillonnage_44100_vers_16000():
    audio = np.random.rand(44100).astype(np.float32)
    result = reechantillonner(audio, 44_100, 16_000)
    assert abs(result.shape[0] - 16000) <= 10


def test_reechantillonnage_stereo_vers_mono():
    n = 4410
    audio = np.random.rand(n, 2).astype(np.float32)
    result = reechantillonner(audio, 44_100, 16_000)
    assert result.ndim == 1


def test_reechantillonnage_deja_16000():
    audio = np.random.rand(16000).astype(np.float32)
    result = reechantillonner(audio, 16_000, 16_000)
    np.testing.assert_array_equal(result, audio)


def test_reechantillonnage_retourne_float32():
    audio = np.random.rand(44100).astype(np.float64)
    result = reechantillonner(audio, 44_100, 16_000)
    assert result.dtype == np.float32


def test_buffer_vide_retourne_tableau_vide():
    buf = BufferAudio()
    result = buf.recuperer_et_vider()
    assert result.shape == (0,)
    assert result.dtype == np.float32


# ── preparer_asr (normalisation centrale + porte anti-silence, docs/27) ────────

def test_preparer_asr_audio_vide_retourne_none():
    result = preparer_asr(np.array([], dtype=np.float32))
    assert result is None


def test_preparer_asr_silence_pur_retourne_none():
    silence = np.zeros(16_000, dtype=np.float32)
    result = preparer_asr(silence)
    assert result is None


def test_preparer_asr_souffle_quasi_nul_retourne_none():
    """Amplitude 5e-6 : sous le plancher anti-amplification (1e-5) → jamais remonté."""
    souffle = np.full(16_000, 5e-6, dtype=np.float32)
    result = preparer_asr(souffle)
    assert result is None


def test_preparer_asr_parole_faible_est_remontee():
    """Cas réel du 2026-07-02 : RMS ≈ 0.003 (micro faible) → normalisé au-dessus de la
    porte, non None. C'est LE test de non-régression du bug dictée/journal muets."""
    t = np.arange(16_000, dtype=np.float32) / 16_000.0
    faible = (np.sin(2 * np.pi * 220.0 * t) * (0.003 * np.sqrt(2.0))).astype(np.float32)

    result = preparer_asr(faible)

    assert result is not None
    rms = float(np.sqrt(np.mean(result.astype(np.float32) ** 2)))
    assert rms >= SEUIL_RMS_SILENCE
    assert 0.02 < rms < 0.04   # remonté vers la cible (0.03)


def test_preparer_asr_audio_fort_inchange():
    fort = np.ones(16_000, dtype=np.float32)
    result = preparer_asr(fort)
    assert result is not None
    np.testing.assert_array_equal(result, fort)
