"""Journalisation du spike backends Windows.

Run unique par machine → on logge tout en DEBUG fichier + résumé INFO console.
"""
from __future__ import annotations

import logging
from pathlib import Path

NOM_LOGGER = "spike_backends"


def configurer_journal(chemin: Path, console: bool = True) -> logging.Logger:
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
    logger = logging.getLogger(NOM_LOGGER)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger
