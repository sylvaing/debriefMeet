"""Résolution des chemins (assets, modèles, sortie).

Variables d'environnement SPIKE_* surchargent les défauts (bundle hors-ligne).
"""
from __future__ import annotations

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent
ASSETS = RACINE / "assets"


def dossier_assets() -> Path:
    return Path(os.environ.get("SPIKE_ASSETS", str(ASSETS)))


def dossier_modeles() -> Path:
    if v := os.environ.get("SPIKE_MODELS"):
        return Path(v)
    return dossier_assets() / "models"


def audio_canonique() -> Path:
    return Path(os.environ.get("SPIKE_AUDIO", str(dossier_assets() / "audio_canonique.wav")))


def dossier_sortie() -> Path:
    return Path(os.environ.get("SPIKE_SORTIE", str(Path.cwd() / "resultats_spike")))


def binaire_whispercpp() -> Path:
    """Chemin du binaire whisper-cli (whisper.cpp Vulkan)."""
    if v := os.environ.get("SPIKE_WHISPER_CLI"):
        return Path(v)
    import sys
    nom = "whisper-cli.exe" if sys.platform == "win32" else "whisper-cli"
    # D'abord à côté des assets (bundle), sinon sur le PATH.
    local = dossier_assets() / nom
    if local.exists():
        return local
    return Path(nom)
