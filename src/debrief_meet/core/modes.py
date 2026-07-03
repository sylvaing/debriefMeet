from __future__ import annotations

import logging
from enum import Enum, auto

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class Mode(Enum):
    IDLE = auto()
    DICTEE = auto()
    REUNION = auto()
    JOURNAL = auto()


class EtatVisuel(Enum):
    """État d'activité reflété par la couleur de l'icône (indépendant du mode).

    REPOS          : aucune activité — icône template monochrome (s'adapte à la barre).
    ENREGISTREMENT : capture audio en cours — rouge.
    TRANSCRIPTION  : transcription en cours (dictée/journal, à l'arrêt) — orange.
    TERMINE        : transcription terminée — vert, bref, puis retour REPOS.
    ERREUR         : échec de transcription — gris, bref, puis retour REPOS.
    """

    REPOS = auto()
    ENREGISTREMENT = auto()
    TRANSCRIPTION = auto()
    TERMINE = auto()
    ERREUR = auto()


class MachineEtats(QObject):
    """Machine à états des modes d'enregistrement.

    Un seul mode peut être actif à la fois. toggle_*() démarre ou arrête le mode ;
    démarrer un mode pendant qu'un autre est actif émet le signal `erreur`.
    """

    mode_change = Signal(object)   # Mode
    erreur = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode = Mode.IDLE

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def est_actif(self) -> bool:
        return self._mode != Mode.IDLE

    def toggle_dictee(self) -> bool:
        return self._transition(Mode.DICTEE)

    def toggle_reunion(self) -> bool:
        return self._transition(Mode.REUNION)

    def toggle_journal(self) -> bool:
        return self._transition(Mode.JOURNAL)

    def _transition(self, cible: Mode) -> bool:
        if self._mode == cible:
            logger.info("Mode %s → IDLE", cible.name)
            self._mode = Mode.IDLE
            self.mode_change.emit(Mode.IDLE)
            return True

        if self._mode != Mode.IDLE:
            msg = f"Mode {self._mode.name} actif — impossible de démarrer {cible.name}"
            logger.warning(msg)
            self.erreur.emit(msg)
            return False

        logger.info("IDLE → %s", cible.name)
        self._mode = cible
        self.mode_change.emit(cible)
        return True
