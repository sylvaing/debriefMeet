"""Sélection et abstraction du moteur de transcription pour le benchmark.

- macOS Apple Silicon → mlx-whisper (Metal) — mode baseline, pour comparer aux spikes.
- Windows / Linux → faster-whisper (CTranslate2) : CUDA float16 si NVIDIA, sinon CPU int8.

Les imports des moteurs sont lazy : le module s'importe partout, et un moteur
absent échoue proprement au chargement (capté par le pipeline) au lieu de
casser tout le run.
"""
from __future__ import annotations

import os

import numpy as np

from benchmark import modeles
from benchmark.journalisation import journal
from debrief_meet.platform.interfaces import ResultatTranscription, Segment


def choisir_mode(materiel: dict) -> dict:
    """Détermine backend/device/compute_type d'après le matériel détecté.

    Reflète la stratégie de docs/02-specifications-techniques.md.
    """
    osys = materiel.get("os")
    arch = (materiel.get("arch") or "").lower()
    gpu = materiel.get("gpu") or {}

    if osys == "macos" and arch in ("arm64", "aarch64"):
        return {"moteur": "mlx", "device": "metal", "compute_type": "float16"}

    if gpu.get("type") == "nvidia" and gpu.get("cuda"):
        return {"moteur": "faster-whisper", "device": "cuda", "compute_type": "float16"}

    # AMD/Intel/pas de GPU → CPU int8 (Vulkan/whisper.cpp = v2, hors périmètre).
    return {"moteur": "faster-whisper", "device": "cpu", "compute_type": "int8"}


class MoteurBench:
    """Moteur de transcription unifié (faster-whisper ou mlx) pour le benchmark."""

    def __init__(self, mode: dict, cpu_threads: int | None = None) -> None:
        self.mode = dict(mode)
        self.cpu_threads = cpu_threads or max(1, (os.cpu_count() or 4) - 2)
        self.taille: str | None = None
        self._modele = None  # faster-whisper : WhisperModel ; mlx : repo (str)

    # ── Chargement ────────────────────────────────────────────────────────────

    def charger(self, taille: str) -> None:
        self.taille = taille
        if self.mode["moteur"] == "mlx":
            self._charger_mlx(taille)
        else:
            self._charger_faster_whisper(taille)

    def _charger_mlx(self, taille: str) -> None:
        from debrief_meet.core.modeles import resoudre_mlx

        # mlx_whisper résout/charge le modèle au premier transcribe ; on mémorise le repo.
        self._modele = resoudre_mlx(taille)
        journal().debug("mlx : modèle résolu %s", self._modele)

    def _charger_faster_whisper(self, taille: str) -> None:
        from faster_whisper import WhisperModel

        repo = modeles.resoudre_faster_whisper(taille)
        journal().debug(
            "faster-whisper : chargement %s (device=%s, compute=%s, threads=%s)",
            repo, self.mode["device"], self.mode["compute_type"], self.cpu_threads,
        )
        self._modele = WhisperModel(
            repo,
            device=self.mode["device"],
            compute_type=self.mode["compute_type"],
            cpu_threads=self.cpu_threads,
        )

    # ── Transcription ───────────────────────────────────────────────────────────

    def transcrire(self, audio: np.ndarray, langue: str | None = None) -> ResultatTranscription:
        if self._modele is None:
            raise RuntimeError("Modèle non chargé : appeler charger() d'abord.")
        if self.mode["moteur"] == "mlx":
            return self._transcrire_mlx(audio, langue)
        return self._transcrire_faster_whisper(audio, langue)

    def _transcrire_mlx(self, audio: np.ndarray, langue: str | None) -> ResultatTranscription:
        import mlx_whisper

        res = mlx_whisper.transcribe(
            audio.astype(np.float32),
            path_or_hf_repo=self._modele,
            language=langue,
            verbose=None,
            condition_on_previous_text=False,
        )
        segments = [
            Segment(float(s["start"]), float(s["end"]), s["text"].strip())
            for s in res.get("segments", [])
        ]
        return ResultatTranscription(res.get("text", "").strip(), res.get("language"), segments)

    def _transcrire_faster_whisper(self, audio: np.ndarray, langue: str | None) -> ResultatTranscription:
        segs_iter, info = self._modele.transcribe(audio.astype(np.float32), language=langue)
        segments: list[Segment] = []
        textes: list[str] = []
        for s in segs_iter:  # générateur paresseux → consommé ici
            segments.append(Segment(float(s.start), float(s.end), s.text.strip()))
            textes.append(s.text)
        texte = " ".join(t.strip() for t in textes).strip()
        return ResultatTranscription(texte, getattr(info, "language", None), segments)

    # ── Libération mémoire ───────────────────────────────────────────────────────

    def liberer(self) -> None:
        """Libère le modèle (important entre tailles pour ne pas saturer la VRAM)."""
        self._modele = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
