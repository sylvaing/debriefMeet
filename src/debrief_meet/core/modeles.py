from __future__ import annotations

TABLE_MLX: dict[str, str] = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}

NOMS_LOGIQUES: list[str] = list(TABLE_MLX)


def resoudre_mlx(nom_logique: str) -> str:
    try:
        return TABLE_MLX[nom_logique]
    except KeyError:
        raise ValueError(f"Modèle inconnu : {nom_logique!r}. Valeurs valides : {NOMS_LOGIQUES}")


# ── faster-whisper (CTranslate2, Windows) — docs/34 §1.3 ─────────────────────
# small/medium/large-v3 validés par le spike docs/18 ; tiny/base/large-v2 suivent le
# même repo officiel Systran (pattern confirmé par le spike, non testé individuellement).
# large-v3-turbo : repo CT2 turbo utilisé par le spike (Systran n'en publie pas).
TABLE_FASTER_WHISPER: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
}


def resoudre_faster_whisper(nom_logique: str) -> str:
    try:
        return TABLE_FASTER_WHISPER[nom_logique]
    except KeyError:
        raise ValueError(f"Modèle inconnu : {nom_logique!r}. Valeurs valides : {NOMS_LOGIQUES}")
