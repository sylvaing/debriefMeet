"""Moteur whisper.cpp Vulkan (binaire officiel en subprocess).

Le binaire whisper-cli officiel est compilé avec Vulkan : il couvre iGPU Intel et AMD
sans dépendre de PyPI. Il tourne en subprocess isolé (pas d'extension Python).

Raison du subprocess : les wheels PyPI de pywhispercpp sont compilées CPU-only
(Vulkan absent). Le binaire officiel découple la brique compilée du Python embeddable.

Gate : gate_vulkan() (accel.py).
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from spike.backends_windows import chemins, modeles
from spike.backends_windows.audio_io import ecrire_wav
from spike.backends_windows.journalisation import journal
from debrief_meet.platform.interfaces import ResultatTranscription, Segment

SR = 16_000
BACKEND = "vulkan"
TIMEOUT_S = 600


class MoteurWhisperCpp:
    def __init__(self) -> None:
        self.taille: str | None = None
        self._chemin_modele: str | None = None
        self._binaire = chemins.binaire_whispercpp()

    def charger(self, taille: str) -> None:
        self.taille = taille
        self._chemin_modele = modeles.resoudre_vulkan_ggml(taille)
        journal().debug("whispercpp : modèle %s, binaire %s",
                        self._chemin_modele, self._binaire)

    def transcrire(self, audio: np.ndarray, langue: str | None = None) -> ResultatTranscription:
        if self._chemin_modele is None:
            raise RuntimeError("Modèle non chargé.")

        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "input.wav"
            ecrire_wav(audio, SR, wav)

            cmd = [
                str(self._binaire),
                "-m", self._chemin_modele,
                "-f", str(wav),
                "--no-prints",       # supprime les méta-infos, garde la transcription
                "--print-special",   # n.
                "-t", str(max(1, 4)),  # threads (conservateur — ne pas saturer l'hôte)
            ]
            if langue:
                cmd += ["-l", langue]

            journal().debug("whispercpp cmd : %s", " ".join(cmd))
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=TIMEOUT_S, check=False)

        if proc.returncode != 0:
            journal().debug("whispercpp stderr : %s", proc.stderr[:500])
            raise RuntimeError(f"whisper-cli retcode={proc.returncode}: {proc.stderr[:200]}")

        return _parser_sortie(proc.stdout, len(audio) / SR)

    def liberer(self) -> None:
        self._chemin_modele = None

    @staticmethod
    def info_device() -> dict:
        return {"device_reel": "vulkan", "compute_type": "ggml_q5_0"}


# ── Parsing de la sortie texte whisper.cpp ────────────────────────────────────
# Format stdout (sans --output-txt) :
# [00:00:00.000 --> 00:00:05.123]   Bonjour tout le monde.

_RE_SEGMENT = re.compile(
    r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]\s*(.*)")


def _ts_to_s(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _parser_sortie(stdout: str, duree_audio: float) -> ResultatTranscription:
    segments: list[Segment] = []
    textes: list[str] = []
    langue_detectee: str | None = None

    for ligne in stdout.splitlines():
        m = _RE_SEGMENT.match(ligne.strip())
        if m:
            debut = _ts_to_s(m.group(1))
            fin = _ts_to_s(m.group(2))
            texte_seg = m.group(3).strip()
            if texte_seg:
                segments.append(Segment(debut, fin, texte_seg))
                textes.append(texte_seg)
        # whisper.cpp imprime la langue détectée sur stderr généralement,
        # mais on la cherche aussi dans stdout (certaines versions).
        if "auto-detected language:" in ligne.lower():
            parts = ligne.lower().split("auto-detected language:")
            if len(parts) > 1:
                langue_detectee = parts[1].strip().split()[0] if parts[1].strip() else None

    texte = " ".join(textes).strip()
    return ResultatTranscription(texte, langue_detectee, segments)
