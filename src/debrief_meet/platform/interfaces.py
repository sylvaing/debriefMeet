from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np


@dataclass
class Segment:
    debut: float
    fin: float
    texte: str


@dataclass
class ResultatTranscription:
    texte: str
    langue_detectee: str | None
    segments: list[Segment] = field(default_factory=list)


class MoteurTranscription(ABC):
    @property
    @abstractmethod
    def acceleration(self) -> str:
        """Retourne "Metal" | "CUDA" | "Vulkan" | "CPU"."""

    @abstractmethod
    def charger_modele(self, nom_logique: str) -> None: ...

    def transcrire(self, audio: "np.ndarray", langue: str | None) -> ResultatTranscription:
        """Transcrit `audio` (float32 mono 16 kHz). Applique la préparation centrale
        (normalisation + porte anti-silence, docs/27) puis délègue au backend.
        Les appelants n'ont PLUS à normaliser eux-mêmes."""
        from debrief_meet.core.audio import preparer_asr  # paresseux : numpy/scipy

        pret = preparer_asr(audio)
        if pret is None:
            return ResultatTranscription(texte="", langue_detectee=langue, segments=[])
        return self._transcrire_pret(pret, langue)

    @abstractmethod
    def _transcrire_pret(self, audio: "np.ndarray", langue: str | None) -> ResultatTranscription:
        """Transcription effective d'un audio déjà normalisé et non silencieux."""

    @abstractmethod
    def est_telecharge(self, nom_logique: str) -> bool: ...

    @abstractmethod
    def telecharger_modele(self, nom_logique: str, progression: Callable[[float], None] | None = None) -> None: ...

    def recharger_modele(self, nom_logique: str) -> None:
        """Bascule à chaud vers un autre modèle, **sans redémarrer l'app** : arrête les
        workers du modèle courant puis les relance avec le nouveau. À appeler hors
        transcription (ex. validation des Préférences). Défaut : terminer + charger."""
        self.terminer()
        self.charger_modele(nom_logique)

    def terminer(self) -> None:
        """Nettoyage en fin d'application (arrêt processus, etc.). No-op par défaut."""


class CaptureMicro(ABC):
    @property
    def taux_echantillonnage(self) -> int:
        """Taux d'échantillonnage rendu par `recuperer_echantillons()` (Hz).

        Défaut : 16 000 (taux canonique — Whisper, AEC et WAV retenu convergent
        tous vers ce taux, cf. docs/20). Une implémentation qui capture à un taux
        natif variable (ex. `CaptureMicroSounddevice`) rééchantillonne en interne
        et retourne toujours cette constante."""
        return 16_000

    @abstractmethod
    def disponible(self) -> bool: ...

    @abstractmethod
    def demarrer(self, index_peripherique: int | None = None) -> None: ...

    @abstractmethod
    def arreter(self) -> None: ...

    @abstractmethod
    def recuperer_echantillons(self) -> "np.ndarray": ...

    def redemarrer(self, index_peripherique: int | None = None) -> None:
        """Reconnecte le flux sur un nouveau périphérique SANS vider le buffer.

        Utilisé pour le redémarrage à chaud quand le périphérique d'entrée
        change en cours de capture (ex. retrait des AirPods). No-op par défaut
        (les plate-formes qui ne le gèrent pas encore l'héritent telle quelle)."""

    def resoudre_peripherique(self, index_peripherique: int | None) -> object:
        """Identifiant stable du périphérique qui serait effectivement utilisé pour cet
        index (ex. nom du périphérique par défaut résolu si `index_peripherique` est
        None). Sert à détecter un changement *réel* avant de payer le coût d'un
        redémarrage à chaud (cf. docs/20 §6 étape B). Défaut : renvoie l'index tel
        quel (pas de résolution — toute comparaison avant/après sera donc stable
        tant que la config ne change pas)."""
        return index_peripherique

    def terminer(self) -> None:
        """Nettoyage en fin d'application. No-op par défaut."""


class CaptureAudioSysteme(ABC):
    @property
    def taux_echantillonnage(self) -> int:
        """Taux d'échantillonnage du périphérique (Hz). Défaut : 48 000."""
        return 48_000

    @abstractmethod
    def disponible(self) -> bool: ...

    @abstractmethod
    def demarrer(self) -> None: ...

    @abstractmethod
    def arreter(self) -> None: ...

    @abstractmethod
    def recuperer_echantillons(self) -> "np.ndarray": ...

    def terminer(self) -> None:
        """Nettoyage en fin d'application. No-op par défaut."""


class PressePapiers(ABC):
    @abstractmethod
    def copier(self, texte: str) -> None: ...

    @abstractmethod
    def lire(self) -> str: ...


class DemarrageAuto(ABC):
    @abstractmethod
    def est_active(self) -> bool: ...

    @abstractmethod
    def activer(self) -> None: ...

    @abstractmethod
    def desactiver(self) -> None: ...


class RaccourcisGlobaux(ABC):
    """Raccourcis clavier système (capturés même quand l'app n'a pas le focus)."""

    @abstractmethod
    def enregistrer(self, combinaison: str, callback: Callable[[], None]) -> bool:
        """Enregistre `combinaison` (format portable QKeySequence, ex. "Meta+Alt+Ctrl+D").
        False si l'enregistrement échoue (combinaison déjà prise par une autre app,
        conversion impossible). Le callback est invoqué sur le thread principal Qt."""

    @abstractmethod
    def desactiver_tous(self) -> None: ...
