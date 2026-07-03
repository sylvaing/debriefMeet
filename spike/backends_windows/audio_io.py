"""Chargement audio pour le spike → float32 mono 16 kHz."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from spike.backends_windows.journalisation import journal
from debrief_meet.core.audio import reechantillonner

SR_CIBLE = 16_000


def _wav_vers_float_mono(chemin: Path) -> tuple[np.ndarray, int]:
    sr, data = wavfile.read(chemin)
    data = np.asarray(data)
    etait_entier = np.issubdtype(data.dtype, np.integer)
    if data.ndim == 2:
        data = data.mean(axis=1)
    data = data.astype(np.float32)
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
    """Charge un fichier audio → (float32 mono, sr_cible). Lève si illisible."""
    chemin = Path(chemin)
    if chemin.suffix.lower() == ".wav":
        audio, sr = _wav_vers_float_mono(chemin)
    else:
        journal().debug("décodage ffmpeg de %s", chemin)
        audio, sr = _decoder_ffmpeg(chemin)
    if sr != sr_cible:
        audio = reechantillonner(audio, sr, sr_cible)
    return audio.astype(np.float32), sr_cible


def ecrire_wav(audio: np.ndarray, sr: int, chemin: Path) -> None:
    """Écrit un array float32 → WAV PCM 16 bits."""
    pcm = np.clip(audio, -1.0, 1.0)
    wavfile.write(chemin, sr, (pcm * 32767).astype(np.int16))
