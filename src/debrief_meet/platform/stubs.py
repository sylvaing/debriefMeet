"""Implémentations no-op utilisées par l'app en Phase 0 (avant les vrais adaptateurs)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import numpy as np

from debrief_meet.platform.interfaces import (
    CaptureMicro,
    CaptureAudioSysteme,
    DemarrageAuto,
    MoteurTranscription,
    PressePapiers,
    RaccourcisGlobaux,
    ResultatTranscription,
    Segment,
)

logger = logging.getLogger(__name__)


class MoteurStub(MoteurTranscription):
    @property
    def acceleration(self) -> str:
        return "CPU"

    def charger_modele(self, nom_logique: str) -> None:
        logger.debug("MoteurStub: charger_modele(%s)", nom_logique)

    def _transcrire_pret(self, audio: np.ndarray, langue: str | None) -> ResultatTranscription:
        logger.debug("MoteurStub: transcrire(%d samples)", len(audio))
        return ResultatTranscription(
            texte="[stub — pas de transcription réelle]",
            langue_detectee=langue,
            segments=[Segment(0.0, 1.0, "[stub]")],
        )

    def est_telecharge(self, nom_logique: str) -> bool:
        return False

    def telecharger_modele(self, nom_logique: str, progression: Callable[[float], None] | None = None) -> None:
        logger.debug("MoteurStub: telecharger_modele(%s)", nom_logique)


class MicroStub(CaptureMicro):
    def disponible(self) -> bool:
        return True

    def demarrer(self, index_peripherique: int | None = None) -> None:
        logger.debug("MicroStub: demarrer(index=%s)", index_peripherique)

    def arreter(self) -> None:
        logger.debug("MicroStub: arreter()")

    def recuperer_echantillons(self) -> np.ndarray:
        return np.zeros(0, dtype=np.float32)


class SystemeStub(CaptureAudioSysteme):
    def disponible(self) -> bool:
        return False

    def demarrer(self) -> None:
        logger.debug("SystemeStub: demarrer()")

    def arreter(self) -> None:
        logger.debug("SystemeStub: arreter()")

    def recuperer_echantillons(self) -> np.ndarray:
        return np.zeros(0, dtype=np.float32)


class PressePapiersStub(PressePapiers):
    def __init__(self) -> None:
        self._contenu = ""

    def copier(self, texte: str) -> None:
        self._contenu = texte
        logger.debug("PressePapiersStub: copier(%d chars)", len(texte))

    def copier_fichier(self, chemin) -> None:
        logger.debug("PressePapiersStub: copier_fichier(%s)", chemin)

    def lire(self) -> str:
        return self._contenu


class DemarrageAutoStub(DemarrageAuto):
    def __init__(self) -> None:
        self._active = False

    def est_active(self) -> bool:
        return self._active

    def activer(self) -> None:
        self._active = True
        logger.debug("DemarrageAutoStub: activer()")

    def desactiver(self) -> None:
        self._active = False
        logger.debug("DemarrageAutoStub: desactiver()")


class RaccourcisStub(RaccourcisGlobaux):
    def __init__(self) -> None:
        self._enregistres: dict[str, Callable[[], None]] = {}

    def enregistrer(self, combinaison: str, callback: Callable[[], None]) -> bool:
        self._enregistres[combinaison] = callback
        logger.debug("RaccourcisStub: enregistrer(%s)", combinaison)
        return True

    def desactiver_tous(self) -> None:
        self._enregistres.clear()
        logger.debug("RaccourcisStub: desactiver_tous()")
