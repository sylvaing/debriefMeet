"""Presse-papiers Linux — docs/49 §5.2.

Identique à l'implémentation Windows : `QGuiApplication.clipboard()` masque les
différences X11/Wayland (l'app est déjà PySide6, aucun appel externe à `xclip` ou
`wl-copy` n'est nécessaire — ce qui évite au passage une dépendance de plus dans le
`.deb`).

Piège Linux classique neutralisé par la nature de l'app : sous X11 comme sous
Wayland, le contenu du presse-papiers appartient au processus qui l'a posé et
disparaît avec lui. debriefMeet étant résidente en tray, le texte copié survit
aussi longtemps que l'utilisateur en a besoin.

Appels depuis le thread principal Qt uniquement (comme sur les autres OS)."""
from __future__ import annotations

import logging

from PySide6.QtGui import QGuiApplication

from debrief_meet.platform.interfaces import PressePapiers

logger = logging.getLogger(__name__)


class PressePapiersLinux(PressePapiers):
    def copier(self, texte: str) -> None:
        QGuiApplication.clipboard().setText(texte)
        # Jamais le texte lui-même dans les logs (docs/31 §3.7.1) — la longueur seule.
        logger.debug("PressePapiersLinux: copier(%d chars)", len(texte))

    def copier_fichier(self, chemin) -> None:
        # `text/uri-list` — le format compris par Nautilus et consorts pour un
        # collage de fichier (Qt y ajoute le fallback texte du chemin).
        from PySide6.QtCore import QMimeData, QUrl
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(chemin))])
        QGuiApplication.clipboard().setMimeData(mime)
        logger.debug("PressePapiersLinux: copier_fichier(%s)", chemin)

    def lire(self) -> str:
        return QGuiApplication.clipboard().text()
