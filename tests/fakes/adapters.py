"""Faux adaptateurs riches pour les tests — enregistrent les appels et sont configurables."""
from __future__ import annotations

from typing import Callable

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


class MoteurFake(MoteurTranscription):
    def __init__(self) -> None:
        self.modele_charge: str | None = None
        self.appels_transcrire: list[tuple[np.ndarray, str | None]] = []
        self.resultat_fixe = ResultatTranscription(
            texte="transcription de test",
            langue_detectee="fr",
            segments=[Segment(0.0, 1.0, "transcription de test")],
        )
        self.modeles_telecharges: set[str] = set()
        self.lever_erreur: Exception | None = None

    @property
    def acceleration(self) -> str:
        return "CPU"

    def charger_modele(self, nom_logique: str) -> None:
        self.modele_charge = nom_logique

    def _transcrire_pret(self, audio: np.ndarray, langue: str | None) -> ResultatTranscription:
        if self.lever_erreur:
            raise self.lever_erreur
        self.appels_transcrire.append((audio, langue))
        return self.resultat_fixe

    def est_telecharge(self, nom_logique: str) -> bool:
        return nom_logique in self.modeles_telecharges

    def telecharger_modele(self, nom_logique: str, progression: Callable[[float], None] | None = None) -> None:
        self.modeles_telecharges.add(nom_logique)
        if progression:
            progression(1.0)


class MicroFake(CaptureMicro):
    def __init__(
        self,
        echantillons: np.ndarray | None = None,
        lever_au_demarrage: Exception | None = None,
        changement_reel: bool = True,
    ) -> None:
        self.en_cours = False
        self.index_utilise: int | None = None
        self.appels_demarrer = 0
        self.appels_arreter = 0
        self.appels_redemarrer = 0
        self.index_redemarrage: list[int | None] = []
        self.lever_au_redemarrage: Exception | None = None
        self.lever_au_demarrage = lever_au_demarrage
        self._echantillons = echantillons if echantillons is not None else np.zeros(1600, dtype=np.float32)
        # `changement_reel=True` (défaut) : chaque résolution renvoie une valeur inédite,
        # donc `_sur_changement_peripherique` considère toujours qu'un changement a eu
        # lieu (comportement historique des tests). `changement_reel=False` simule un
        # événement en double / sans effet réel (même périphérique résolu deux fois).
        self._changement_reel = changement_reel
        self.appels_resoudre = 0

    def disponible(self) -> bool:
        return True

    def demarrer(self, index_peripherique: int | None = None) -> None:
        self.appels_demarrer += 1
        if self.lever_au_demarrage is not None:
            raise self.lever_au_demarrage
        self.en_cours = True
        self.index_utilise = index_peripherique

    def redemarrer(self, index_peripherique: int | None = None) -> None:
        self.appels_redemarrer += 1
        self.index_redemarrage.append(index_peripherique)
        if self.lever_au_redemarrage is not None:
            raise self.lever_au_redemarrage
        self.en_cours = True
        self.index_utilise = index_peripherique

    def arreter(self) -> None:
        self.en_cours = False
        self.appels_arreter += 1

    def resoudre_peripherique(self, index_peripherique: int | None) -> object:
        self.appels_resoudre += 1
        if not self._changement_reel:
            return "meme-peripherique"
        return self.appels_resoudre  # valeur inédite à chaque appel → "changé" par défaut

    def recuperer_echantillons(self) -> np.ndarray:
        return self._echantillons.copy()


class SystemeFake(CaptureAudioSysteme):
    def __init__(
        self,
        disponible: bool = True,
        echantillons: np.ndarray | None = None,
        lever_au_demarrage: Exception | None = None,
    ) -> None:
        self._disponible = disponible
        self.en_cours = False
        self.appels_demarrer = 0
        self.appels_arreter = 0
        self.lever_au_demarrage = lever_au_demarrage
        self._echantillons = echantillons if echantillons is not None else np.zeros(1600, dtype=np.float32)

    def disponible(self) -> bool:
        return self._disponible

    def demarrer(self) -> None:
        self.appels_demarrer += 1
        if self.lever_au_demarrage is not None:
            raise self.lever_au_demarrage
        self.en_cours = True

    def arreter(self) -> None:
        self.en_cours = False
        self.appels_arreter += 1

    def recuperer_echantillons(self) -> np.ndarray:
        return self._echantillons.copy()


class PressePapiersFake(PressePapiers):
    def __init__(self) -> None:
        self.historique: list[str] = []
        self.fichiers_copies: list = []

    def copier(self, texte: str) -> None:
        self.historique.append(texte)

    def copier_fichier(self, chemin) -> None:
        self.fichiers_copies.append(chemin)

    def lire(self) -> str:
        return self.historique[-1] if self.historique else ""

    @property
    def dernier(self) -> str:
        return self.lire()


class DemarrageAutoFake(DemarrageAuto):
    def __init__(self) -> None:
        self._active = False
        self.appels_activer = 0
        self.appels_desactiver = 0

    def est_active(self) -> bool:
        return self._active

    def activer(self) -> None:
        self._active = True
        self.appels_activer += 1

    def desactiver(self) -> None:
        self._active = False
        self.appels_desactiver += 1


class RaccourcisFake(RaccourcisGlobaux):
    def __init__(self, refuser: set[str] | None = None) -> None:
        self.enregistres: dict[str, Callable[[], None]] = {}
        self.appels_desactiver_tous = 0
        self._refuser = refuser or set()

    def enregistrer(self, combinaison: str, callback: Callable[[], None]) -> bool:
        if combinaison in self._refuser:
            return False
        self.enregistres[combinaison] = callback
        return True

    def desactiver_tous(self) -> None:
        self.appels_desactiver_tous += 1
        self.enregistres.clear()
