"""Génération de CR Mistral en arrière-plan, **persistant** (hors fenêtre Historique).

Miroir de `ui/gestionnaire_diarization.py` : la génération (upload éventuel + rédaction)
peut durer plusieurs minutes, ne doit **pas** appartenir à la fenêtre Historique (sinon
la fermer tuerait le `QThread`). Ce gestionnaire vit dans `__main__`, survit à
l'ouverture/fermeture de la fenêtre, n'exécute **qu'un seul job à la fois**.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, Signal, Slot

from debrief_meet.core.arret_threads import arreter_thread

if TYPE_CHECKING:
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)


def _resolu(md: Path | None) -> Path | None:
    """`resoudre_chemin_reunion` tolérant au None (aucun job en cours) : le dossier a pu
    être renommé pendant le job (association BlueMind, édition du titre)."""
    from debrief_meet.core.fichiers import resoudre_chemin_reunion
    return None if md is None else resoudre_chemin_reunion(md)


class _WorkerCRMistral(QObject):
    """Exécute `pipeline.generer_cr_reunion` dans un QThread. Ne lève jamais."""

    terminee = Signal(object)   # Path du <stem>_CR.md
    erreur = Signal(str)

    def __init__(self, chemin_md: Path, config: "Config", prompt: str | None = None) -> None:
        super().__init__()
        self._md = chemin_md
        self._config = config
        self._prompt = prompt

    @Slot()
    def executer(self) -> None:
        try:
            from debrief_meet.core.mistral import pipeline

            sortie = pipeline.generer_cr_reunion(self._md, self._config, prompt=self._prompt)
            self.terminee.emit(sortie)
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self.erreur.emit(str(exc))


class GestionnaireCRMistral(QObject):
    """Orchestre les jobs de génération de CR Mistral en arrière-plan (un seul à la fois).

    Signaux : `demarre(md)`, `termine(md, sortie)`, `echoue(md, message)` — `md` est le
    `.md` source de la réunion. La fenêtre Historique s'y connecte pour son affichage."""

    demarre = Signal(object)            # chemin_md (Path)
    termine = Signal(object, object)    # chemin_md, sortie (Path)
    echoue = Signal(object, str)        # chemin_md, message

    def __init__(self, config: "Config", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._thread: QThread | None = None
        self._worker: _WorkerCRMistral | None = None
        self._job_en_cours: Path | None = None

    # ── État (lu par la fenêtre) ───────────────────────────────────────────────

    def disponible(self) -> bool:
        """Vrai si une clé API Mistral est configurée (§9.2)."""
        from debrief_meet.core.mistral import pipeline
        return pipeline.disponible(self._config)

    def job_en_cours(self) -> Path | None:
        """`.md` en cours de génération, ou None si aucun job."""
        return self._job_en_cours

    # ── Lancement ──────────────────────────────────────────────────────────────

    def lancer(self, chemin_md: Path, prompt: str | None = None) -> bool:
        """Démarre une génération de CR. False si indisponible ou job déjà en cours.

        `prompt` : contenu de prompt **ponctuel** (choisi via la flèche du bouton
        « Générer le CR ») — n'affecte que ce job, le prompt actif de la config
        reste inchangé. None → prompt actif (comportement par défaut)."""
        if not self.disponible() or self._job_en_cours is not None:
            return False

        thread = QThread(self)
        worker = _WorkerCRMistral(chemin_md, self._config, prompt)
        worker.moveToThread(thread)
        thread.started.connect(worker.executer)
        worker.terminee.connect(self._sur_terminee)
        worker.erreur.connect(self._sur_erreur)
        worker.terminee.connect(thread.quit)
        worker.erreur.connect(thread.quit)
        # PAS de `thread.finished.connect(worker.deleteLater)` ici : même précaution
        # que `gestionnaire_diarization.py` (access violation Windows évitée en gardant
        # les références Python, remplacées au job suivant plutôt que deleteLater
        # depuis le thread mourant).

        self._thread = thread
        self._worker = worker
        self._job_en_cours = chemin_md
        thread.start()
        self.demarre.emit(chemin_md)
        return True

    @Slot(object)
    def _sur_terminee(self, sortie: object) -> None:
        md = _resolu(self._job_en_cours)
        self._job_en_cours = None
        logger.info("CR Mistral terminé : %s", sortie)
        self.termine.emit(md, Path(str(sortie)))

    @Slot(str)
    def _sur_erreur(self, message: str) -> None:
        md = _resolu(self._job_en_cours)
        self._job_en_cours = None
        logger.error("CR Mistral échoué (%s) : %s", md, message)
        self.echoue.emit(md, message)

    def terminer(self) -> None:
        """Attend la fin du job courant (appelé par aboutToQuit)."""
        if self._thread is not None and self._thread.isRunning():
            logger.debug("GestionnaireCRMistral : attente fin du job…")
            arreter_thread(self._thread, 30_000, garder=(self._worker,))
