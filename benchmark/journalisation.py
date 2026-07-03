"""Journalisation exhaustive du benchmark.

Le bench ne tourne qu'une fois par machine : on ne pourra pas rejouer pour
creuser. On logge donc tout au maximum dans un fichier verbeux (DEBUG) écrit à
côté du rapport, et un résumé lisible (INFO) en console.
"""
from __future__ import annotations

import logging
from pathlib import Path

NOM_LOGGER = "benchmark"


def configurer_journal(chemin: Path, console: bool = True) -> logging.Logger:
    """Configure le logger du benchmark : fichier DEBUG + console INFO.

    Idempotent : reconfigurer remplace les handlers existants.
    """
    logger = logging.getLogger(NOM_LOGGER)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    chemin.parent.mkdir(parents=True, exist_ok=True)
    fichier = logging.FileHandler(chemin, encoding="utf-8")
    fichier.setLevel(logging.DEBUG)
    fichier.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s")
    )
    logger.addHandler(fichier)

    if console:
        sortie = logging.StreamHandler()
        sortie.setLevel(logging.INFO)
        sortie.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(sortie)

    return logger


def journal() -> logging.Logger:
    """Retourne le logger du benchmark (NullHandler tant que non configuré)."""
    logger = logging.getLogger(NOM_LOGGER)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger
