"""Tables de modèles pour le benchmark : transcription + diarisation.

Calqué sur core/modeles.py (TABLE_MLX). Le sweep de transcription couvre
small → medium → large-v3 pour déterminer le plus gros modèle viable.
"""
from __future__ import annotations

from benchmark import chemins

# ── Transcription ─────────────────────────────────────────────────────────────

# Tailles balayées par défaut (du plus léger au plus lourd).
SWEEP = ["small", "medium", "large-v3"]

# faster-whisper (Windows/Linux) : repos CTranslate2.
TABLE_FASTER_WHISPER: dict[str, str] = {
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def resoudre_faster_whisper(taille: str) -> str:
    """Chemin local du modèle dans le bundle s'il existe, sinon le repo HF.

    En bundle hors-ligne, les modèles sont pré-téléchargés dans assets/models/ ;
    on pointe dessus directement. Sinon WhisperModel téléchargera (dev/online).
    """
    local = chemins.dossier_modeles() / f"faster-whisper-{taille}"
    if local.is_dir():
        return str(local)
    if taille in TABLE_FASTER_WHISPER:
        return TABLE_FASTER_WHISPER[taille]
    raise ValueError(f"Taille inconnue : {taille!r}. Valides : {list(TABLE_FASTER_WHISPER)}")


# OpenVINO (Windows/Linux, GPU Intel) : modèles INT8 pré-convertis (publics, Apache).
TABLE_OPENVINO: dict[str, str] = {
    "small": "OpenVINO/whisper-small-int8-ov",
    "medium": "OpenVINO/whisper-medium-int8-ov",
    "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
}


def resoudre_openvino(taille: str) -> str:
    """Dossier local du modèle OpenVINO dans le bundle s'il existe, sinon le repo HF."""
    local = chemins.dossier_modeles() / f"openvino-whisper-{taille}"
    if local.is_dir():
        return str(local)
    if taille in TABLE_OPENVINO:
        return TABLE_OPENVINO[taille]
    raise ValueError(f"Taille inconnue : {taille!r}. Valides : {list(TABLE_OPENVINO)}")


# ── Diarisation ─────────────────────────────────────────────────────────────

# pyannote 4.0 (gated — token HF requis au téléchargement, pas au runtime offline).
PYANNOTE_PIPELINE = "pyannote/speaker-diarization-community-1"

# sherpa-onnx (sans licence) — mêmes noms de fichiers que dans spike/diarization.
SHERPA_SEGMENTATION = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
SHERPA_EMBEDDING = "emb.onnx"


def chemin_sherpa_segmentation() -> "object":
    return chemins.dossier_modeles() / SHERPA_SEGMENTATION


def chemin_sherpa_embedding() -> "object":
    return chemins.dossier_modeles() / SHERPA_EMBEDDING
