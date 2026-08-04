from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QObject, QTimer, Signal, Slot

logger = logging.getLogger(__name__)


class SurveillantPeripheriques(QObject):
    """Surveille les périphériques d'entrée audio et signale leurs changements.

    S'appuie sur `QMediaDevices.audioInputsChanged` (Qt Multimedia) — un signal
    événementiel, instantané et cross-platform, émis dès qu'un périphérique
    d'entrée apparaît ou disparaît (ex. retrait des AirPods).

    Les changements arrivent souvent en rafale (un retrait émet plusieurs
    événements) : un anti-rebond les regroupe en un seul signal `change`.

    ## Suppression des signaux parasites — **Windows uniquement** (docs/44 §8)

    Sur une machine Windows à puce Realtek SST, `audioInputsChanged` est émis
    ~1 fois par seconde en continu : 3086 événements mesurés dont la liste des entrées
    était **identique**, contre 3 changements réels (un casque Bluetooth). Chacun
    provoquait une reconnexion micro (3082 en 65 min), affamait le flux et empêchait
    l'AEC de se caler — le micro n'était pas enregistré.

    On ignore donc l'événement quand la liste Qt est inchangée… **mais seulement sur
    Windows**. Ailleurs, le comportement historique est conservé au caractère près,
    et ce n'est pas un excès de prudence : la comparaison porte sur `description()`,
    donc elle ne verrait PAS un changement de taux d'échantillonnage à périphérique
    constant (AirPods 24↔48 kHz, docs/20) ni un changement de périphérique par défaut
    à liste constante. Sur macOS ces deux cas sont couverts aujourd'hui par la
    reconnexion inconditionnelle de docs/25 — les supprimer serait une régression, et
    nous n'avons aucune donnée macOS pour l'affirmer sans risque.

    Filet de sécurité conservé dans tous les cas : le watchdog « tranche muette »
    (`core/reunion.py`) reconnecte le micro si son buffer reste vide sur une tranche
    entière, même si un événement a été ignoré à tort.
    """

    change = Signal()

    def __init__(self, debounce_ms: int = 300, parent: QObject | None = None,
                 supprimer_parasites: bool | None = None) -> None:
        super().__init__(parent)
        # Import paresseux : Qt Multimedia charge le backend (ffmpeg) au premier usage.
        from PySide6.QtMultimedia import QMediaDevices

        # Paramètre explicite plutôt qu'un `sys.platform` lu directement dans
        # `_planifier` : les tests deviennent déterministes sur les deux OS (la gate
        # de build tourne sur la VM Windows, où un défaut implicite inverserait le
        # comportement attendu par les tests d'anti-rebond).
        self._supprimer_parasites = (
            sys.platform == "win32" if supprimer_parasites is None else supprimer_parasites)
        self._media = QMediaDevices(self)
        self._apercu: tuple[str, ...] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self.change)
        self._media.audioInputsChanged.connect(self._planifier)

    def _releve_entrees(self) -> tuple[str, ...]:
        """Descriptions des entrées vues par **Qt** — et non la table PortAudio, dont la
        péremption est justement ce que docs/25 reprochait à l'ancienne comparaison.

        Tuple vide = relevé indisponible (voir le repli fail-open dans `_planifier`)."""
        try:
            from PySide6.QtMultimedia import QMediaDevices

            return tuple(sorted(d.description() for d in QMediaDevices.audioInputs()))
        except Exception:  # noqa: BLE001 — l'instrumentation ne doit jamais gêner
            return ()

    @Slot()
    def _planifier(self) -> None:
        apercu = self._releve_entrees()
        inchangee = self._apercu is not None and apercu == self._apercu

        if self._apercu is None:
            logger.debug("Entrées audio — relevé initial : %d périphérique(s)", len(apercu))
        elif inchangee:
            logger.debug(
                "Changement signalé mais liste INCHANGÉE (%d périphériques) — "
                "signal Qt parasite", len(apercu))
        else:
            ajouts = [d for d in apercu if d not in self._apercu]
            retraits = [d for d in self._apercu if d not in apercu]
            logger.debug("Liste des entrées MODIFIÉE : +%s / -%s", ajouts or "∅", retraits or "∅")
        self._apercu = apercu

        # Repli **fail-open** : un relevé vide (Qt indisponible, ou plus aucune entrée)
        # ne doit jamais faire passer pour « inchangé » ce qu'on n'a pas pu observer —
        # sinon une panne de l'instrumentation désactiverait en silence la reconnexion
        # à chaud. Dans le doute, on reconnecte.
        if inchangee and apercu and self._supprimer_parasites:
            logger.debug("Événement ignoré (liste inchangée) — pas de reconnexion micro")
            return

        # Chaque événement (re)lance le délai : `change` n'est émis qu'une fois
        # le flux d'événements stabilisé pendant `debounce_ms`.
        logger.debug("Changement de périphériques d'entrée détecté — anti-rebond relancé")
        self._timer.start()
