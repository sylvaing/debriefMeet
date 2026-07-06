"""Formatage mono du chronomètre mm:ss — partagé entre la barre d'action de
capture (`capture_action_bar.py`) et la ligne « en cours » du tableau Réunion
(`capture_model.py`).
"""
from __future__ import annotations


def formater_chrono(secondes: int) -> str:
    m, s = divmod(max(0, secondes), 60)
    return f"{m:02d}:{s:02d}"
