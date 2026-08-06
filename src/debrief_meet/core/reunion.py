from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from debrief_meet.core import mode_transcription
from debrief_meet.core.arret_threads import arreter_thread
from debrief_meet.core.audio import reechantillonner
from debrief_meet.core.fichiers import (
    EcrivainReunion,
    EnregistreurAudioReunion,
    chemin_reunion,
    chemins_audio_reunion,
    definir_duree,
)
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from debrief_meet.platform.interfaces import CaptureAudioSysteme, CaptureMicro, MoteurTranscription

if TYPE_CHECKING:
    import numpy as np
    from debrief_meet.core.aec import ProcesseurAEC
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)


class _WorkerTranche(QObject):
    # (micro, systeme, offset_s) — l'offset voyage DANS le signal : le slot n'a donc pas
    # besoin de `sender()` (qui plantait en reconstruisant le wrapper d'un worker en cours
    # de destruction à l'arrêt). Cf. crash EXC_BAD_ACCESS dans getWrapperForQObject.
    terminee = Signal(object, object, float)
    erreur = Signal(str)

    def __init__(
        self,
        moteur: MoteurTranscription,
        audio_micro: "np.ndarray",
        audio_systeme: "np.ndarray",
        sr_micro: int,
        sr_systeme: int,
        avec_systeme: bool,
        offset_s: float = 0.0,
    ) -> None:
        super().__init__()
        self._moteur = moteur
        self._audio_micro = audio_micro
        self._audio_systeme = audio_systeme
        self._sr_micro = sr_micro
        self._sr_systeme = sr_systeme
        self._avec_systeme = avec_systeme
        self._offset_s = offset_s

    @Slot()
    def transcrire(self) -> None:
        from concurrent.futures import ThreadPoolExecutor
        from debrief_meet.platform.interfaces import ResultatTranscription

        _vide_res = ResultatTranscription(texte="", langue_detectee=None)

        def _transcrire_micro() -> ResultatTranscription:
            if len(self._audio_micro) == 0:
                return _vide_res
            # Le moteur normalise et applique la porte anti-silence en interne
            # (docs/27) — le micro post-AEC, atténué, en bénéficie comme les autres.
            audio_16k = reechantillonner(self._audio_micro, self._sr_micro)
            return self._moteur.transcrire(audio_16k, None)

        def _transcrire_systeme() -> ResultatTranscription:
            if not self._avec_systeme or len(self._audio_systeme) == 0:
                return _vide_res
            audio_16k = reechantillonner(self._audio_systeme, self._sr_systeme)
            return self._moteur.transcrire(audio_16k, None)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_micro = pool.submit(_transcrire_micro)
                f_systeme = pool.submit(_transcrire_systeme)
                res_micro = f_micro.result()
                res_systeme = f_systeme.result()
            self.terminee.emit(res_micro, res_systeme, self._offset_s)
        except Exception as exc:
            self.erreur.emit(str(exc))


