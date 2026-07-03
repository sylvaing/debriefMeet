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
