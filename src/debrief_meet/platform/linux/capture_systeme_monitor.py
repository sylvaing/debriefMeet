"""Capture audio système Linux — source `.monitor` PipeWire (docs/49 §5.1).

Sous PipeWire, chaque sortie expose une source moniteur `<sink>.monitor` que
PortAudio rend visible : `sounddevice` suffit, ni `soundcard` (contrairement à
Windows) ni API PipeWire native. Tout ce qui suit est adossé aux **3 passages du
spike** `spike/capture_monitor_linux/` sur le poste cible (2026-08-12/13), pas à des
hypothèses — chaque garde ci-dessous répond à un comportement mesuré.

Les deux modes de panne mesurés, radicalement différents (docs/49 §5.1 Q4 et Q6) :

* **Le son part sur une autre sortie** (le sink reste présent, passe `IDLE`) : le flux
  continue de livrer des **zéros parfaits**, indéfiniment, sans erreur — 760 s
  observées. Indiscernable d'une réunion réellement silencieuse ⇒ la seule détection
  possible passe par `pactl`. ⚠️ Surveiller la **sortie par défaut** ne suffit pas :
  une application peut router son flux ailleurs sans que la sortie par défaut change
  (terrain 2026-08-31, 2 h 19 perdues). On résout donc la sortie depuis les **flux de
  lecture réels** — `sink_a_surveiller`, docs/49 §11.
* **Le sink disparaît** (casque BT déconnecté, dock débranché) : le flux **gèle** —
  plus une seule trame — pendant que `stream.active` reste `True`, sans exception ni
  statut PortAudio ⇒ la seule détection possible est l'**absence de trames**.

D'où deux gardes complémentaires, dont aucune ne peut remplacer l'autre, et
l'interdiction de se fier à `stream.active`.

**Repli silence obligatoire.** `core/reunion.py` mesure le temps à partir du *nombre
d'échantillons* de chaque piste : si la piste système cesse d'avancer pendant que le
micro continue, les deux se décalent exactement de la durée de la panne — l'alignement
inter-pistes que docs/48 s'emploie à maîtriser. Toute coupure est donc comblée par des
zéros à hauteur du temps réellement écoulé.

**Pas de rafraîchissement de la table PortAudio ici.** `sd._terminate()` ferme *tous*
les flux du process, micro compris (cf. `micro_sounddevice._rafraichir_portaudio`,
« à n'appeler QUE quand aucun flux n'est ouvert ») : le faire en cours de réunion
tuerait la piste micro en silence. Ce n'est pas une perte : `micro_sounddevice.demarrer()`
rafraîchit la table juste avant, et il démarre avant nous (`core/reunion.py`) — la
table est donc fraîche au début de chaque réunion. Limitation assumée, identique à
celle du micro : une sortie apparue **pendant** la réunion reste invisible ; on le
journalise et on tient la piste en silence.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

import numpy as np

from debrief_meet.platform.interfaces import CaptureAudioSysteme

logger = logging.getLogger(__name__)

TAUX = 48_000          # taux natif mesuré sur les sinks PipeWire du poste cible
CANAUX = 2             # les moniteurs sont stéréo ; downmix mono comme sur Windows
TAILLE_BLOC = 1024

# Sondage de la sortie par défaut. 2 s comme Windows (docs/34 §2.3) : au pire deux
# secondes de la mauvaise sortie, pour un `pactl` toutes les 2 s.
_INTERVALLE_TICK_S = 0.5
_INTERVALLE_SURVEILLANCE_S = 2.0

# Chien de garde : aucune trame pendant ce délai ⇒ flux gelé (sink détruit). Large
# devant la période d'un bloc (1024/48000 ≈ 21 ms) pour ne jamais rouvrir sur un
# simple à-coup d'ordonnancement.
_SILENCE_AVANT_REOUVERTURE_S = 2.0

# Un `demarrer()` juste après l'ouverture n'a encore reçu aucune trame : sans ce
# délai de grâce, le chien de garde rouvrirait aussitôt en boucle.
_GRACE_APRES_OUVERTURE_S = 3.0

# Garde-fou mémoire : une mise en veille de la machine peut créer un trou de plusieurs
# heures. On comble au plus 2 min d'un coup (≈ 23 Mo) et on le dit — mieux vaut une
# piste tronquée et un WARNING qu'une allocation d'un gigaoctet.
_COMBLEMENT_MAX_S = 120.0

# Sous ce seuil, l'écart n'est que le jitter normal entre deux blocs : ne rien combler.
_COMBLEMENT_MIN_S = 0.05

# Quand la capture est durablement indisponible, la boucle comble à chaque tick :
# journaliser chaque comblement noierait le log rotatif (2 lignes/s, soit ~7 000/h,
# alors que le fichier fait 5 Mo — cf. docs/31). On récapitule périodiquement.
_PERIODE_LOG_SILENCE_S = 30.0

_ECHECS_MAX_AVANT_SILENCE = 3

# Une bascule de sortie coûte une réouverture, donc un trou comblé par du silence : on
# ne la déclenche pas sur un clignotement. Un flux de lecture disparaît brièvement à
# chaque pause, changement de piste ou renégociation de la visio ; sans confirmation, la
# capture ferait l'aller-retour à chaque fois. Deux sondages concordants (≈ 4 s) suffisent
# à distinguer un vrai changement de sortie d'un à-coup.
_CONFIRMATIONS_AVANT_BASCULE = 2


# ── Résolution du moniteur ───────────────────────────────────────────────────────

def _pactl(*args: str) -> str | None:
    """Sortie de `pactl <args>`, ou None si l'outil manque ou échoue.

    `pulseaudio-utils` est un `Depends` du .deb (docs/49 §6.1) : son absence est une
    anomalie d'installation, pas un cas nominal — mais elle ne doit pas faire tomber
    la réunion."""
    if shutil.which("pactl") is None:
        return None
    try:
        # LC_ALL=C : `pactl list` traduit ses étiquettes (« Sink: », « Corked: ») dans
        # la locale de l'utilisateur, et on les parse. Le poste terrain est en français.
        resultat = subprocess.run(["pactl", *args], capture_output=True, text=True,
                                  timeout=5, check=True,
                                  env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C"})
        return resultat.stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("pactl %s a échoué (%s)", " ".join(args), exc)
        return None


def sink_par_defaut() -> str | None:
    """Nom technique de la sortie active, ex. `alsa_output.pci-….HiFi__HDMI1__sink`."""
    nom = _pactl("get-default-sink")
    return nom or None


def _sinks_par_index() -> dict[int, str]:
    """`index → nom` depuis `pactl list short sinks` (tabulé, jamais traduit)."""
    sortie = _pactl("list", "short", "sinks")
    if not sortie:
        return {}
    table: dict[int, str] = {}
    for ligne in sortie.splitlines():
        champs = ligne.split("\t")
        if len(champs) >= 2 and champs[0].strip().isdigit():
            table[int(champs[0])] = champs[1].strip()
    return table


def sinks_en_lecture() -> set[str]:
    """Noms des sorties portant au moins un flux de lecture **actif**.

    `pactl list sink-inputs` énumère les flux de lecture ; chaque bloc porte le sink de
    destination (`Sink: <index>`) et son état de pause (`Corked: yes|no`). Un flux
    suspendu ne joue rien — un onglet en pause ne doit pas désigner une sortie.

    Rend un ensemble vide quand rien ne joue : c'est un état parfaitement légitime (une
    réunion physique autour d'un speakerphone n'a aucun flux de lecture), et l'appelant
    doit alors s'en tenir à la sortie par défaut."""
    sortie = _pactl("list", "sink-inputs")
    if not sortie:
        return set()
    noms = _sinks_par_index()
    actifs: set[str] = set()
    index_courant: int | None = None
    suspendu = False
    for ligne in sortie.splitlines():
        depouillee = ligne.strip()
        if depouillee.startswith("Sink Input #"):
            index_courant, suspendu = None, False
        elif depouillee.startswith("Sink:"):
            valeur = depouillee.split(":", 1)[1].strip()
            index_courant = int(valeur) if valeur.isdigit() else None
        elif depouillee.startswith("Corked:"):
            suspendu = depouillee.split(":", 1)[1].strip().lower() == "yes"
            if index_courant is not None and not suspendu and index_courant in noms:
                actifs.add(noms[index_courant])
    return actifs


