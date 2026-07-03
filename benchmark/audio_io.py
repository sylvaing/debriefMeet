"""Chargement audio pour le benchmark → float32 mono 16 kHz.

Réutilise core/audio.py:reechantillonner. Décode via scipy pour le WAV, via
ffmpeg pour les autres formats (mp3…). ffmpeg est optionnel : absent, on se
limite au WAV.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from benchmark.journalisation import journal
from debrief_meet.core.audio import reechantillonner

SR_CIBLE = 16_000


def _wav_vers_float_mono(chemin: Path) -> tuple[np.ndarray, int]:
    sr, data = wavfile.read(chemin)
    data = np.asarray(data)
    etait_entier = np.issubdtype(data.dtype, np.integer)
    if data.ndim == 2:
        data = data.mean(axis=1)
    data = data.astype(np.float32)
    # Normalise les entiers PCM en [-1, 1].
    if etait_entier or np.max(np.abs(data)) > 1.5:
        data = data / 32768.0
    return data.astype(np.float32), int(sr)


def _decoder_ffmpeg(chemin: Path) -> tuple[np.ndarray, int]:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "decode.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(chemin), "-ac", "1", "-ar", str(SR_CIBLE),
             "-f", "wav", str(wav)],
            check=True, capture_output=True,
        )
        return _wav_vers_float_mono(wav)


def charger(chemin: Path | str, sr_cible: int = SR_CIBLE) -> tuple[np.ndarray, int]:
    """Charge un fichier audio → (float32 mono, sr_cible). Lève si le fichier est illisible."""
    chemin = Path(chemin)
    if chemin.suffix.lower() == ".wav":
        audio, sr = _wav_vers_float_mono(chemin)
    else:
        journal().debug("décodage ffmpeg de %s", chemin)
        audio, sr = _decoder_ffmpeg(chemin)
    if sr != sr_cible:
        audio = reechantillonner(audio, sr, sr_cible)
    return audio.astype(np.float32), sr_cible
