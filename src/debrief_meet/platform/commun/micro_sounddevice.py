from __future__ import annotations

import sys
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

    # Fermeture physique qui ne revient pas (docs/16 §5.7) : la PortAudio 19.7.0 de
    # sounddevice peut s'interbloquer dans `stream.stop()` avec le thread d'E/S de
    # CoreAudio — le micro reste alors ouvert (pastille orange) jusqu'à la mort du
    # process, et rien ne le débloque de l'intérieur. Corrigé à la source dans l'app
    # livrée (dylib recompilée avec PortAudio#1175) ; ces deux délais n'en sont que le
    # filet : rendre une rechute visible dans le log, et ne pas l'aggraver.
    ALERTE_FERMETURE_S = 5.0   # au-delà, WARNING « micro non libéré »
    ATTENTE_FERMETURE_S = 2.0  # attente max de la fermeture avant un refresh PortAudio

    # Comblement des trous de capture (docs/48 §8) : PortAudio peut PERDRE des
    # échantillons quand le callback est affamé (le wrapper Python attend le GIL
    # tenu par le MainThread — pousser AEC ~0,2 s/tranche, upload Mistral, UI —
    # et le buffer HAL déborde pendant ce temps). Chaque perte décale
    # DÉFINITIVEMENT la piste micro par rapport à la piste système : l'AEC se
    # désaligne (sauts de 65 à 193 ms mesurés le 2026-08-18, causalité cassée →
    # 0 dB) et moi.opus/systeme.opus divergent d'autant. On détecte le trou par
    # la discontinuité de l'horodatage ADC des blocs et on le comble par du
    # silence de même durée — le flux reste juste à l'échantillon.
    TROU_MIN_S = 0.020  # sous ce seuil : gigue d'horodatage, pas une perte
    TROU_MAX_S = 10.0   # au-delà : horodatage aberrant → resynchroniser sans combler

    # Host API préféré quand AUCUN périphérique n'est demandé (terrain 2026-08-26).
    # PortAudio prend par défaut, sous Windows, le périphérique par défaut de **MME** —
    # le plus ancien host API, dont `inputBufferAdcTime` n'est pas l'horloge du
    # périphérique. Le comblement de trous ci-dessus en dépend entièrement : sous MME il
    # est silencieusement hors service (constaté chez une utilisatrice Windows : overflow
    # signalé par PortAudio, 0 trou détecté, et l'offset inter-pistes qui saute de 0,6 à
    # 0,7 s par bond — AEC à 0 dB sur une réunion entière). `_logger_infos_flux` disait
    # déjà que MME est « un indice de latence/qualité dégradée » (E-8, docs/33 §2.1) :
    # on ne s'y résigne plus, on demande WASAPI et on retombe sur le défaut global si
    # WASAPI est absent ou refuse d'ouvrir.
    HOST_API_PREFERE_DEFAUT = "WASAPI"

    # Déficit d'échantillons avant d'annoncer que le comblement est hors service.
    #
    # Ni `paInputOverflow` ni l'horodatage ADC ne sont des déclencheurs fiables : sur le
    # poste du terrain 2026-08-26, l'offset inter-pistes a sauté de 1,3 s en 12 min avec
    # **zéro** overflow signalé ce jour-là (un seul sur tout le mois) — les pertes ne se
    # déclarent pas. Le seul signal indépendant de l'host API : comparer le temps écoulé
    # à l'horloge murale au nombre d'échantillons réellement livrés. Un déficit, ce sont
    # des échantillons perdus, point. La dérive d'horloge légitime (12 ppm mesurés,
    # docs/48 §8.4) vaut 1 ms sur 80 s — trois ordres de grandeur sous le seuil, aucune
    # confusion possible. `time.monotonic` n'avance pas pendant une veille système :
    # refermer le capot ne fabrique pas de faux déficit.
    DEFICIT_ALERTE_S = 0.250

    # Rétrogradation de l'host API préféré : un flux OUVERT qui ne livre aucun bloc
    # pendant ce délai est mort. Sans cette garde, la bascule WASAPI a un pire cas bien
    # plus grave que le statu quo : le watchdog « tranche muette » de `core/reunion`
    # rappelle `redemarrer(micro_index)` avec le MÊME `micro_index = None`, donc la même
    # préférence, donc le même flux muet — une réunion entière de silence en boucle. On
    # abandonne donc la préférence pour le reste de la session : la reconnexion suivante
    # repart sur le défaut global. Les blocs arrivent toutes les ~10-50 ms : 5 s sans
    # rien n'est pas de la gigue.
    MUET_AVANT_RETROGRADATION_S = 5.0

    def __init__(self, host_api_prefere: str | None = None) -> None:
        # Paramètre explicite plutôt qu'un `sys.platform` lu dans `_ouvrir_flux` (même
        # raison que `surveillant_peripheriques`) : les tests restent déterministes sur
        # les deux OS, la gate de build tournant sur la VM Windows. `""` désactive la
        # préférence (= comportement PortAudio d'origine).
        self._host_api_prefere = (
            self.HOST_API_PREFERE_DEFAUT if host_api_prefere is None and sys.platform == "win32"
            else (host_api_prefere or ""))
        self._buffer: list[tuple[np.ndarray, int]] = []  # (bloc, taux_natif_a_la_capture)
        self._verrou = threading.Lock()
        self._stream = None
        self._sr_flux = TAUX_CANONIQUE  # taux natif du flux actuellement ouvert
        self._fermer_event = threading.Event()
        self._thread_fermeture: threading.Thread | None = None
        # Continuité ADC (docs/48 §8) : horodatage attendu du prochain bloc, sur
        # l'horloge PortAudio du flux courant. Lu/écrit UNIQUEMENT par le thread
        # callback (sérialisé) — pas de verrou ; remis à None à chaque nouveau flux.
        self._adc_attendu: float | None = None
        # Compteurs d'incidents, drainés à chaque tranche (sous _verrou).
        self._overflows = 0
        self._trous_combles = 0
        self._silence_comble_s = 0.0
        # Aveuglement du comblement (terrain 2026-08-26) : cumulés sur la DURÉE DU FLUX,
        # pas drainés par tranche — c'est une propriété de l'host API, pas de la tranche.
        self._overflows_sans_trou = 0
        self._blocs_sans_horodatage = 0
        self._trous_combles_flux = 0
        self._alerte_aveugle_emise = False
        # Comptabilité murale : instant du 1ᵉʳ bloc du flux, et total livré depuis (blocs
        # + silence de comblement). L'écart entre les deux EST la perte non compensée.
        self._t0_flux: float | None = None
        self._echantillons_livres = 0
        # Ouverture du flux : mesurée AU DÉMARRAGE, pas au 1ᵉʳ bloc — c'est justement
        # l'absence de bloc qu'on doit pouvoir constater (`_t0_flux` resterait None).
        self._t_ouverture: float | None = None
        self._retrogradation_faite = False

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

    @staticmethod
    def _logger_infos_flux(sd, stream, taux_natif: int) -> None:
        """E-8 (docs/33 §2.1) : périphérique/host API/taux à chaque (re)démarrage —
        un host API `MME` au lieu de `WASAPI` sur Windows est un indice de latence/
        qualité dégradée, détectable à distance dans un zip diagnostic."""
        import logging
        try:
            infos = sd.query_devices(stream.device)
            nom = infos["name"]
            host_api = sd.query_hostapis(infos["hostapi"])["name"]
        except Exception:
            nom, host_api = "inconnu", "inconnu"
        logging.getLogger(__name__).info(
            "Micro (re)démarré : périphérique=%r host_api=%s taux_natif=%dHz taux_sortie=%dHz",
            nom, host_api, taux_natif, TAUX_CANONIQUE,
        )

    def _defaut_host_api_prefere(self, sd) -> int | None:
        """Index du périphérique d'entrée par défaut de l'host API préféré, ou None.

        None couvre tous les cas d'indisponibilité (préférence vide, host API absent,
        pas d'entrée par défaut, PortAudio muet) : l'appelant retombe alors sur le
        défaut global. On ne lève jamais — un host API manquant n'est pas une panne."""
        if not self._host_api_prefere:
            return None
        vise = self._host_api_prefere.lower()
        try:
            for api in sd.query_hostapis():
                if vise not in str(api.get("name", "")).lower():
                    continue
                index = api.get("default_input_device")
                # PortAudio met -1 quand l'host API n'a aucune entrée par défaut.
                if index is None or int(index) < 0:
                    continue
                return int(index)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug(
                "Host API préféré %r introuvable (%s) — défaut global",
                self._host_api_prefere, exc)
        return None

    def _ouvrir_flux(self, sd, index_peripherique: int | None):
        """Ouvre un InputStream au taux natif du périphérique, avec repli sur le
        périphérique par défaut.

        `samplerate=None` laisse PortAudio choisir le taux natif du périphérique
        (plus jamais un taux imposé qui ferait échouer certains micros Bluetooth).
        Si l'index demandé échoue (ex. AirPods déconnectés), on réessaie sur le
        périphérique par défaut. Un index None qui échoue est propagé (pas de
        périphérique du tout)."""
        if index_peripherique is None:
            # Aucun périphérique demandé : viser le défaut de l'host API préféré plutôt
            # que le défaut global de PortAudio (cf. HOST_API_PREFERE_DEFAUT). None si
            # indisponible → défaut global, comme avant.
            index_peripherique = self._defaut_host_api_prefere(sd)
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

    def _attendre_fermeture_differee(self) -> bool:
        """Attend la fermeture physique d'un flux confié à `arreter()` (fermeture
        différée de `DELAI_FERMETURE_S`) avant de rafraîchir PortAudio — un refresh
        avec un flux encore ouvert laisse PortAudio dans un état indéfini (cf. docs/25).

        Rend False si la fermeture n'est toujours pas revenue : l'appelant ne doit
        alors PAS rafraîchir. `sd._terminate()` est un `Pa_Terminate`, qui ferme les
        flux encore ouverts — il buterait sur le verrou CoreAudio qui retient
        `_fermer_flux` et figerait le thread appelant, c'est-à-dire l'UI (docs/16 §5.7)."""
        self._fermer_event.set()  # réveille _fermer_flux immédiatement
        t = self._thread_fermeture
        if t is not None and t.is_alive():
            t.join(timeout=self.ATTENTE_FERMETURE_S)
            if t.is_alive():
                import logging
                logging.getLogger(__name__).warning(
                    "Ancien flux micro toujours pas fermé — refresh PortAudio sauté "
                    "(Pa_Terminate se bloquerait sur le même verrou CoreAudio)")
                return False
        self._thread_fermeture = None
        return True

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
            self._overflows = self._trous_combles = 0
            self._silence_comble_s = 0.0
            self._reinitialiser_suivi_horodatage()

        if self._attendre_fermeture_differee():
            self._rafraichir_portaudio(sd)

        self._stream = self._ouvrir_flux(sd, index_peripherique)
        self._sr_flux = self._taux_natif(self._stream)
        self._adc_attendu = None  # nouveau flux = nouvelle horloge PortAudio
        self._stream.start()
        self._t_ouverture = time.monotonic()
        self._logger_infos_flux(sd, self._stream, self._sr_flux)

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

        if self._attendre_fermeture_differee():
            self._rafraichir_portaudio(sd)

        nouveau = self._ouvrir_flux(sd, index_peripherique)
        self._sr_flux = self._taux_natif(nouveau)
        self._adc_attendu = None  # nouveau flux = nouvelle horloge PortAudio
        with self._verrou:
            self._reinitialiser_suivi_horodatage()
        nouveau.start()
        self._t_ouverture = time.monotonic()
        self._logger_infos_flux(sd, nouveau, self._sr_flux)

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
            alerte = threading.Timer(
                self.ALERTE_FERMETURE_S, self._alerter_si_non_ferme,
                args=(self._thread_fermeture,))
            alerte.daemon = True
            alerte.start()

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

    def _alerter_si_non_ferme(self, thread: threading.Thread) -> None:
        """Un thread bloqué dans `stream.stop()` ne peut rien journaliser lui-même : c'est
        ce minuteur qui constate. Sans lui, le seul symptôme était la pastille orange."""
        if thread.is_alive():
            import logging
            logging.getLogger(__name__).warning(
                "Flux micro toujours pas fermé %.0f s après l'arrêt — interblocage "
                "CoreAudio probable (docs/16 §5.7) : le micro reste ouvert jusqu'au "
                "redémarrage de l'app", self.ALERTE_FERMETURE_S)

    def _fermer_flux(self, stream) -> None:
        # Attend le délai normal, ou se réveille tôt si terminer() est appelé.
        self._fermer_event.wait(timeout=self.DELAI_FERMETURE_S)
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def bilan(self) -> str:
        """État de la capture en une ligne, pour le bilan de fin de réunion : host API
        réellement retenu, déficit d'échantillons, trous comblés."""
        with self._verrou:
            t0, livres = self._t0_flux, self._echantillons_livres
            trous, sans_horodatage = self._trous_combles_flux, self._blocs_sans_horodatage
            retrograde = self._retrogradation_faite
        if t0 is None:
            return "aucun bloc reçu"
        deficit = time.monotonic() - t0 - livres / max(1, self._sr_flux)
        details = [f"déficit {deficit * 1000:+.0f} ms", f"{trous} trou(s) comblé(s)"]
        if sans_horodatage:
            details.append(f"{sans_horodatage} bloc(s) sans horodatage ADC")
        if retrograde:
            details.append("host API préféré abandonné")
        return ", ".join(details)

    def _reinitialiser_suivi_horodatage(self) -> None:
        """Compteurs d'aveuglement, par FLUX (à appeler sous `_verrou`). Un nouveau flux
        peut viser un autre host API : le verdict précédent ne le concerne pas."""
        self._overflows_sans_trou = 0
        self._blocs_sans_horodatage = 0
        self._trous_combles_flux = 0
        self._alerte_aveugle_emise = False
        self._t0_flux = None
        self._echantillons_livres = 0
        # NB : `_retrogradation_faite` et `_host_api_prefere` ne sont PAS réarmés ici.
        # Ils vivent à la session : les réarmer ferait retenter l'host API muet à chaque
        # reconnexion, c'est-à-dire exactement la boucle qu'on cherche à casser.

    def _retrograder_si_flux_muet(self) -> None:
        """Abandonne l'host API préféré si le flux ouvert ne livre RIEN.

        Appelé au drain de tranche. Ne rouvre pas le flux : la reconnexion est déjà le
        travail du watchdog « tranche muette » de `core/reunion`, qui repasse par
        `redemarrer(micro_index)`. En retirant la préférence, on rend ce watchdog
        efficace au lieu de le laisser boucler sur le même host API."""
        if (self._retrogradation_faite or not self._host_api_prefere
                or self._t_ouverture is None or self._t0_flux is not None):
            return
        if time.monotonic() - self._t_ouverture < self.MUET_AVANT_RETROGRADATION_S:
            return
        abandonne, self._host_api_prefere = self._host_api_prefere, ""
        self._retrogradation_faite = True
        import logging
        logging.getLogger(__name__).warning(
            "Micro : aucun bloc reçu depuis %.0f s sur l'host API %s — préférence "
            "abandonnée pour cette session, la prochaine reconnexion prendra le "
            "périphérique par défaut du système.",
            self.MUET_AVANT_RETROGRADATION_S, abandonne)

    def _alerter_si_comblement_aveugle(self) -> None:
        """Dit une fois par flux que le comblement de trous est hors service.

        Le comblement (docs/48 §8) suppose que `inputBufferAdcTime` porte l'horloge du
        PÉRIPHÉRIQUE. Quand l'host API ne fournit rien, ou qu'il dérive l'horodatage du
        nombre d'échantillons livrés, un trou est invisible : PortAudio annonce des
        overflows et le détecteur ne comble rien. Ce silence-là a coûté cher (terrain
        2026-08-26 : il a fallu remonter l'offset de l'AEC pour deviner que les pertes
        n'étaient pas compensées) — désormais le diagnostic le dit lui-même.

        Le DÉCLENCHEUR est le déficit d'horloge murale (`DEFICIT_ALERTE_S`), pas
        l'absence d'horodatage ni les overflows : un host API qui ne fournit pas
        d'horodatage mais ne perd rien ne mérite aucun WARNING (sinon Linux et macOS en
        récolteraient un par réunion), et un poste qui perd des échantillons sans le
        déclarer doit en récolter un (c'est exactement le cas du terrain). L'horodatage
        et les overflows ne servent plus qu'à EXPLIQUER le déficit constaté.

        Émis depuis le drain de tranche (MainThread) et jamais depuis le callback :
        logger dans le callback le ferait attendre une écriture disque, ce qui est
        précisément la famine qui provoque les pertes qu'on cherche à décrire."""
        with self._verrou:
            if self._alerte_aveugle_emise or self._t0_flux is None:
                return
            deficit = (time.monotonic() - self._t0_flux
                       - self._echantillons_livres / max(1, self._sr_flux))
            if deficit < self.DEFICIT_ALERTE_S:
                return
            sans_horodatage = self._blocs_sans_horodatage
            sans_trou = self._overflows_sans_trou
            trous = self._trous_combles_flux
            self._alerte_aveugle_emise = True

        import logging
        cause = ("l'host API ne fournit pas d'horodatage ADC"
                 if sans_horodatage else
                 "l'horodatage ADC ne montre aucune discontinuité malgré les pertes")
        logging.getLogger(__name__).warning(
            "Micro : comblement des trous HORS SERVICE — %.0f ms d'échantillons manquants "
            "non compensés depuis l'ouverture du flux ; %s (%d bloc(s) sans horodatage, "
            "%d overflow(s) non compensé(s), %d trou(s) comblé(s)). L'alignement "
            "moi/systeme n'est plus garanti et l'AEC va décrocher. Choisir un micro sous "
            "un autre host API (Préférences › Audio) — cf. docs/48 §8.",
            deficit * 1000, cause, sans_horodatage, sans_trou, trous)

    def recuperer_echantillons(self) -> np.ndarray:
        """Concatène le buffer et le renvoie rééchantillonné à 16 kHz.

        Chaque suite contiguë de blocs de même taux natif est rééchantillonnée
        en un seul appel (évite les transitoires de bord de bloc), puis les
        suites sont recollées — un switch de périphérique en cours de tranche
        produit deux suites (ex. 48k puis 24k) qui se recollent en 16k homogène."""
        with self._verrou:
            buffer, self._buffer = self._buffer, []
            overflows, self._overflows = self._overflows, 0
            trous, self._trous_combles = self._trous_combles, 0
            comble_s, self._silence_comble_s = self._silence_comble_s, 0.0

        self._retrograder_si_flux_muet()
        if trous or overflows:
            # WARNING assumé (docs/48 : « l'échec était dans les logs, mais en
            # DEBUG ») — borné à 1 ligne par tranche, jamais par événement.
            import logging
            logging.getLogger(__name__).warning(
                "Micro : %d trou(s) de capture comblé(s) par %.0f ms de silence, "
                "%d overflow(s) PortAudio signalé(s) sur la tranche — continuité "
                "des pistes préservée (docs/48 §8)",
                trous, comble_s * 1000, overflows)
        self._alerter_si_comblement_aveugle()

        if not buffer:
            return np.zeros(0, dtype=np.float32)

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
        sr = self._sr_flux
        silence, horodatage_utilisable = self._silence_de_comblement(frames, time_info, sr)
        overflow = bool(getattr(status, "input_overflow", False))
        with self._verrou:
            if overflow:
                self._overflows += 1
                # Overflow annoncé par PortAudio ET aucun trou détecté sur ce bloc : soit
                # l'horodatage manque, soit il est dérivé des échantillons LIVRÉS (donc
                # continu par construction, un trou y est invisible). Dans les deux cas
                # les échantillons perdus ne sont PAS compensés — cf. l'alerte drainée
                # dans `recuperer_echantillons`.
                if silence is None:
                    self._overflows_sans_trou += 1
            if not horodatage_utilisable:
                self._blocs_sans_horodatage += 1
            if silence is not None:
                self._buffer.append((silence, sr))
                self._trous_combles += 1
                self._trous_combles_flux += 1
                self._silence_comble_s += len(silence) / sr
                # Le silence de comblement compte comme LIVRÉ : il remplace les
                # échantillons perdus, donc un trou correctement comblé ne creuse aucun
                # déficit. C'est ce qui sépare « comblement opérant » de « hors service ».
                self._echantillons_livres += len(silence)
            self._buffer.append((indata.copy().flatten(), sr))
            self._echantillons_livres += frames
            if self._t0_flux is None:
                self._t0_flux = time.monotonic()

    def _silence_de_comblement(self, frames, time_info, sr) -> tuple[np.ndarray | None, bool]:
        """(silence couvrant les échantillons perdus avant ce bloc, horodatage utilisable).

        Les blocs d'un flux sain sont contigus sur l'horloge ADC
        (`time_info.inputBufferAdcTime`) : un saut en avant = des échantillons ont
        été jetés en amont (buffer HAL débordé pendant que le callback attendait le
        GIL, cf. commentaire de classe). On ne s'appuie PAS sur `paInputOverflow` :
        le drapeau n'est pas garanti par tous les host API, l'horodatage si — et il
        donne la taille exacte du trou. Hors service si l'API ne fournit pas
        d'horodatage (adc ≤ 0) : on ne comble jamais à l'aveugle.
        Appelé uniquement depuis le thread callback (`_adc_attendu` sans verrou)."""
        adc = float(getattr(time_info, "inputBufferAdcTime", 0.0) or 0.0)
        attendu = self._adc_attendu
        self._adc_attendu = adc + frames / sr if adc > 0 else None
        if adc <= 0:
            return None, False          # host API sans horodatage : comblement impossible
        if attendu is None:
            return None, True           # premier bloc du flux : rien à comparer
        manque = adc - attendu
        if not (self.TROU_MIN_S <= manque <= self.TROU_MAX_S):
            return None, True
        return np.zeros(int(round(manque * sr)), dtype=np.float32), True