class OrchestrateurReunion(QObject):
    etat_visuel_change = Signal(object)
    micro_perdu = Signal(str)
    micro_retabli = Signal(str)
    # Émis à la FIN d'une réunion dont la piste micro était intégralement muette
    # (docs/44 §8.7). Déclencheur volontairement conservateur — jamais sur une tranche
    # isolée : un enregistrement entièrement silencieux ne peut pas être un faux
    # positif, alors qu'une tranche muette est banale (personne ne parle).
    micro_muet = Signal(str)
    reunion_demarree = Signal(object)  # Path du .md créé (docs/40 §8 — démarrage pré-associé)

    def __init__(
        self,
        machine: MachineEtats,
        micro: CaptureMicro,
        systeme: CaptureAudioSysteme,
        moteur: MoteurTranscription | None,   # None en édition lite (docs/44)
        config: "Config",
        delai_termine_ms: int = 500,
        surveillant: "QObject | None" = None,
        processeur_aec: "ProcesseurAEC | None" = None,
    ) -> None:
        super().__init__()
        self._machine = machine
        self._micro = micro
        self._systeme = systeme
        self._moteur = moteur
        self._config = config
        self._delai_termine_ms = delai_termine_ms
        # AEC injectée (None en tests → désactivée, aucun chargement LiveKit).
        # `_aec` = l'instance réellement utilisée pour la session en cours (ou None).
        self._processeur_aec = processeur_aec
        self._aec: "ProcesseurAEC | None" = None
        self._enregistreur: "EnregistreurAudioReunion | None" = None
        self._actif = False
        self._transcription_live = True
        self._debut: datetime | None = None
        self._ecrivain: EcrivainReunion | None = None
        self._avec_systeme = False
        self._avec_micro = True
        self._base_moi: Path | None = None
        self._worker: _WorkerTranche | None = None
        self._thread: QThread | None = None
        # Événement BlueMind pré-associé (docs/40 §8, docs/43 §5.2) : posé par l'appelant
        # (tray, démarrage F3) avant le basculement en mode réunion, consommé dans
        # `_demarrer()` pour créer le dossier déjà titré (aucun renommage pendant
        # l'enregistrement, cf. docs/43 §6.3).
        self._evenement_pre_associe = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sur_tick)
        machine.mode_change.connect(self._sur_mode_change)

        # Détection à chaud du changement de périphérique micro (Phase 3.5).
        self._surveillant = surveillant
        if surveillant is not None:
            surveillant.change.connect(self._sur_changement_peripherique)

    @Slot(object)
    def _sur_mode_change(self, mode: Mode) -> None:
        if mode == Mode.REUNION:
            self._demarrer()
        elif mode == Mode.IDLE and self._actif:
            self._arreter()

    def definir_evenement_pre_associe(self, evt) -> None:
        """Appelé par l'appelant UI (tray, F3) juste avant `machine.toggle_reunion()`
        — le dossier créé par `_demarrer()` en tiendra compte pour naître déjà titré
        (docs/43 §5.2/§6.3)."""
        self._evenement_pre_associe = evt

    def _demarrer(self) -> None:
        self._actif = True
        # Retour visuel immédiat (tray rouge) : la suite bloque le thread UI pendant
        # plusieurs secondes à froid (micro, loopback, spawn ffmpeg — mesuré 2 à 12 s
        # sur poste Windows). En cas d'échec, `_annuler_demarrage` remet REPOS.
        self.etat_visuel_change.emit(EtatVisuel.ENREGISTREMENT)
        # Chrono par étape (DEBUG) : identifie la phase lente d'un démarrage à partir
        # d'un export diagnostic, sans rien supposer de l'ordre des logs tiers.
        _t0 = time.monotonic()

        def _jalon(nom: str) -> None:
            logger.debug("Démarrage réunion — %s à +%.2fs", nom, time.monotonic() - _t0)
        # Mode distant : jamais de transcription en direct, quoi qu'en dise la config —
        # `transcription_live` garde sa valeur pour un retour en mode local (docs/45).
        # C'est le SEUL site à gater : `_transcription_live` pilote ensuite la rétention
        # forcée, le placeholder du .md, le routage du tick et le chemin d'arrêt
        # court-circuité.
        self._transcription_live = (
            mode_transcription.avec_transcription_locale()
            and bool(self._config.get("transcription_live")))
        self._debut = datetime.now()
        self._avec_micro = False
        self._avec_systeme = False
        self._micro_a_capte_du_son = False
        evt_pre_associe = self._evenement_pre_associe
        self._evenement_pre_associe = None
        try:
            titre_pre = evt_pre_associe.titre if evt_pre_associe is not None else None
            fichier = chemin_reunion(
                Path(self._config.get("dossier_reunions")), self._debut, titre_pre)
            self._ecrivain = EcrivainReunion(fichier, self._debut)
            _jalon("dossier prêt")
            self._avec_systeme = self._systeme.disponible()
            if not self._avec_systeme:
                logger.warning(
                    "Audio système indisponible au démarrage — réunion sans piste système "
                    "(helper de capture absent/non exécutable)")

            micro_index = self._config.get("micro_index")
            try:
                self._micro.demarrer(micro_index)
                self._avec_micro = True
                _jalon("micro démarré")
            except Exception as exc:
                logger.warning("Micro indisponible au démarrage (%s) — réunion sans micro", exc)
                self._avec_micro = False
                self.micro_perdu.emit(
                    "Réunion démarrée sans micro — seule l'autre partie sera enregistrée"
                )

            if self._avec_systeme:
                self._systeme.demarrer()
                _jalon("capture système démarrée")

            # AEC : active seulement si micro + système présents et activée en config.
            # Conservée aussi en mode audio-seul (nettoie le micro retenu → bénéficie à la
            # transcription différée et à la diarization). Repli sans écho si indisponible.
            self._aec = None
            if (self._processeur_aec is not None and self._avec_micro and self._avec_systeme
                    and self._config.get("aec_actif")):
                try:
                    self._processeur_aec.demarrer()
                    self._aec = self._processeur_aec
                    _jalon("AEC démarrée")
                except Exception as exc:
                    logger.warning("AEC indisponible (%s) — réunion sans annulation d'écho", exc)
                    self._aec = None

            # Rétention audio : 2 pistes 16k mono streamées à côté du .md.
            # Forcée en mode audio-seul (sinon rien à transcrire après — docs/10).
            self._enregistreur = None
            self._base_moi = None
            retention = self._config.get("retention_audio") or not self._transcription_live
            if retention and (self._avec_micro or self._avec_systeme):
                base_moi, base_sys = chemins_audio_reunion(fichier)
                # Conservé même si `_avec_micro` est False : permet à `activer_moi` de
                # brancher la piste Moi si le micro est récupéré en cours de réunion.
                self._base_moi = base_moi
                self._enregistreur = EnregistreurAudioReunion(
                    base_moi=base_moi if self._avec_micro else None,
                    base_systeme=base_sys if self._avec_systeme else None,
                )
                _jalon("écrivains audio prêts (spawn ffmpeg)")

            if self._transcription_live:
                self._ecrivain.creer(avec_systeme=self._avec_systeme, avec_micro=self._avec_micro)
            else:
                # Mode enregistrement seul : placeholder, transcription lancée plus tard.
                self._ecrivain.creer_placeholder()
            _jalon("transcription.md créé — démarrage terminé")

            self._timer.start(self._config.get("intervalle_reunion") * 1000)
            self.reunion_demarree.emit(fichier)
        except Exception as exc:
            logger.error("Démarrage de la réunion impossible (%s) — annulation", exc, exc_info=True)
            self._annuler_demarrage(str(exc))

    def _annuler_demarrage(self, motif: str) -> None:
        """Rollback : une étape de `_demarrer()` a levé après que des captures ont déjà
        démarré — on les arrête pour ne rien laisser tourner (micro/système/AEC ouverts
        sans timer pour les drainer), puis on ramène la machine à états sur IDLE."""
        self._timer.stop()
        if self._avec_micro:
            try:
                self._micro.arreter()
            except Exception:
                logger.warning("Arrêt micro après échec de démarrage", exc_info=True)
        if self._avec_systeme:
            try:
                self._systeme.arreter()
            except Exception:
                logger.warning("Arrêt capture système après échec de démarrage", exc_info=True)
        if self._aec is not None:
            try:
                self._aec.terminer()
            except Exception:
                pass
            self._aec = None
        if self._enregistreur is not None:
            try:
                self._enregistreur.terminer()
            except Exception:
                pass
            self._enregistreur = None
        self._actif = False
        self.etat_visuel_change.emit(EtatVisuel.REPOS)
        self._machine.erreur.emit(f"Impossible de démarrer la réunion : {motif}")
        self._machine.toggle_reunion()

    @Slot()
    def _sur_tick(self) -> None:
        """Tick du timer : transcription par tranche (live) ou simple capture (audio-seul)."""
        if self._transcription_live:
            self._transcrire_tranche()
        else:
            self._capturer_seulement()

    def _capturer_seulement(self) -> None:
        """Mode audio-seul : streame l'audio (AEC + rétention) sans rien transcrire."""
        self._capturer_tranche(surveiller=True)

    def _arreter(self) -> None:
        self._actif = False
        self._timer.stop()
        if self._avec_micro:
            self._micro.arreter()
        if self._avec_systeme:
            self._systeme.arreter()

        # Mode audio-seul : on streame le reste, on finalise l'audio, sans transcrire.
        if not self._transcription_live:
            self._capturer_tranche()
            self._enregistrer_duree()
            if self._enregistreur is not None:
                self._enregistreur.terminer()
                self._enregistreur = None
            self._avertir_si_micro_muet()
            self.etat_visuel_change.emit(EtatVisuel.REPOS)
            return

        self.etat_visuel_change.emit(EtatVisuel.TRANSCRIPTION)
        audio_micro, audio_systeme, sr_micro = self._capturer_tranche()
        self._avertir_si_micro_muet()
        offset_s = (datetime.now() - self._debut).total_seconds() if self._debut else 0.0
        self._enregistrer_duree()

        # Dernière tranche écrite → on finalise les WAV (en-tête).
        if self._enregistreur is not None:
            self._enregistreur.terminer()
            self._enregistreur = None

        self._lancer_worker(audio_micro, audio_systeme, sr_micro, offset_s, finale=True)

    def _avertir_si_micro_muet(self) -> None:
        """Réunion terminée sans un seul échantillon micro au-dessus du seuil → on le dit.

        Motivation (docs/44 §8.7) : une utilisatrice a enregistré plusieurs réunions
        entièrement muettes sans que rien ne l'avertisse — Windows dirigeait l'entrée
        vers un micro interne inactif pendant qu'elle portait un casque Bluetooth. Le
        `RMS=0.0000` n'existait que dans les logs, et il a fallu trois jours et un
        diagnostic pour le voir.

        Ne se déclenche que si le micro était censé fonctionner : ni quand il a été
        perdu en route (`micro_perdu` a déjà prévenu, et `_avec_micro` est retombé à
        False), ni quand il n'y en avait pas au démarrage."""
        if not self._avec_micro or self._micro_a_capte_du_son:
            return
        logger.warning("Piste micro entièrement silencieuse sur cette réunion — "
                       "périphérique d'entrée probablement inactif")
        self.micro_muet.emit(
            "Aucun son capté sur le micro — vérifiez le périphérique "
            "dans Préférences › Audio")

    def _enregistrer_duree(self) -> None:
        """Stocke la durée écoulée dans le `.md` (titre/durée de l'Historique, docs/14)."""
        if self._ecrivain is None or self._debut is None:
            return
        duree = (datetime.now() - self._debut).total_seconds()
        definir_duree(self._ecrivain.chemin, int(duree))

    def _transcrire_tranche(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        audio_micro, audio_systeme, sr_micro = self._capturer_tranche(surveiller=True)
        offset_s = (datetime.now() - self._debut).total_seconds() if self._debut else 0.0
        self._lancer_worker(audio_micro, audio_systeme, sr_micro, offset_s, finale=False)

    def _capturer_tranche(self, surveiller: bool = False) -> "tuple[np.ndarray, np.ndarray, int]":
        """Récupère les échantillons des deux pistes ; si l'AEC est active, renvoie le
        micro **nettoyé à 16 kHz** (la réf système sert à annuler l'écho). Sinon micro brut.

        Le `pousser()` AEC tourne ici (thread principal) : ~0,2 s/30 s, et l'état AEC
        n'est jamais touché par deux tranches concurrentes (transcription off-thread).

        `surveiller=True` (chemin des ticks uniquement, jamais `_arreter`) active le
        watchdog « tranche muette » : un buffer micro vide sur une tranche entière
        signifie que le flux est mort sans qu'aucun événement ne l'ait signalé
        (cf. docs/25) → tentative de reconnexion."""
        audio_micro = self._micro.recuperer_echantillons() if self._avec_micro else _vide()
        audio_systeme = self._systeme.recuperer_echantillons() if self._avec_systeme else _vide()
        if surveiller and self._actif and self._avec_micro and len(audio_micro) == 0:
            self._recuperer_micro()
        sr_micro = self._micro.taux_echantillonnage
        if self._aec is not None:
            from debrief_meet.core.aec import SR_AEC
            audio_micro = self._aec.pousser(audio_micro, audio_systeme)
            sr_micro = SR_AEC

        # Le jugement porte sur l'audio **tel qu'il part sur le disque** (donc après AEC) :
        # c'est celui-là que l'utilisateur écoutera et que Voxtral transcrira.
        if self._avec_micro and len(audio_micro):
            from debrief_meet.core.audio import SEUIL_RMS_SILENCE, rms
            if rms(audio_micro) >= SEUIL_RMS_SILENCE:
                self._micro_a_capte_du_son = True

        # Rétention : on streame les 2 pistes en 16 kHz mono (Moi = micro nettoyé).
        if self._enregistreur is not None:
            from debrief_meet.core.audio import reechantillonner
            if self._avec_micro and len(audio_micro):
                self._enregistreur.ajouter_moi(reechantillonner(audio_micro, sr_micro))
            if self._avec_systeme and len(audio_systeme):
                self._enregistreur.ajouter_systeme(
                    reechantillonner(audio_systeme, self._systeme.taux_echantillonnage))

        return audio_micro, audio_systeme, sr_micro

    def _lancer_worker(
        self,
        audio_micro: "np.ndarray",
        audio_systeme: "np.ndarray",
        sr_micro: int,
        offset_s: float,
        finale: bool,
    ) -> None:
        # Garde défensive : inatteignable (aucun tick de transcription quand
        # `_transcription_live` est False), mais convertit un AttributeError dans une app
        # livrée en simple silence.
        if self._moteur is None:
            return
        # Sérialisation : ne jamais écraser un worker encore en vol (sinon son objet C++,
        # possédé par son wrapper Python, peut être détruit pendant qu'un signal est livré
        # → crash). On attend la fin du précédent (quit() explicite + wait, comme terminer()).
        if self._thread is not None:
            self._thread.quit()
            if not arreter_thread(self._thread, 10_000, garder=(self._worker,)):
                # Thread gelé abandonné : couper ses signaux pour qu'une éventuelle fin
                # tardive n'écrive pas une tranche périmée dans l'écrivain.
                try:
                    self._worker.disconnect()
                except Exception:
                    pass

        worker = _WorkerTranche(
            moteur=self._moteur,
            audio_micro=audio_micro,
            audio_systeme=audio_systeme,
            sr_micro=sr_micro,
            sr_systeme=self._systeme.taux_echantillonnage,
            avec_systeme=self._avec_systeme,
            offset_s=offset_s,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.transcrire)
        # Méthodes nommées obligatoires : les lambdas comme slots cross-thread
        # sont détruites sur le QThread (sans GIL) → SIGSEGV dans PySide6.
        # L'offset arrive dans le signal → plus de `sender()` (cf. _WorkerTranche).
        worker.terminee.connect(self._sur_tranche_ok)
        worker.terminee.connect(thread.quit)
        worker.erreur.connect(thread.quit)

        if finale:
            worker.terminee.connect(self._sur_finale)
            worker.erreur.connect(self._sur_finale_erreur)
        else:
            worker.erreur.connect(self._sur_erreur_tranche)

        thread.finished.connect(worker.deleteLater)
        # NB : on ne deleteLater() pas le thread — `self._thread` est relu ensuite
        # (terminer(), garde de sérialisation) ; il est parenté à l'orchestrateur.
        self._worker = worker
        self._thread = thread
        thread.start()

    @Slot(str)
    def _sur_erreur_tranche(self, msg: str) -> None:
        logger.error("Tranche réunion : %s", msg)

    @Slot(object, object, float)
    def _sur_tranche_ok(self, res_micro: object, res_participants: object, offset_s: float) -> None:
        if self._ecrivain is not None:
            from debrief_meet.platform.interfaces import ResultatTranscription
            micro = res_micro if isinstance(res_micro, ResultatTranscription) else ResultatTranscription(texte=str(res_micro), langue_detectee=None)
            parts = res_participants if isinstance(res_participants, ResultatTranscription) else ResultatTranscription(texte=str(res_participants), langue_detectee=None)
            segs_moi = [(s.debut, s.texte) for s in micro.segments]
            segs_parts = [(s.debut, s.texte) for s in parts.segments]
            self._ecrivain.ajouter_tranche(micro.texte.strip(), parts.texte.strip(), offset_s, segs_moi, segs_parts)

    @Slot(object, object, float)
    def _sur_finale(self, res_micro: object, res_participants: object,
                    offset_s: float = 0.0) -> None:
        self.etat_visuel_change.emit(EtatVisuel.TERMINE)
        QTimer.singleShot(
            self._delai_termine_ms,
            lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS),
        )

    @Slot(str)
    def _sur_finale_erreur(self, msg: str) -> None:
        logger.error("Erreur tranche finale réunion : %s", msg)
        self.etat_visuel_change.emit(EtatVisuel.TERMINE)
        QTimer.singleShot(
            self._delai_termine_ms,
            lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS),
        )

    @Slot()
    def _sur_changement_peripherique(self) -> None:
        """Le périphérique d'entrée a changé pendant la réunion → reconnexion à chaud.

        On retente systématiquement (plus de comparaison via `resoudre_peripherique`,
        qui lisait une table PortAudio périmée et pouvait juger un vrai changement
        « inchangé » — cf. docs/25) : coût d'un trou de warm-up de 200 ms pour les
        événements qui ne concernent pas notre entrée, accepté."""
        if not self._actif:
            return
        self._recuperer_micro()

    def _recuperer_micro(self) -> None:
        """Tentative de reconnexion micro — appelée sur un changement de périphérique
        signalé (surveillant) ou par le watchdog « tranche muette ». Ne désarme jamais
        définitivement la surveillance : le prochain déclencheur retentera (cf. docs/25)."""
        micro_index = self._config.get("micro_index")
        if self._avec_micro:
            try:
                self._micro.redemarrer(micro_index)
                if self._aec is not None:
                    self._aec.recalibrer()
                logger.info("Micro reconnecté à chaud")
            except Exception as exc:
                logger.warning(
                    "Reconnexion micro impossible (%s) — poursuite sans micro", exc
                )
                self._avec_micro = False
                self.micro_perdu.emit(
                    "Micro perdu — seule l'autre partie sera enregistrée"
                )
        else:
            try:
                self._micro.demarrer(micro_index)
                self._avec_micro = True
                # Récupération tardive : la piste Moi n'existait pas au démarrage
                # (rien à streamer sans micro). AEC volontairement non démarrée ici
                # (limitation acceptée — pas de recalibrage à froid en cours de session).
                if self._enregistreur is not None and self._base_moi is not None:
                    self._enregistreur.activer_moi(self._base_moi)
                self.micro_retabli.emit("Micro rétabli")
                logger.info("Micro rétabli")
            except Exception as exc:
                logger.debug("Micro toujours indisponible (%s)", exc)

    def terminer(self) -> None:
        """Appelé par aboutToQuit — attend le QThread en cours avant de rendre la main."""
        self._timer.stop()
        if self._thread is not None:
            # Pas de garde `isRunning()` : cf. arreter_thread — un thread peut être en
            # cours de finalisation (DeferredDelete du worker) alors qu'isRunning() rend
            # déjà False ; on doit quand même attendre pour ne pas laisser le worker
            # toucher Shiboken en // du thread principal (SIGSEGV).
            logger.debug("OrchestrateurReunion : attente fin du thread de transcription…")
            arreter_thread(
                self._thread, 10_000,
                # tue les sous-processus MLX → débloque read() ; None en lite (pas de moteur)
                debloquer=self._moteur.terminer if self._moteur is not None else None,
                garder=(self._worker,),
            )
        if self._enregistreur is not None:
            self._enregistreur.terminer()
            self._enregistreur = None
        if self._processeur_aec is not None:
            try:
                self._processeur_aec.terminer()
            except Exception:
                pass


def _vide() -> "np.ndarray":
    import numpy as np
    return np.zeros(0, dtype=np.float32)
