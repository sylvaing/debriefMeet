"""Gestionnaire de diarization en arrière-plan, **persistant** (hors fenêtre Historique).

La passe finale de diarization (re-transcription + pyannote) dure plusieurs minutes. Elle
ne doit **pas** appartenir à la fenêtre Historique (sinon fermer la fenêtre tuerait le
`QThread`). Ce gestionnaire vit dans `__main__`, survit à l'ouverture/fermeture de la
fenêtre, n'exécute **qu'un seul job à la fois**, et expose son état pour que la fenêtre
restaure l'affichage « en cours » à la réouverture. Cf. docs/09-refonte-historique.md §5.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from debrief_meet.core.arret_threads import arreter_thread
from debrief_meet.platform.interfaces import MoteurTranscription

if False:  # TYPE_CHECKING léger sans import circulaire
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)


class _WorkerDiarization(QObject):
    """Exécute `generer_locuteurs` dans un QThread. Ne lève jamais (erreurs remontées)."""

    terminee = Signal(object)   # Path du <stem>_locuteurs.md
    erreur = Signal(str)

    def __init__(self, chemin_md: Path, moteur_transcription: MoteurTranscription,
                 langue: str | None) -> None:
        super().__init__()
        self._md = chemin_md
        self._moteur_transcription = moteur_transcription
        self._langue = langue

    @Slot()
    def executer(self) -> None:
        try:
            from debrief_meet.core import diarization

            sortie = diarization.generer_locuteurs(
                self._md, self._moteur_transcription,
                diarization.DiarizationPyannote(), langue=self._langue)
            self.terminee.emit(sortie)
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self.erreur.emit(str(exc))


class _WorkerTranscription(QObject):
    """Exécute `transcrire_reunion` (transcription différée) dans un QThread."""

    terminee = Signal(object)   # Path du .md (ré)écrit
    erreur = Signal(str)

    def __init__(self, chemin_md: Path, moteur_transcription: MoteurTranscription,
                 langue: str | None) -> None:
        super().__init__()
        self._md = chemin_md
        self._moteur_transcription = moteur_transcription
        self._langue = langue

    @Slot()
    def executer(self) -> None:
        try:
            from debrief_meet.core import transcription_differee

            sortie = transcription_differee.transcrire_reunion(
                self._md, self._moteur_transcription, langue=self._langue)
            self.terminee.emit(sortie)
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self.erreur.emit(str(exc))


class GestionnaireDiarization(QObject):
    """Orchestre les jobs de diarization en arrière-plan (un seul à la fois).

    Signaux : `demarre(md)`, `termine(md, sortie)`, `echoue(md, message)` — `md` est le
    `.md` source de la réunion. La fenêtre Historique s'y connecte pour son affichage."""

    demarre = Signal(object)            # chemin_md (Path)
    termine = Signal(object, object)    # chemin_md, sortie (Path)
    echoue = Signal(object, str)        # chemin_md, message

    def __init__(self, moteur_transcription: MoteurTranscription | None,
                 config: "Config", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._moteur = moteur_transcription
        self._config = config
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._job_en_cours: Path | None = None
        self._type_job: str | None = None   # "transcription" | "diarization"
        self._dernier_termine: Path | None = None

    # ── État (lu par la fenêtre) ───────────────────────────────────────────────

    def disponible(self) -> bool:
        """Vrai si un moteur de transcription est présent (génération possible)."""
        return self._moteur is not None

    def diarization_prete(self) -> bool:
        """Vrai si la **diarization** (locuteurs) est lançable : moteur présent **et**
        modèle pyannote téléchargé/configuré (cf. docs/13). La transcription différée,
        elle, ne dépend que de `disponible()`."""
        if self._moteur is None:
            return False
        from debrief_meet.core import diarization
        return diarization.configuree()

    def job_en_cours(self) -> Path | None:
        """`.md` en cours de génération, ou None si aucun job."""
        return self._job_en_cours

    def type_job_en_cours(self) -> str | None:
        """Type du job en cours : « transcription », « diarization », ou None."""
        return self._type_job

    def dernier_termine(self) -> Path | None:
        """`.md` du dernier job terminé avec succès (cible du clic sur notification)."""
        return self._dernier_termine

    # ── Lancement ──────────────────────────────────────────────────────────────

    def lancer(self, chemin_md: Path) -> bool:
        """Démarre une diarization. False si indisponible ou si un job tourne déjà."""
        worker = _WorkerDiarization(chemin_md, self._moteur, self._config.get("langue")) \
            if self._moteur is not None else None
        return self._demarrer(chemin_md, worker, "diarization")

    def lancer_transcription(self, chemin_md: Path) -> bool:
        """Démarre une transcription différée. False si indisponible ou job déjà en cours."""
        worker = _WorkerTranscription(chemin_md, self._moteur, self._config.get("langue")) \
            if self._moteur is not None else None
        return self._demarrer(chemin_md, worker, "transcription")

    def _demarrer(self, chemin_md: Path, worker: QObject | None, type_job: str) -> bool:
        if worker is None or self._job_en_cours is not None:
            return False

        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.executer)
        worker.terminee.connect(self._sur_terminee)
        worker.erreur.connect(self._sur_erreur)
        worker.terminee.connect(thread.quit)
        worker.erreur.connect(thread.quit)
        # PAS de `thread.finished.connect(worker.deleteLater)` ici : le deferred delete
        # serait traité DANS le thread mourant (connexion directe — le worker y vit),
        # et cette destruction native concurrente au thread principal provoque une
        # access violation intermittente sur Windows (VM, 2026-07-03/04). On garde les
        # références Python (`self._worker`/`self._thread`) : le worker, redevenu
        # « threadless » après la fin du thread, est détruit sans danger depuis le
        # thread principal quand la référence est remplacée au job suivant.

        self._thread = thread
        self._worker = worker
        self._job_en_cours = chemin_md
        self._type_job = type_job
        thread.start()
        self.demarre.emit(chemin_md)
        return True

    @Slot(object)
    def _sur_terminee(self, sortie: object) -> None:
        md = self._job_en_cours
        type_job = self._type_job
        self._job_en_cours = None
        self._type_job = None
        self._dernier_termine = md
        logger.info("Job %s terminé : %s", type_job, sortie)
        self.termine.emit(md, Path(str(sortie)))

    @Slot(str)
    def _sur_erreur(self, message: str) -> None:
        md = self._job_en_cours
        type_job = self._type_job
        self._job_en_cours = None
        self._type_job = None
        logger.error("Job %s échoué (%s) : %s", type_job, md, message)
        self.echoue.emit(md, message)

    def terminer(self) -> None:
        """Attend la fin du job courant (appelé par aboutToQuit, avant l'arrêt moteur)."""
        if self._thread is not None and self._thread.isRunning():
            logger.debug("GestionnaireDiarization : attente fin du job…")
            arreter_thread(self._thread, 30_000,
                           debloquer=(self._moteur.terminer if self._moteur is not None else None),
                           garder=(self._worker,))
