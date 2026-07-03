"""Capture audio système Windows — loopback WASAPI via `soundcard` (docs/34 §2).

`sounddevice`/PortAudio ne sait pas faire le loopback WASAPI (CLAUDE.md) — on utilise
`soundcard`, qui l'expose via `include_loopback=True` sur le microphone miroir du
haut-parleur par défaut.

Piège validé au benchmark : toujours capturer en **stéréo** puis downmixer
(`bloc.mean(axis=1)`) — `soundcard` rend du bruit si on demande 1 canal explicite en
loopback WASAPI.

`soundcard` exige `CoInitialize` dans le thread qui touche WASAPI : tous les appels
`soundcard` (énumération comprise) se font **dans le thread de capture**, jamais
dans le thread Qt — reprend le motif buffer/verrou de `micro_sounddevice.py`.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from debrief_meet.platform.interfaces import CaptureAudioSysteme

logger = logging.getLogger(__name__)

TAUX = 48_000
CANAUX = 2
TAILLE_BLOC = 1024

_INTERVALLE_SURVEILLANCE_S = 2.0   # fréquence de vérification du haut-parleur par défaut (§2.3)
_ECHECS_MAX_AVANT_SILENCE = 3      # cf. docs/33 E-3 : jamais de crash de réunion pour le loopback


class CaptureAudioSystemeWasapi(CaptureAudioSysteme):
    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._verrou = threading.Lock()
        self._thread: threading.Thread | None = None
        self._arret = threading.Event()
        self._demarre = False
        self._silence = False

    @property
    def taux_echantillonnage(self) -> int:
        return TAUX

    def disponible(self) -> bool:
        try:
            import soundcard as sc
            return sc.default_speaker() is not None
        except Exception:
            return False

    def demarrer(self) -> None:
        """Idempotent (E-2, docs/33 §2.3) : un second appel sans `arreter()` est un
        no-op loggé, jamais un second flux ouvert."""
        if self._demarre:
            logger.warning("demarrer() appelé alors qu'une capture système était déjà en cours — ignoré")
            return
        self._demarre = True
        self._silence = False
        self._arret.clear()
        with self._verrou:
            self._buffer = []
        self._thread = threading.Thread(
            target=self._boucle_capture, daemon=True, name="capture-systeme"
        )
        self._thread.start()

    def arreter(self) -> None:
        """Positionne l'arrêt et joint le thread (E-3) — timeout 5 s, échec loggé
        en WARNING plutôt que de bloquer indéfiniment la fermeture de l'app."""
        if not self._demarre:
            return
        self._demarre = False
        self._arret.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning("Capture système : thread non joint dans les temps (5 s)")

    def terminer(self) -> None:
        self.arreter()

    def recuperer_echantillons(self) -> np.ndarray:
        """Drainage du buffer — mono float32 48 kHz (l'AEC et le mixage du cœur
        rééchantillonnent déjà, comportement identique à la capture SCK macOS)."""
        with self._verrou:
            if not self._buffer:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._buffer)
            self._buffer = []
        return audio

    # ── Thread de capture — tout `soundcard` vit ici (docs/34 §2.1) ─────────────

    @staticmethod
    def _nom_haut_parleur_defaut(sc, repli: str | None) -> str | None:
        try:
            return sc.default_speaker().name
        except Exception:
            return repli

    def _boucle_capture(self) -> None:
        import soundcard as sc

        nom_capte = self._nom_haut_parleur_defaut(sc, repli=None)
        if nom_capte is None:
            logger.error("Capture système : aucun haut-parleur par défaut disponible")
            return
        logger.info("Capture système démarrée sur %r (%d Hz)", nom_capte, TAUX)

        echecs_consecutifs = 0
        while not self._arret.is_set():
            nom_capte = self._nom_haut_parleur_defaut(sc, repli=nom_capte)
            try:
                mic = sc.get_microphone(nom_capte, include_loopback=True)
                with mic.recorder(samplerate=TAUX, channels=CANAUX, blocksize=TAILLE_BLOC) as rec:
                    echecs_consecutifs = 0
                    derniere_verif = time.monotonic()
                    while not self._arret.is_set():
                        bloc = rec.record(numframes=TAILLE_BLOC)
                        mono = bloc.mean(axis=1).astype(np.float32)
                        with self._verrou:
                            self._buffer.append(mono)

                        maintenant = time.monotonic()
                        if maintenant - derniere_verif >= _INTERVALLE_SURVEILLANCE_S:
                            derniere_verif = maintenant
                            nouveau = self._nom_haut_parleur_defaut(sc, repli=nom_capte)
                            if nouveau != nom_capte:
                                logger.info("Sortie audio changée : %r → %r", nom_capte, nouveau)
                                nom_capte = nouveau
                                break   # sort du `with` → réouverture sur le nouveau haut-parleur
            except Exception as exc:
                echecs_consecutifs += 1
                logger.warning(
                    "Capture système : échec (%s) [%d/%d]",
                    exc, echecs_consecutifs, _ECHECS_MAX_AVANT_SILENCE, exc_info=True,
                )
                if echecs_consecutifs >= _ECHECS_MAX_AVANT_SILENCE:
                    logger.error(
                        "Capture système : %d échecs consécutifs — passage en mode silence "
                        "(la réunion continue avec le micro seul)",
                        echecs_consecutifs,
                    )
                    self._silence = True
                    self._arret.wait()
                    return
