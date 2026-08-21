"""Presse-papiers Windows — docs/34 §3.

`QGuiApplication.clipboard()` gère nativement l'Unicode et les subtilités Win32
(formats, verrous) : l'app est déjà PySide6, pas besoin de ctypes ici. Appels
depuis le thread principal Qt uniquement — la copie est déjà déclenchée par
l'UI/les orchestrateurs sur ce thread (comme `pbcopy` sur macOS)."""
from __future__ import annotations

import logging

from PySide6.QtGui import QGuiApplication

from debrief_meet.platform.interfaces import PressePapiers

logger = logging.getLogger(__name__)


class PressePapiersWindows(PressePapiers):
    def copier(self, texte: str) -> None:
        QGuiApplication.clipboard().setText(texte)
        # Jamais le texte lui-même dans les logs (docs/31 §3.7.1) — la longueur seule.
        logger.debug("PressePapiersWindows: copier(%d chars)", len(texte))

    def copier_fichier(self, chemin) -> None:
        # Qt traduit les URLs en CF_HDROP — le format attendu par l'Explorateur
        # pour un collage de fichier.
        from PySide6.QtCore import QMimeData, QUrl
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(chemin))])
        QGuiApplication.clipboard().setMimeData(mime)
        logger.debug("PressePapiersWindows: copier_fichier(%s)", chemin)

    def lire(self) -> str:
        return QGuiApplication.clipboard().text()
