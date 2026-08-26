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

# Comblement du silence (docs/48 ; port de `platform/linux/capture_systeme_monitor.py`,
# qui l'a appris le premier). Toute seconde de temps mural pendant laquelle ce thread ne
# livre rien RACCOURCIT la piste système, donc décale les deux pistes d'autant : l'AEC
# décroche et l'attribution des locuteurs devient fausse. Trois chemins perdaient ce
# temps sans rien combler — l'exception + réouverture, le changement de sortie, et
# surtout l'abandon après `_ECHECS_MAX_AVANT_SILENCE` échecs, où `_silence = True` était
# posé puis JAMAIS lu (aucun silence n'était injecté, la piste s'arrêtait de grandir
# jusqu'à la fin de la réunion).
_COMBLEMENT_MIN_S = 0.050          # sous ce seuil : gigue d'ordonnancement, pas un trou
_COMBLEMENT_MAX_S = 600.0          # borne mémoire (10 min de zéros = 115 Mo en float32)
_PERIODE_LOG_SILENCE_S = 30.0      # récap d'une panne qui dure, pour ne pas noyer le log
_PERIODE_COMBLEMENT_S = 1.0        # cadence d'injection pendant une panne persistante


class CaptureAudioSystemeWasapi(CaptureAudioSysteme):
    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._verrou = threading.Lock()
        self._thread: threading.Thread | None = None
        self._arret = threading.Event()
        self._demarre = False
        self._silence = False
        # Horloge de continuité : instant de la dernière livraison réelle. L'écart avec
        # le temps mural EST le trou à combler.
        self._t_derniere_trame = 0.0
        self._silence_cumule_s = 0.0
        self._dernier_log_silence = 0.0

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
        self._t_derniere_trame = time.monotonic()
        self._silence_cumule_s = 0.0
        self._dernier_log_silence = self._t_derniere_trame
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

    def _combler_silence(self, jusqu_a: float, raison: str, periodique: bool = False) -> None:
        """Injecte des zéros pour couvrir l'intervalle sans livraison (docs/48).

        Calque de `platform/linux/capture_systeme_monitor._combler_silence`. Appelé
        depuis le thread de capture uniquement. `periodique=True` pour une panne qui
        dure : le silence est bien injecté à chaque tick, mais le journal n'en garde
        qu'un récapitulatif toutes les `_PERIODE_LOG_SILENCE_S`."""
        manque_s = jusqu_a - self._t_derniere_trame
        if manque_s < _COMBLEMENT_MIN_S:
            return
        retenu_s = min(manque_s, _COMBLEMENT_MAX_S)
        with self._verrou:
            self._buffer.append(np.zeros(int(retenu_s * TAUX), dtype=np.float32))
        self._t_derniere_trame = jusqu_a
        self._silence_cumule_s += retenu_s

        if retenu_s < manque_s:
            logger.warning("Piste système : trou de %.1f s (%s) comblé à hauteur de "
                           "%.0f s seulement — les pistes seront décalées d'autant",
                           manque_s, raison, retenu_s)
            return
        if not periodique:
            logger.info("Piste système : %.1f s de silence injectées (%s)", retenu_s, raison)
            return
        if jusqu_a - self._dernier_log_silence >= _PERIODE_LOG_SILENCE_S:
            self._dernier_log_silence = jusqu_a
            logger.warning("Piste système toujours indisponible (%s) — %.0f s de "
                           "silence injectées au total", raison, self._silence_cumule_s)

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
        raison_trou = "ouverture de la capture"
        while not self._arret.is_set():
            nom_capte = self._nom_haut_parleur_defaut(sc, repli=nom_capte)
            try:
                mic = sc.get_microphone(nom_capte, include_loopback=True)
                with mic.recorder(samplerate=TAUX, channels=CANAUX, blocksize=TAILLE_BLOC) as rec:
                    echecs_consecutifs = 0
                    derniere_verif = time.monotonic()
                    # Le temps passé à (ré)ouvrir WASAPI n'a rien livré : le combler ici,
                    # sinon la piste système est courte de cette durée à chaque cycle.
                    self._combler_silence(derniere_verif, raison_trou)
                    while not self._arret.is_set():
                        bloc = rec.record(numframes=TAILLE_BLOC)
                        mono = bloc.mean(axis=1).astype(np.float32)
                        with self._verrou:
                            self._buffer.append(mono)
                        self._t_derniere_trame = time.monotonic()

                        maintenant = time.monotonic()
                        if maintenant - derniere_verif >= _INTERVALLE_SURVEILLANCE_S:
                            derniere_verif = maintenant
                            nouveau = self._nom_haut_parleur_defaut(sc, repli=nom_capte)
                            if nouveau != nom_capte:
                                logger.info("Sortie audio changée : %r → %r", nom_capte, nouveau)
                                nom_capte = nouveau
                                raison_trou = "changement de sortie audio"
                                break   # sort du `with` → réouverture sur le nouveau haut-parleur
            except Exception as exc:
                echecs_consecutifs += 1
                raison_trou = f"capture système en échec ({type(exc).__name__})"
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
                    # `self._arret.wait()` suivi d'un `return` laissait la piste système
                    # cesser de grandir : elle finissait courte de TOUT le reste de la
                    # réunion, et `_silence` n'était lu par personne. On comble désormais
                    # en continu jusqu'à l'arrêt — la piste garde sa durée réelle.
                    while not self._arret.wait(_PERIODE_COMBLEMENT_S):
                        self._combler_silence(time.monotonic(), "capture système indisponible",
                                              periodique=True)
                    self._combler_silence(time.monotonic(), "capture système indisponible",
                                          periodique=True)
                    return
