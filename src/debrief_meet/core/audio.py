from __future__ import annotations

import logging
import threading

import numpy as np
from scipy.signal import resample_poly
from math import gcd

logger = logging.getLogger(__name__)

# Porte anti-silence centrale (anti-hallucination Whisper, cf. docs/22 et docs/27).
# Source unique : core/aec.py et les moteurs importent d'ici, plus de copies locales.
SEUIL_RMS_SILENCE = 0.008


class BufferAudio:
    def __init__(self) -> None:
        self._chunks: list[np.ndarray] = []
        self._verrou = threading.Lock()

    def ajouter(self, chunk: np.ndarray) -> None:
        with self._verrou:
            self._chunks.append(chunk)

    def recuperer_et_vider(self) -> np.ndarray:
        with self._verrou:
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks).astype(np.float32)
            self._chunks = []
            return audio

    def vide(self) -> bool:
        with self._verrou:
            return len(self._chunks) == 0


def reechantillonner(audio: np.ndarray, sr_source: int, sr_cible: int = 16_000) -> np.ndarray:
    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    audio = audio.astype(np.float32)

    if sr_source == sr_cible:
        return audio

    diviseur = gcd(sr_source, sr_cible)
    up = sr_cible // diviseur
    down = sr_source // diviseur
    return resample_poly(audio, up, down).astype(np.float32)


def normaliser_asr(audio: np.ndarray, cible_rms: float = 0.03,
                   gain_max: float = 20.0) -> np.ndarray:
    """Remonte le niveau d'un audio trop faible avant transcription/diarization.

    Le micro post-AEC (l'AEC atténue le niveau) — comme l'audio retenu encodé Opus —
    peut avoir un RMS moyen sous le seuil anti-silence du moteur (0.008) **alors qu'il
    contient de la parole claire** → le moteur le rejetterait à tort comme du silence.
    On le ramène à `cible_rms` (gain plafonné). Le **silence pur** (RMS ~0) est laissé
    tel quel, donc toujours ignoré à raison. N'atténue jamais un audio déjà assez fort."""
    if not len(audio):
        return audio
    rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
    if rms < 1e-5:                      # silence pur → ne pas amplifier du bruit
        return audio.astype(np.float32)
    facteur = min(cible_rms / rms, gain_max)
    if facteur <= 1.0:                  # déjà suffisant → ne pas toucher
        return audio.astype(np.float32)
    return np.clip(audio * facteur, -1.0, 1.0).astype(np.float32)


def rms(audio: np.ndarray) -> float:
    """Niveau efficace d'un buffer float32. 0.0 pour un buffer vide."""
    if not len(audio):
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))


def preparer_asr(audio: np.ndarray) -> np.ndarray | None:
    """Prépare un audio 16 kHz pour la transcription : normalise puis applique la
    porte anti-silence. Retourne None si l'audio ne doit pas être transcrit
    (vide, ou silence même après normalisation — le silence pur n'est pas amplifié).

    L'ordre normaliser→porter est contractuel (docs/27 §1.6) : porter l'audio brut
    rejetterait la parole faible (micro discret, piste post-AEC atténuée)."""
    if not len(audio):
        return None
    audio = normaliser_asr(audio)
    niveau = rms(audio)
    if niveau < SEUIL_RMS_SILENCE:
        logger.debug("Audio silencieux (RMS=%.4f < %.4f) — transcription ignorée",
                     niveau, SEUIL_RMS_SILENCE)
        return None
    return audio


def _wav_vers_float_mono(chemin) -> tuple[np.ndarray, int]:
    from scipy.io import wavfile

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


def _decoder_ffmpeg(chemin) -> tuple[np.ndarray, int]:
    import subprocess
    import tempfile
    from pathlib import Path

    from debrief_meet.core.fichiers import ErreurFfmpegIntrouvable, chemin_ffmpeg

    exe = chemin_ffmpeg()
    if exe is None:
        raise ErreurFfmpegIntrouvable()
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "decode.wav"
        subprocess.run(
            [exe, "-y", "-i", str(chemin), "-ac", "1", "-ar", "16000",
             "-f", "wav", str(wav)],
            check=True, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return _wav_vers_float_mono(wav)


def decoder_audio_16k(chemin) -> np.ndarray:
    """Décode un fichier audio (.wav, .opus…) en float32 mono 16 kHz.

    WAV via scipy ; autres formats (Opus de la rétention réunion) via ffmpeg.
    Lève si le fichier est illisible / ffmpeg absent.
    """
    from pathlib import Path

    chemin = Path(chemin)
    if chemin.suffix.lower() == ".wav":
        audio, sr = _wav_vers_float_mono(chemin)
    else:
        audio, sr = _decoder_ffmpeg(chemin)
    if sr != 16_000:
        audio = reechantillonner(audio, sr, 16_000)
    return audio.astype(np.float32)
