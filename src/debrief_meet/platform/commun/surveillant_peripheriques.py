from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal, Slot

logger = logging.getLogger(__name__)


class SurveillantPeripheriques(QObject):
    """Surveille les périphériques d'entrée audio et signale leurs changements.

    S'appuie sur `QMediaDevices.audioInputsChanged` (Qt Multimedia) — un signal
    événementiel, instantané et cross-platform, émis dès qu'un périphérique
    d'entrée apparaît ou disparaît (ex. retrait des AirPods).

    Les changements arrivent souvent en rafale (un retrait émet plusieurs
    événements) : un anti-rebond les regroupe en un seul signal `change`.
    """

    change = Signal()

    def __init__(self, debounce_ms: int = 300, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Import paresseux : Qt Multimedia charge le backend (ffmpeg) au premier usage.
        from PySide6.QtMultimedia import QMediaDevices

        self._media = QMediaDevices(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self.change)
        self._media.audioInputsChanged.connect(self._planifier)

    @Slot()
    def _planifier(self) -> None:
        # Chaque événement (re)lance le délai : `change` n'est émis qu'une fois
        # le flux d'événements stabilisé pendant `debounce_ms`.
        logger.debug("Changement de périphériques d'entrée détecté — anti-rebond relancé")
        self._timer.start()
