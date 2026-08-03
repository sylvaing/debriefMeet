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

    Instrumentation (2026-07-31, diagnostic Alix) : sur une machine Windows à puce
    Realtek SST, ce signal est émis **~1 fois par seconde** en continu (92 occurrences
    dans un log), ce qui déclenche autant de reconnexions micro et affame le flux. Reste
    à savoir si la liste des entrées **change réellement** ou si Qt émet un signal
    parasite — les deux appellent des correctifs opposés. On journalise donc l'écart
    entre deux relevés. **Aucun événement n'est filtré ici** : l'observation ne doit pas
    modifier le comportement tant que la cause n'est pas établie (la reconnexion
    inconditionnelle est le correctif macOS de docs/25, à ne pas casser).
    """

    change = Signal()

    def __init__(self, debounce_ms: int = 300, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Import paresseux : Qt Multimedia charge le backend (ffmpeg) au premier usage.
        from PySide6.QtMultimedia import QMediaDevices

        self._media = QMediaDevices(self)
        self._apercu: tuple[str, ...] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self.change)
        self._media.audioInputsChanged.connect(self._planifier)

    def _releve_entrees(self) -> tuple[str, ...]:
        """Descriptions des entrées vues par **Qt** — et non la table PortAudio, dont la
        péremption est justement ce que docs/25 reprochait à l'ancienne comparaison."""
        try:
            from PySide6.QtMultimedia import QMediaDevices

            return tuple(sorted(d.description() for d in QMediaDevices.audioInputs()))
        except Exception:  # noqa: BLE001 — l'instrumentation ne doit jamais gêner
            return ()

    @Slot()
    def _planifier(self) -> None:
        # Chaque événement (re)lance le délai : `change` n'est émis qu'une fois
        # le flux d'événements stabilisé pendant `debounce_ms`.
        apercu = self._releve_entrees()
        if self._apercu is None:
            logger.debug("Entrées audio — relevé initial : %d périphérique(s)", len(apercu))
        elif apercu == self._apercu:
            logger.debug(
                "Changement signalé mais liste INCHANGÉE (%d périphériques) — "
                "signal Qt parasite", len(apercu))
        else:
            ajouts = [d for d in apercu if d not in self._apercu]
            retraits = [d for d in self._apercu if d not in apercu]
            logger.debug("Liste des entrées MODIFIÉE : +%s / -%s", ajouts or "∅", retraits or "∅")
        self._apercu = apercu

        logger.debug("Changement de périphériques d'entrée détecté — anti-rebond relancé")
        self._timer.start()
