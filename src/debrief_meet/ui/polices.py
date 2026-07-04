"""Chargement des polices embarquées (refonte design, IBM Plex Sans/Mono).

Pas de .qrc : chemins de fichiers directs, comme le reste de `ui/assets/`
(cf. `ui/icones.py` pour la fonte Tabler).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"

_FICHIERS = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexSans-Bold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
)


def charger_polices(app: QApplication) -> None:
    """Enregistre les polices IBM Plex embarquées et les définit par défaut.

    À appeler après la création de `QApplication`, avant toute création de widget.
    Sans effet si un fichier est absent (Qt se rabat alors sur une police système) —
    tolérant tant que `ui/assets/fonts/*.ttf` n'a pas encore été fourni.
    """
    for nom in _FICHIERS:
        chemin = FONT_DIR / nom
        if not chemin.exists():
            logger.debug("Police absente (ignorée) : %s", chemin)
            continue
        if QFontDatabase.addApplicationFont(str(chemin)) == -1:
            logger.warning("Échec de chargement de la police : %s", chemin)
    app.setFont(QFont(SANS, 10))