def sink_a_surveiller(sd) -> str | None:
    """Sortie à capturer : celle où le son se trouve RÉELLEMENT (docs/49 §11).

    `pactl get-default-sink` seul ne suffit pas. Terrain 2026-08-31 : la sortie par
    défaut était les haut-parleurs internes, l'utilisateur travaillait sur un
    speakerphone USB, et le navigateur y routait son flux — 2 h 19 de piste système à
    99,97 % de zéros, sans qu'aucune garde n'ait de raison de broncher (la sortie par
    défaut n'avait pas changé : elle n'était simplement jamais utilisée).

    Politique, du plus sûr au plus utile — jamais de repli aveugle :

    1. rien ne joue nulle part → **sortie par défaut**. C'est le cas d'une réunion
       physique, parfaitement normal : il n'y a rien à capter et rien à deviner ;
    2. la sortie par défaut porte un flux actif → **elle**, sans discussion. Cas le
       plus courant, et comportement identique à celui d'avant ce correctif ;
    3. une seule autre sortie porte des flux → **elle**. C'est le cas de Dario ;
    4. plusieurs autres sorties en portent, et pas la sortie par défaut → **sortie par
       défaut**, avec un WARNING nommant les candidates. Départager au hasard
       (« la première venue ») est exactement ce que `index_moniteur` s'interdit.

    Une sortie retenue dont le moniteur est **invisible de PortAudio** est abandonnée au
    profit de la sortie par défaut : la table n'est pas rafraîchie en cours de réunion
    (cf. en-tête), et il vaut mieux capturer la mauvaise sortie que rien du tout — c'est
    le comportement d'avant ce correctif, on ne régresse pas dessous."""
    defaut = sink_par_defaut()
    try:
        actifs = sinks_en_lecture()
    except Exception as exc:  # noqa: BLE001 — jamais au prix de la réunion
        logger.debug("Flux de lecture illisibles (%s) — sortie par défaut", exc)
        return defaut

    if not actifs or (defaut is not None and defaut in actifs):
        return defaut
    if len(actifs) > 1:
        logger.warning("Plusieurs sorties portent du son (%s) et aucune n'est la sortie "
                       "par défaut (%s) — on s'en tient à la sortie par défaut, "
                       "cf. docs/49 §11", ", ".join(sorted(actifs)), defaut)
        return defaut

    retenu = next(iter(actifs))
    if _index_moniteur(sd, retenu) is None:
        logger.warning("Le son joue sur %r mais son moniteur est invisible de PortAudio "
                       "(sortie apparue après le début de la réunion) — repli sur la "
                       "sortie par défaut %r", retenu, defaut)
        return defaut
    if retenu != defaut:
        logger.info("Le son ne passe pas par la sortie par défaut (%s) mais par %s "
                    "— c'est elle qu'on capture", defaut, retenu)
    return retenu


