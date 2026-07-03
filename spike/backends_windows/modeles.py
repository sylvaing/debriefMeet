"""Tables de modèles pour le spike backends Windows.

4 backends × 4 modèles (small / medium / large-v3 / large-v3-turbo).
Chaque table expose une fonction resoudre_*() : chemin local du bundle s'il
existe, sinon repo HuggingFace (online). En bundle offline HF_HUB_OFFLINE=1.
"""
from __future__ import annotations

from spike.backends_windows import chemins

SWEEP = ["small", "medium", "large-v3", "large-v3-turbo"]

# ── faster-whisper (CTranslate2) ──────────────────────────────────────────────

TABLE_FASTER_WHISPER: dict[str, str] = {
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
}


def resoudre_faster_whisper(taille: str) -> str:
    local = chemins.dossier_modeles() / f"faster-whisper-{taille}"
    if local.is_dir():
        return str(local)
    if taille in TABLE_FASTER_WHISPER:
        return TABLE_FASTER_WHISPER[taille]
    raise ValueError(f"Taille inconnue : {taille!r}. Valides : {list(TABLE_FASTER_WHISPER)}")


# ── OpenVINO (optimum-intel, GPU Intel) ───────────────────────────────────────

TABLE_OPENVINO: dict[str, str | None] = {
    "small": "OpenVINO/whisper-small-int8-ov",
    "medium": "OpenVINO/whisper-medium-int8-ov",
    "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
    # turbo : converti par l'assembleur si pas de repo public disponible
    "large-v3-turbo": None,
}


def resoudre_openvino(taille: str) -> str:
    local = chemins.dossier_modeles() / f"openvino-whisper-{taille}"
    if local.is_dir():
        return str(local)
    repo = TABLE_OPENVINO.get(taille)
    if repo:
        return repo
    raise ValueError(f"Modèle OpenVINO {taille!r} non disponible (local ou HF).")


# ── DirectML (ONNX Runtime, iGPU Intel+AMD) ───────────────────────────────────
# Modèles ONNX pré-convertis (onnx-community). Fichiers ONNX dans onnx/ ou à la racine.

TABLE_DIRECTML_HF: dict[str, str] = {
    "small": "onnx-community/whisper-small",
    "medium": "Xenova/whisper-medium",           # onnx-community/whisper-medium : 401
    "large-v3": "Xenova/whisper-large-v3",       # onnx-community/whisper-large-v3 : 401
    "large-v3-turbo": "onnx-community/whisper-large-v3-turbo",
}


def resoudre_directml(taille: str) -> str:
    local = chemins.dossier_modeles() / f"directml-whisper-{taille}"
    if local.is_dir():
        return str(local)
    if taille in TABLE_DIRECTML_HF:
        return TABLE_DIRECTML_HF[taille]
    raise ValueError(f"Taille inconnue : {taille!r}. Valides : {list(TABLE_DIRECTML_HF)}")


# Variante fp16 native (pas de quantization dynamique — cf. doc 18 §12.3) :
# kwargs ORTModelForSpeechSeq2Seq.from_pretrained() + filtre snapshot_download.
DIRECTML_FICHIERS_FP16: dict[str, str] = {
    "encoder_file_name": "encoder_model_fp16.onnx",
    "decoder_file_name": "decoder_model_fp16.onnx",
    "decoder_with_past_file_name": "decoder_with_past_model_fp16.onnx",
}
DIRECTML_ALLOW_PATTERNS: list[str] = ["onnx/*_fp16.onnx", "*.json", "*.txt"]


# ── Vulkan / whisper.cpp (binaire ggml) ───────────────────────────────────────

TABLE_VULKAN_GGML: dict[str, str] = {
    "small": "ggml-small-q5_1.bin",  # q5_0 n'existe pas pour small (404) — cf. doc 18 §12.4
    "medium": "ggml-medium-q5_0.bin",
    "large-v3": "ggml-large-v3-q5_0.bin",
    "large-v3-turbo": "ggml-large-v3-turbo-q5_0.bin",
}


def resoudre_vulkan_ggml(taille: str) -> str:
    """Chemin du fichier ggml quantifié (dans le bundle)."""
    nom = TABLE_VULKAN_GGML.get(taille)
    if nom is None:
        raise ValueError(f"Taille inconnue : {taille!r}.")
    local = chemins.dossier_modeles() / "ggml" / nom
    if local.exists():
        return str(local)
    raise FileNotFoundError(
        f"Modèle ggml absent : {local}\n"
        "L'assembleur doit télécharger les ggml depuis ggerganov/whisper.cpp releases.")
