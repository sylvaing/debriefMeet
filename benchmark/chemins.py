"""Résolution des chemins (assets embarqués, modèles, sortie).

Tout est surchargeable par variable d'environnement pour les tests et pour le
bundle (où les modèles sont à côté de l'exécutable).
"""
from __future__ import annotations

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent
ASSETS = RACINE / "assets"


def dossier_assets() -> Path:
    return Path(os.environ.get("BENCH_ASSETS", str(ASSETS)))


def dossier_modeles() -> Path:
    if v := os.environ.get("BENCH_MODELS"):
        return Path(v)
    default = dossier_assets() / "models"
    # Fallback dev : les modèles sherpa sont dans spike/diarization/models/
    # (l'assembleur les copie dans le bundle, mais pas dans le dépôt).
    spike = RACINE.parent / "spike" / "diarization" / "models"
    if not (default / "emb.onnx").exists() and spike.exists():
        return spike
    return default


def audio_canonique() -> Path:
    return Path(os.environ.get("BENCH_AUDIO", str(dossier_assets() / "audio_canonique.wav")))


def reference_txt() -> Path:
    return Path(os.environ.get("BENCH_REFERENCE", str(dossier_assets() / "reference.txt")))


def dossier_sortie() -> Path:
    """Dossier où sont écrits rapport/journal/artefacts (à côté de l'exe)."""
    return Path(os.environ.get("BENCH_SORTIE", str(Path.cwd() / "resultats_benchmark")))
