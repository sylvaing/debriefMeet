from __future__ import annotations

import threading
import time

import numpy as np

from debrief_meet.core.audio import reechantillonner
from debrief_meet.platform.interfaces import CaptureMicro

TAUX_CANONIQUE = 16_000  # point de convergence de toute la chaîne (Whisper, AEC, WAV retenu)


class CaptureMicroSounddevice(CaptureMicro):
    """Capture microphone via sounddevice.

    Le flux est ouvert uniquement pendant un enregistrement et fermé
    dès l'arrêt — l'indicateur micro macOS n'apparaît qu'en session.

    Chaque flux est ouvert au **taux natif du périphérique** (jamais un taux
    imposé : certains micros Bluetooth, ex. AirPods en mode mains-libres à
    24 kHz, refusent 44 100 Hz → `-10851`). Les blocs captés sont étiquetés
    avec ce taux natif ; `recuperer_echantillons` les rééchantillonne vers le
    taux canonique 16 kHz avant de les rendre — `taux_echantillonnage`
    retourne donc toujours 16000, quel que soit le périphérique.

    Un warm-up de 200 ms est appliqué à chaque ouverture : Core Audio
    prend ce temps pour reconfigurer le graphe audio (bref silence sur
    la sortie). L'audio capturé pendant cette fenêtre est jeté, ce qui
    rend le glitch inaudible.
    """

    WARMUP_S = 0.2  # secondes à jeter après ouverture du flux
    DELAI_FERMETURE_S = 0.3  # délai avant fermeture physique du flux

    def __init__(self) -> None:
        self._buffer: list[tuple[np.ndarray, int]] = []  # (bloc, taux_natif_a_la_capture)
        self._verrou = threading.Lock()
        self._stream = None
        self._sr_flux = TAUX_CANONIQUE  # taux natif du flux actuellement ouvert
        self._fermer_event = threading.Event()
        self._thread_fermeture: threading.Thread | None = None

    @property
    def taux_echantillonnage(self) -> int:
        return TAUX_CANONIQUE

    def disponible(self) -> bool:
        try:
            import sounddevice as sd
            sd.query_devices(kind="input")
            return True
        except Exception:
            return False

    @staticmethod
    def _taux_natif(stream) -> int:
        sr = getattr(stream, "samplerate", None)
        return int(round(sr)) if sr else TAUX_CANONIQUE

    def _ouvrir_flux(self, sd, index_peripherique: int | None):
        """Ouvre un InputStream au taux natif du périphérique, avec repli sur le
        périphérique par défaut.

        `samplerate=None` laisse PortAudio choisir le taux natif du périphérique
        (plus jamais un taux imposé qui ferait échouer certains micros Bluetooth).
        Si l'index demandé échoue (ex. AirPods déconnectés), on réessaie sur le
        périphérique par défaut. Un index None qui échoue est propagé (pas de
        périphérique du tout)."""
        try:
            return sd.InputStream(
                samplerate=None,
                channels=1,
                dtype="float32",
                device=index_peripherique,
                callback=self._callback,
            )
        except Exception:
            if index_peripherique is None:
                raise
            import logging
            logging.getLogger(__name__).warning(
                "Périphérique micro %s indisponible — repli sur le périphérique par défaut",
                index_peripherique,
            )
            return sd.InputStream(
                samplerate=None,
                channels=1,
                dtype="float32",
                device=None,
                callback=self._callback,
            )

    def _attendre_fermeture_differee(self) -> None:
        """Attend la fermeture physique d'un flux confié à `arreter()` (fermeture
        différée de `DELAI_FERMETURE_S`) avant de rafraîchir PortAudio — un refresh
        avec un flux encore ouvert laisse PortAudio dans un état indéfini (cf. docs/25)."""
        self._fermer_event.set()  # réveille _fermer_flux immédiatement
        t = self._thread_fermeture
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        self._thread_fermeture = None

    @staticmethod
    def _rafraichir_portaudio(sd) -> None:
        """Resynchronise la table de périphériques PortAudio (figée à `Pa_Initialize`,
        pas de hot-plug — cf. docs/25). À n'appeler QUE quand aucun flux n'est ouvert.

        API privée de sounddevice, best-effort : un échec ne doit jamais casser la
        capture. Limitation acceptée : après un refresh, PortAudio peut renuméroter
        les index — un `micro_index` stocké en config peut donc viser un autre
        périphérique (le repli de `_ouvrir_flux` sur le défaut couvre l'échec franc ;
        stocker le nom plutôt que l'index est hors périmètre)."""
        try:
            sd._terminate()
            sd._initialize()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug("Refresh PortAudio impossible (%s)", exc)

    def demarrer(self, index_peripherique: int | None = None) -> None:
        import sounddevice as sd

        if self._stream is not None:
            import logging
            logging.getLogger(__name__).warning(
                "demarrer() appelé alors qu'un flux micro était déjà ouvert — fermeture avant réouverture"
            )
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

        with self._verrou:
            self._buffer = []

        self._attendre_fermeture_differee()
        self._rafraichir_portaudio(sd)

        self._stream = self._ouvrir_flux(sd, index_peripherique)
        self._sr_flux = self._taux_natif(self._stream)
        self._stream.start()

        # Warm-up : on laisse Core Audio se reconfigurer, puis on
        # vide le buffer pour ne pas capturer le glitch de démarrage.
        time.sleep(self.WARMUP_S)
        with self._verrou:
            self._buffer = []

    def redemarrer(self, index_peripherique: int | None = None) -> None:
        """Reconnecte à chaud sur un nouveau périphérique en préservant le buffer.

        Le glitch capté pendant le warm-up du nouveau flux est jeté, mais
        l'audio déjà accumulé depuis la dernière tranche est conservé — avec
        son étiquette de taux natif d'origine (ex. 48k avant le switch, puis
        24k après : `recuperer_echantillons` rééchantillonne chaque suite
        séparément avant de les recoller en 16 kHz)."""
        import sounddevice as sd

        ancien = self._stream
        self._stream = None  # stoppe la collecte sur l'ancien flux
        if ancien is not None:
            try:
                ancien.stop()
                ancien.close()
            except Exception:
                pass

        # Snapshot de l'audio déjà capté (l'ancien flux est fermé, le buffer est figé).
        with self._verrou:
            preserve = list(self._buffer)

        self._attendre_fermeture_differee()
        self._rafraichir_portaudio(sd)

        nouveau = self._ouvrir_flux(sd, index_peripherique)
        self._sr_flux = self._taux_natif(nouveau)
        nouveau.start()

        # Warm-up : ce que le nouveau flux capte ici est du glitch → on le jette
        # en restaurant le buffer à son snapshot d'avant ouverture.
        time.sleep(self.WARMUP_S)
        with self._verrou:
            self._buffer = preserve
        self._stream = nouveau
        logging_index = index_peripherique if index_peripherique is not None else "défaut"
        import logging
        logging.getLogger(__name__).info("Micro reconnecté à chaud sur %s", logging_index)

    def resoudre_peripherique(self, index_peripherique: int | None) -> object:
        """Nom du périphérique réellement résolu pour cet index (le nom, pas l'index :
        un retrait/rebranchement peut renuméroter les index sans changer le matériel).
        None si la résolution échoue (ex. plus aucun périphérique d'entrée)."""
        try:
            import sounddevice as sd
            if index_peripherique is not None:
                info = sd.query_devices(index_peripherique)
            else:
                info = sd.query_devices(kind="input")
            return info.get("name")
        except Exception:
            return None

    def arreter(self) -> None:
        stream = self._stream
        self._stream = None  # arrêt immédiat de la collecte
        if stream is not None:
            # Fermeture décalée en arrière-plan : Core Audio reconfigure
            # après que l'UI ait mis à jour l'état, rendant le glitch
            # de fermeture inaudible. L'event permet à terminer() de
            # réveiller ce thread immédiatement à la fermeture de l'app.
            self._fermer_event.clear()
            self._thread_fermeture = threading.Thread(
                target=self._fermer_flux, args=(stream,), daemon=True
            )
            self._thread_fermeture.start()

    def terminer(self) -> None:
        """Fermeture propre à la sortie de l'application."""
        self._fermer_event.set()  # réveille un _fermer_flux en attente
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _fermer_flux(self, stream) -> None:
        # Attend le délai normal, ou se réveille tôt si terminer() est appelé.
        self._fermer_event.wait(timeout=self.DELAI_FERMETURE_S)
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def recuperer_echantillons(self) -> np.ndarray:
        """Concatène le buffer et le renvoie rééchantillonné à 16 kHz.

        Chaque suite contiguë de blocs de même taux natif est rééchantillonnée
        en un seul appel (évite les transitoires de bord de bloc), puis les
        suites sont recollées — un switch de périphérique en cours de tranche
        produit deux suites (ex. 48k puis 24k) qui se recollent en 16k homogène."""
        with self._verrou:
            if not self._buffer:
                return np.zeros(0, dtype=np.float32)
            buffer = self._buffer
            self._buffer = []

        morceaux: list[np.ndarray] = []
        suite_sr: int | None = None
        suite_blocs: list[np.ndarray] = []
        for bloc, sr in buffer:
            if suite_blocs and sr != suite_sr:
                morceaux.append(reechantillonner(
                    np.concatenate(suite_blocs), suite_sr, TAUX_CANONIQUE))
                suite_blocs = []
            suite_sr = sr
            suite_blocs.append(bloc)
        if suite_blocs:
            morceaux.append(reechantillonner(
                np.concatenate(suite_blocs), suite_sr, TAUX_CANONIQUE))

        return np.concatenate(morceaux).astype(np.float32)

    def _callback(self, indata, frames, time_info, status) -> None:
        with self._verrou:
            self._buffer.append((indata.copy().flatten(), self._sr_flux))
