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

# Les deux tâches que ce gestionnaire sait lancer. Elles partagent le même
# `_job_en_cours`, et c'est le but : une transcription Voxtral et un CR réécrivent
# tous deux `transcription.md`, les laisser tourner en parallèle sur la même réunion
# ferait courir deux uploads et deux écritures concurrentes. Un seul gestionnaire =
# exclusion mutuelle structurelle, rien à re-vérifier au point d'appel.
TACHE_CR = "cr"
TACHE_TRANSCRIPTION = "transcription"


def _resolu(md: Path | None) -> Path | None:
    """`resoudre_chemin_reunion` tolérant au None (aucun job en cours) : le dossier a pu
    être renommé pendant le job (association BlueMind, édition du titre)."""
    from debrief_meet.core.fichiers import resoudre_chemin_reunion
    return None if md is None else resoudre_chemin_reunion(md)


class _WorkerCRMistral(QObject):
    """Exécute le pipeline Mistral dans un QThread. Ne lève jamais.

    `tache` choisit le point d'entrée : `TACHE_CR` (rédaction, transcription Voxtral
    incluse si besoin) ou `TACHE_TRANSCRIPTION` (Voxtral seul, sans CR)."""

    terminee = Signal(object)   # Path produit (CR.md, ou transcription.md réécrit)
    erreur = Signal(str)

    def __init__(self, chemin_md: Path, config: "Config", prompt: str | None = None,
                 tache: str = TACHE_CR) -> None:
        super().__init__()
        self._md = chemin_md
        self._config = config
        self._prompt = prompt
        self._tache = tache

    @Slot()
    def executer(self) -> None:
        try:
            from debrief_meet.core.mistral import pipeline

            if self._tache == TACHE_TRANSCRIPTION:
                sortie = pipeline.transcrire_reunion(self._md, self._config)
            else:
                sortie = pipeline.generer_cr_reunion(self._md, self._config, prompt=self._prompt)
            self.terminee.emit(sortie)
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self.erreur.emit(str(exc))


class GestionnaireCRMistral(QObject):
    """Orchestre les jobs de génération de CR Mistral en arrière-plan (un seul à la fois).

    Signaux : `demarre(md)`, `termine(md, sortie)`, `echoue(md, message)` — `md` est le
    `.md` source de la réunion. La fenêtre Historique s'y connecte pour son affichage."""

    demarre = Signal(object)            # chemin_md (Path)
    termine = Signal(object, object)    # chemin_md, sortie (Path) — tâche CR
    echoue = Signal(object, str)        # chemin_md, message — tâche CR
    # Paire dédiée à la transcription seule, plutôt qu'un 3ᵉ argument sur `termine` :
    # les deux tâches n'ont ni le même résultat à annoncer (« CR généré » vs
    # « Transcription terminée ») ni le même fichier à ouvrir, et les connexions
    # existantes restent intactes.
    transcription_terminee = Signal(object, object)   # chemin_md, transcription.md
    transcription_echouee = Signal(object, str)       # chemin_md, message

    def __init__(self, config: "Config", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._thread: QThread | None = None
        self._worker: _WorkerCRMistral | None = None
        self._job_en_cours: Path | None = None
        self._tache: str | None = None

    # ── État (lu par la fenêtre) ───────────────────────────────────────────────

    def disponible(self) -> bool:
        """Vrai si une clé API Mistral est configurée (§9.2)."""
        from debrief_meet.core.mistral import pipeline
        return pipeline.disponible(self._config)

    def job_en_cours(self) -> Path | None:
        """`.md` en cours de génération, ou None si aucun job."""
        return self._job_en_cours

    def tache_en_cours(self) -> str | None:
        """`TACHE_CR` / `TACHE_TRANSCRIPTION` du job courant, None si aucun job.

        Lu par l'Historique pour l'icône de la ligne : le même gestionnaire couvre
        deux opérations, qui ne se peignent pas pareil."""
        return self._tache

    # ── Lancement ──────────────────────────────────────────────────────────────

    def lancer(self, chemin_md: Path, prompt: str | None = None,
               tache: str = TACHE_CR) -> bool:
        """Démarre une génération de CR. False si indisponible ou job déjà en cours.

        `prompt` : contenu de prompt **ponctuel** (choisi via la flèche du bouton
        « Générer le CR ») — n'affecte que ce job, le prompt actif de la config
        reste inchangé. None → prompt actif (comportement par défaut).

        `tache` : `TACHE_CR` (défaut) ou `TACHE_TRANSCRIPTION` (Voxtral seul, `prompt`
        alors ignoré) — cf. `lancer_transcription`."""
        if not self.disponible() or self._job_en_cours is not None:
            return False

        thread = QThread(self)
        worker = _WorkerCRMistral(chemin_md, self._config, prompt, tache)
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
        self._tache = tache
        thread.start()
        self.demarre.emit(chemin_md)
        return True

    def lancer_transcription(self, chemin_md: Path) -> bool:
        """Démarre une transcription distante SEULE (aucun CR). Mêmes refus que
        `lancer` : False si Mistral n'est pas configuré ou si un job tourne déjà —
        CR compris, les deux tâches se disputant `transcription.md`."""
        return self.lancer(chemin_md, tache=TACHE_TRANSCRIPTION)

    # `_job_en_cours`/`_tache` sont remis à None AVANT l'émission (la vue interroge le
    # gestionnaire depuis le handler : elle doit y voir « plus de job »), donc la tâche
    # est capturée dans une locale pour choisir la paire de signaux.

    @Slot(object)
    def _sur_terminee(self, sortie: object) -> None:
        md = _resolu(self._job_en_cours)
        tache = self._tache
        self._job_en_cours = None
        self._tache = None
        if tache == TACHE_TRANSCRIPTION:
            logger.info("Transcription Mistral terminée : %s", sortie)
            self.transcription_terminee.emit(md, Path(str(sortie)))
            return
        logger.info("CR Mistral terminé : %s", sortie)
        self.termine.emit(md, Path(str(sortie)))

    @Slot(str)
    def _sur_erreur(self, message: str) -> None:
        md = _resolu(self._job_en_cours)
        tache = self._tache
        self._job_en_cours = None
        self._tache = None
        if tache == TACHE_TRANSCRIPTION:
            logger.error("Transcription Mistral échouée (%s) : %s", md, message)
            self.transcription_echouee.emit(md, message)
            return
        logger.error("CR Mistral échoué (%s) : %s", md, message)
        self.echoue.emit(md, message)

    def terminer(self) -> None:
        """Attend la fin du job courant (appelé par aboutToQuit)."""
        if self._thread is not None and self._thread.isRunning():
            logger.debug("GestionnaireCRMistral : attente fin du job…")
            arreter_thread(self._thread, 30_000, garder=(self._worker,))