def _index_moniteur(sd, nom_sink: str) -> int | None:
    """Cœur silencieux de `index_moniteur` — la politique de `sink_a_surveiller`
    l'interroge toutes les 2 s et n'a pas à noyer le journal."""
    attendu = f"{nom_sink}.monitor"
    try:
        hostapis = sd.query_hostapis()
        peripheriques = sd.query_devices()
    except Exception as exc:
        logger.warning("Énumération PortAudio impossible (%s)", exc)
        return None

    def _pulse(d) -> bool:
        i = d.get("hostapi")
        return (i is not None and 0 <= i < len(hostapis)
                and "pulse" in hostapis[i]["name"].lower())

    for index, d in enumerate(peripheriques):
        if d.get("max_input_channels", 0) > 0 and d.get("name") == attendu and _pulse(d):
            return index
    return None


def index_moniteur(sd, nom_sink: str) -> int | None:
    """Index PortAudio de la source `.monitor` du sink donné, ou None.

    Deux constats du spike commandent cette fonction :

    * les moniteurs ne sont visibles que sous le **hostapi PulseAudio** (jamais ALSA,
      qui n'expose que `default`/`sysdefault`/`pipewire`, lesquels n'identifient aucun
      sink) ;
    * le nom PortAudio est **exactement** `<nom du sink>.monitor`.

    Aucun repli sur « le premier moniteur venu » : sur le poste testé, qui a quatre
    sorties, cela aurait capturé une sortie HDMI inactive — une piste système muette,
    sans que rien ne le signale."""
    index = _index_moniteur(sd, nom_sink)
    if index is None:
        logger.warning("Moniteur %r introuvable parmi les périphériques PortAudio "
                       "(sortie apparue après le démarrage de la réunion ?)",
                       f"{nom_sink}.monitor")
    return index


