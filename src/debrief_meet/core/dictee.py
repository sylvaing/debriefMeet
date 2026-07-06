from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from debrief_meet.core.arret_threads import arreter_thread
from debrief_meet.core.audio import reechantillonner
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from debrief_meet.platform.interfaces import CaptureMicro, MoteurTranscription, PressePapiers

if TYPE_CHECKING:
    import numpy as np
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)


class _WorkerTranscription(QObject):
    terminee = Signal(str)
    erreur = Signal(str)

    def __init__(self, moteur: MoteurTranscription, audio_16k: "np.ndarray") -> None:
        super().__init__()
        self._moteur = moteur
        self._audio = audio_16k

    @Slot()
    def transcrire(self) -> None:
        try:
            resultat = self._moteur.transcrire(self._audio, None)
            self.terminee.emit(resultat.texte)
        except Exception as exc:
            self.erreur.emit(str(exc))


class OrchestrateurDictee(QObject):
    etat_visuel_change = Signal(object)
    rien_entendu = Signal(str)   # message à notifier — rien n'a été copié

    def __init__(
        self,
        machine: MachineEtats,
        micro: CaptureMicro,
        moteur: MoteurTranscription,
        presse_papiers: PressePapiers,
        config: "Config",
        delai_termine_ms: int = 2000,
        delai_erreur_ms: int = 3000,
    ) -> None:
        super().__init__()
        self._machine = machine
        self._micro = micro
        self._moteur = moteur
        self._presse_papiers = presse_papiers
        self._config = config
        self._delai_termine_ms = delai_termine_ms
        self._delai_erreur_ms = delai_erreur_ms
        self._enregistrement_actif = False
        self._worker: _WorkerTranscription | None = None
        self._thread: QThread | None = None

        machine.mode_change.connect(self._sur_mode_change)

    @Slot(object)
    def _sur_mode_change(self, mode: Mode) -> None:
        if mode == Mode.DICTEE:
            self._demarrer()
        elif mode == Mode.IDLE and self._enregistrement_actif:
            self._arreter_et_transcrire()

    def _demarrer(self) -> None:
        try:
            self._micro.demarrer(self._config.get("micro_index"))
        except Exception as exc:
            logger.error("Dictée : démarrage micro impossible (%s)", exc)
            self.rien_entendu.emit("Micro indisponible — dictée annulée.")
            self.etat_visuel_change.emit(EtatVisuel.ERREUR)
            QTimer.singleShot(self._delai_erreur_ms,
                              lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS))
            # Revenir à IDLE — en différé : on est DANS le handler de mode_change,
            # re-toggler synchronement ré-entrerait dans l'émission du signal en cours.
            QTimer.singleShot(0, self._machine.toggle_dictee)
            return
        self._enregistrement_actif = True
        self.etat_visuel_change.emit(EtatVisuel.ENREGISTREMENT)

    def _arreter_et_transcrire(self) -> None:
        self._enregistrement_actif = False
        self._micro.arreter()
        audio = self._micro.recuperer_echantillons()

        if audio.size == 0:
            logger.info("Dictée : aucun échantillon capté — rien à transcrire")
            self.rien_entendu.emit("Aucun son capté — vérifiez le micro.")
            self.etat_visuel_change.emit(EtatVisuel.ERREUR)
            QTimer.singleShot(self._delai_erreur_ms,
                              lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS))
            return

        audio_16k = reechantillonner(audio, self._micro.taux_echantillonnage)
        self.etat_visuel_change.emit(EtatVisuel.TRANSCRIPTION)
        self._lancer_worker(audio_16k)

    def _lancer_worker(self, audio: "np.ndarray") -> None:
        thread = QThread(self)
        worker = _WorkerTranscription(self._moteur, audio)
        worker.moveToThread(thread)

        thread.started.connect(worker.transcrire)
        worker.terminee.connect(self._sur_ok)
        worker.erreur.connect(self._sur_erreur)
        worker.terminee.connect(thread.quit)
        worker.erreur.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)

        self._worker = worker
        self._thread = thread
        thread.start()

    @Slot(str)
    def _sur_ok(self, texte: str) -> None:
        if not texte.strip():
            logger.info("Dictée : transcription vide (silence ou parole inaudible) — rien copié")
            self.rien_entendu.emit("Aucune parole détectée — rien n'a été copié.")
            self.etat_visuel_change.emit(EtatVisuel.ERREUR)
            QTimer.singleShot(self._delai_erreur_ms,
                              lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS))
            return
        self._presse_papiers.copier(texte.strip())
        self.etat_visuel_change.emit(EtatVisuel.TERMINE)
        QTimer.singleShot(
            self._delai_termine_ms,
            lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS),
        )

    @Slot(str)
    def _sur_erreur(self, msg: str) -> None:
        logger.error("Erreur de transcription : %s", msg)
        self.etat_visuel_change.emit(EtatVisuel.ERREUR)
        QTimer.singleShot(
            self._delai_erreur_ms,
            lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS),
        )

    def terminer(self) -> None:
        """Appelé par aboutToQuit — attend le QThread en cours avant de rendre la main."""
        if self._thread is not None:
            # Pas de garde `isRunning()` : un thread en cours de finalisation
            # (QThreadPrivate::finish qui vide le deleteLater du worker) rend déjà
            # isRunning()=False mais touche encore Shiboken côté thread worker —
            # on doit l'attendre pour éviter un SIGSEGV concurrent (cf. arret_threads).
            logger.debug("OrchestrateurDictee : attente fin du thread de transcription…")
            arreter_thread(self._thread, 10_000,
                           debloquer=self._moteur.terminer, garder=(self._worker,))
