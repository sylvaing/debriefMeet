"""Moteur faster-whisper (CTranslate2) — CPU int8, universel.

Interface : charger(taille) / transcrire(audio, langue) / liberer().
"""
from __future__ import annotations

import os

import numpy as np

from spike.backends_windows import modeles
from spike.backends_windows.journalisation import journal
from debrief_meet.platform.interfaces import ResultatTranscription, Segment

BACKEND = "faster-whisper"
DEVICE = "cpu"
COMPUTE_TYPE = "int8"


class MoteurFaster:
    def __init__(self) -> None:
        self.taille: str | None = None
        self._modele = None
        self._threads = max(1, (os.cpu_count() or 4) - 2)

    def charger(self, taille: str) -> None:
        from faster_whisper import WhisperModel
        self.taille = taille
        repo = modeles.resoudre_faster_whisper(taille)
        journal().debug("faster-whisper : chargement %s (threads=%s)", repo, self._threads)
        self._modele = WhisperModel(
            repo, device=DEVICE, compute_type=COMPUTE_TYPE, cpu_threads=self._threads)

    def transcrire(self, audio: np.ndarray, langue: str | None = None) -> ResultatTranscription:
        if self._modele is None:
            raise RuntimeError("Modèle non chargé.")
        segs_iter, info = self._modele.transcribe(audio.astype(np.float32), language=langue)
        segments: list[Segment] = []
        textes: list[str] = []
        for s in segs_iter:
            segments.append(Segment(float(s.start), float(s.end), s.text.strip()))
            textes.append(s.text)
        texte = " ".join(t.strip() for t in textes).strip()
        return ResultatTranscription(texte, getattr(info, "language", None), segments)

    def liberer(self) -> None:
        self._modele = None

    @staticmethod
    def info_device() -> dict:
        return {"device_reel": DEVICE, "compute_type": COMPUTE_TYPE}