# ── Adaptateur ───────────────────────────────────────────────────────────────────

class CaptureAudioSystemeMonitor(CaptureAudioSysteme):
    def __init__(self) -> None:
        self._buffer: list[np.ndarray] = []
        self._verrou = threading.Lock()
        self._thread: threading.Thread | None = None
        self._arret = threading.Event()
        self._demarre = False
        # Écrit par le rappel PortAudio, lu par le thread de surveillance : une
        # affectation de float est atomique en CPython, un verrou serait du bruit
        # (au pire on comble 0,5 s de trop, ce que le seuil de jitter absorbe).
        self._t_derniere_trame = 0.0
        self._silence_cumule_s = 0.0
        self._dernier_log_silence = 0.0

    @property
    def taux_echantillonnage(self) -> int:
        return TAUX

    def disponible(self) -> bool:
        """Vrai si la sortie par défaut est résolue ET son moniteur visible.

        Chaque échec est journalisé avec sa cause : c'est ce qui décide d'une réunion
        sans piste système, et l'utilisateur est distant (docs/49 L5)."""
        try:
            import sounddevice as sd
            nom_sink = sink_a_surveiller(sd)
            if nom_sink is None:
                logger.warning("Capture système indisponible : `pactl get-default-sink` "
                               "muet (pulseaudio-utils absent, ou aucun serveur audio)")
                return False
            return index_moniteur(sd, nom_sink) is not None
        except Exception as exc:
            logger.warning("Capture système indisponible (%s)", exc, exc_info=True)
            return False

    def demarrer(self) -> None:
        """Idempotent (E-2, docs/33 §2.3) : un second appel sans `arreter()` est un
        no-op loggé, jamais un second flux ouvert."""
        if self._demarre:
            logger.warning("demarrer() appelé alors qu'une capture système était "
                           "déjà en cours — ignoré")
            return
        self._demarre = True
        self._arret.clear()
        with self._verrou:
            self._buffer = []
        self._t_derniere_trame = time.monotonic()
        self._thread = threading.Thread(target=self._boucle, daemon=True,
                                        name="capture-systeme-monitor")
        self._thread.start()

    def arreter(self) -> None:
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
        """Drainage du buffer — mono float32 48 kHz, comme SCK (macOS) et WASAPI."""
        with self._verrou:
            if not self._buffer:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._buffer)
            self._buffer = []
        return audio

    # ── Thread de capture ────────────────────────────────────────────────────────

    def _rappel(self, indata, frames, temps, statut) -> None:  # noqa: ARG002
        if statut:
            # Jamais observé au spike, mais un underflow reste précieux à tracer.
            logger.debug("Capture système : statut PortAudio %s", statut)
        mono = indata.mean(axis=1).astype(np.float32)
        with self._verrou:
            self._buffer.append(mono)
        self._t_derniere_trame = time.monotonic()

    def _combler_silence(self, jusqu_a: float, raison: str, periodique: bool = False) -> None:
        """Injecte des zéros pour couvrir l'intervalle sans trame (docs/48).

        `periodique=True` pour les comblements répétés d'une panne qui dure (un par
        tick) : le silence est bien injecté à chaque fois, mais le journal n'en garde
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

    def _ouvrir(self, sd, nom_sink: str):
        index = index_moniteur(sd, nom_sink)
        if index is None:
            return None
        flux = sd.InputStream(device=index, channels=CANAUX, samplerate=TAUX,
                              blocksize=TAILLE_BLOC, dtype="float32",
                              callback=self._rappel)
        flux.start()
        logger.info("Capture système ouverte sur %r (index %d, %d Hz)",
                    f"{nom_sink}.monitor", index, TAUX)
        return flux

    @staticmethod
    def _fermer(flux) -> None:
        if flux is None:
            return
        try:
            flux.stop()
            flux.close()
        except Exception as exc:
            logger.debug("Fermeture du flux système : %s", exc)

    def _boucle(self) -> None:
        import sounddevice as sd

        flux = None
        sink_courant = sink_a_surveiller(sd)
        ouvert_a = 0.0
        derniere_verif = 0.0
        echecs = 0
        candidat = None            # sortie pressentie, en attente de confirmation
        confirmations = 0

        while not self._arret.is_set():
            maintenant = time.monotonic()
            raison_reouverture: str | None = None

            if flux is None:
                # Pas de flux : la piste doit continuer d'avancer coûte que coûte.
                self._combler_silence(maintenant, "capture système indisponible",
                                      periodique=True)
                raison_reouverture = "ouverture initiale" if echecs == 0 else "nouvelle tentative"
            else:
                if maintenant - derniere_verif >= _INTERVALLE_SURVEILLANCE_S:
                    derniere_verif = maintenant
                    nouveau = sink_a_surveiller(sd)
                    if nouveau is None or nouveau == sink_courant:
                        candidat, confirmations = None, 0
                    else:
                        # Hystérésis : on n'abandonne la sortie courante que sur deux
                        # sondages concordants (cf. _CONFIRMATIONS_AVANT_BASCULE).
                        confirmations = confirmations + 1 if nouveau == candidat else 1
                        candidat = nouveau
                        if confirmations >= _CONFIRMATIONS_AVANT_BASCULE:
                            logger.info("Sortie audio changée : %s → %s",
                                        sink_courant, nouveau)
                            sink_courant = nouveau
                            candidat, confirmations = None, 0
                            raison_reouverture = "changement de sortie"

                # Chien de garde — le SEUL signal quand le sink est détruit : ni
                # exception, ni statut, et `flux.active` reste True (docs/49 §5.1 Q6).
                if (raison_reouverture is None
                        and maintenant - ouvert_a > _GRACE_APRES_OUVERTURE_S
                        and maintenant - self._t_derniere_trame > _SILENCE_AVANT_REOUVERTURE_S):
                    logger.warning("Piste système : aucune trame depuis %.1f s — flux "
                                   "considéré mort (sortie disparue ?), réouverture",
                                   maintenant - self._t_derniere_trame)
                    raison_reouverture = "flux gelé"

            if raison_reouverture is not None:
                self._fermer(flux)
                flux = None
                sink_courant = sink_a_surveiller(sd) or sink_courant
                try:
                    if sink_courant is not None:
                        flux = self._ouvrir(sd, sink_courant)
                except Exception as exc:
                    logger.warning("Capture système : ouverture impossible (%s)", exc,
                                   exc_info=True)
                    flux = None

                if flux is None:
                    echecs += 1
                    if echecs == _ECHECS_MAX_AVANT_SILENCE:
                        # On ne s'arrête pas : la piste continue en silence (le micro
                        # porte la réunion) et une sortie qui revient sera reprise.
                        logger.error("Capture système : %d tentatives infructueuses — "
                                     "piste système tenue en silence, la réunion "
                                     "continue avec le micro", echecs)
                else:
                    if echecs:
                        logger.info("Capture système rétablie après %d échec(s)", echecs)
                    echecs = 0
                    ouvert_a = time.monotonic()
                    # Le temps passé fermé est un trou : il doit être comblé, sinon les
                    # deux pistes se décalent de la durée de la réouverture.
                    self._combler_silence(ouvert_a, raison_reouverture)
                    derniere_verif = ouvert_a

            self._arret.wait(_INTERVALLE_TICK_S)

        self._fermer(flux)
        logger.info("Capture système arrêtée")
