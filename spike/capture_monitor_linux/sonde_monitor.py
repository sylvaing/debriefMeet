#!/usr/bin/env python3
"""Spike capture système Linux — sonde des sources `.monitor` PipeWire (docs/49 §5.1).

Exploration ISOLÉE : n'importe rien de `debrief_meet` ni de `benchmark/`. Le but est
de répondre à 5 questions AVANT d'écrire `platform/linux/capture_systeme_monitor.py` :

  Q1 — Quel nom exact portent les sources moniteur vues de PortAudio sur Ubuntu 26.04,
       et sont-elles stables entre deux lancements ?
  Q2 — Faut-il `pactl` pour résoudre la sortie par défaut (⇒ `Depends: pulseaudio-utils`
       dans le .deb) ou l'info est-elle déjà dans PortAudio ?
  Q3 — Quel taux natif et combien de canaux rend le moniteur (le downmix stéréo→mono
       de WASAPI s'applique-t-il pareil) ?
  Q4 — Que devient un flux ouvert quand la sortie par défaut change à chaud
       (erreur PortAudio ? silence ? le flux suit-il tout seul) ?
  Q5 — Le moniteur capte-t-il bien le son des applications (RMS non nul) ?

Protocole GUIDÉ : chaque action attendue de l'utilisateur est annoncée à l'écran, une
à la fois, et attend une validation. Chaque action confirmée devient un marqueur
horodaté dans le log — sans quoi il est impossible, à la relecture, de corréler un
silence ou une erreur avec ce que l'humain venait de faire.

Sortie : `sorties/AAAA-MM-JJ_HH-MM-SS/` contenant `sonde.log`, `phase2_micro.wav`,
`phase2_monitor.wav`, `phase3_monitor.wav`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

try:
    import numpy as np
    import sounddevice as sd
except OSError as exc:  # pragma: no cover
    # `OSError`, PAS `ImportError` : sous Linux, `pip install sounddevice` n'installe
    # que le binding Python — la bibliothèque C PortAudio est un paquet système, et
    # son absence lève « PortAudio library not found » au moment de l'import (même
    # famille que la PortAudioError vue sur le conteneur de build, docs/49 §6.3).
    print(f"\n✗ Il manque une bibliothèque système pour lire le son ({exc}).\n\n"
          "  Installe-la avec :\n\n"
          "      sudo apt install libportaudio2\n\n"
          "  puis relance le test.\n", file=sys.stderr)
    raise SystemExit(2)
except ImportError as exc:  # pragma: no cover — le script s'exécute hors venv de l'app
    print(f"Dépendance Python manquante ({exc}).\n"
          "  python3 -m venv .venv && .venv/bin/pip install sounddevice numpy",
          file=sys.stderr)
    raise SystemExit(2)


# ── Journalisation ───────────────────────────────────────────────────────────────

class Journal:
    """Écrit simultanément à l'écran et dans le fichier de log, toujours horodaté."""

    def __init__(self, chemin: Path) -> None:
        self._fichier = chemin.open("w", encoding="utf-8")

    def _ecrire(self, prefixe: str, message: str) -> None:
        ligne = f"[{dt.datetime.now():%H:%M:%S}] {prefixe}{message}"
        print(ligne, flush=True)
        self._fichier.write(ligne + "\n")
        self._fichier.flush()

    def info(self, message: str) -> None:
        self._ecrire("", message)

    def action(self, message: str) -> None:
        """Marqueur d'action utilisateur — la clé de lecture du log a posteriori."""
        self._ecrire("ACTION  ", message)

    def reponse(self, question: str, message: str) -> None:
        """Réponse à une des 5 questions du spike — grepable en fin d'analyse."""
        self._ecrire(f"REPONSE {question} ", message)

    def erreur(self, message: str) -> None:
        self._ecrire("ERREUR  ", message)

    def fermer(self) -> None:
        self._fichier.close()


def demander(journal: Journal, titre: str, details: list[str] | None = None,
             optionnel: bool = False) -> bool:
    """Annonce UNE action à faire, attend validation, puis la consigne dans le log.

    Le script est envoyé à quelqu'un qui ne connaît ni le projet ni ce qu'on cherche :
    chaque consigne doit être exécutable telle quelle, sans rien deviner. Retourne
    False si l'étape a été sautée (uniquement possible quand `optionnel`)."""
    print()
    print("─" * 72)
    print(f"  ▶ {titre}")
    for ligne in details or []:
        print(f"      {ligne}")
    print("─" * 72)
    invite = "    Entrée quand c'est fait"
    invite += (" — ou tape s puis Entrée pour sauter : " if optionnel else " : ")
    try:
        reponse = input(invite).strip().lower()
    except EOFError:
        print("(entrée non interactive — on continue sans attendre)")
        reponse = ""
    if optionnel and reponse == "s":
        journal.action(f"SAUTÉE — {titre}")
        return False
    journal.action(titre)
    return True


# ── Inventaire (Q1, Q2) ──────────────────────────────────────────────────────────

def _pactl(*args: str) -> str | None:
    if shutil.which("pactl") is None:
        return None
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True,
                              timeout=5, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _est_moniteur(nom: str) -> bool:
    minuscule = nom.lower()
    return "monitor" in minuscule or minuscule.endswith(".monitor")


def inventorier(journal: Journal) -> list[dict]:
    """Liste les périphériques PortAudio, repère les moniteurs, croise avec pactl."""
    journal.info("═══ Phase 1 — inventaire des périphériques ═══")

    journal.info(f"sounddevice {sd.__version__} / PortAudio {sd.get_portaudio_version()[1]}")
    for i, api in enumerate(sd.query_hostapis()):
        journal.info(f"  hostapi[{i}] {api['name']} "
                     f"(défaut in={api['default_input_device']}, out={api['default_output_device']})")

    entrees_moniteur: list[dict] = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        moniteur = _est_moniteur(d["name"])
        journal.info(
            f"  entrée[{i}] {'★ MONITEUR ' if moniteur else ''}{d['name']!r} "
            f"— {d['max_input_channels']}ch @ {int(d['default_samplerate'])} Hz "
            f"(hostapi {d['hostapi']})"
        )
        if moniteur:
            entrees_moniteur.append({"index": i, **{k: d[k] for k in
                                                    ("name", "max_input_channels", "default_samplerate")}})

    if entrees_moniteur:
        journal.reponse("Q1", f"{len(entrees_moniteur)} source(s) moniteur visible(s) de "
                              f"PortAudio : {[m['name'] for m in entrees_moniteur]}")
        premier = entrees_moniteur[0]
        journal.reponse("Q3", f"moniteur natif : {premier['max_input_channels']} canaux @ "
                              f"{int(premier['default_samplerate'])} Hz")
    else:
        journal.reponse("Q1", "AUCUNE source moniteur visible de PortAudio — l'adaptateur "
                              "devra passer par une autre voie (module pulse à charger ? "
                              "API PipeWire native ?)")

    # Q2 — pactl est-il nécessaire pour savoir QUEL moniteur correspond à la sortie active ?
    defaut_sink = _pactl("get-default-sink")
    if defaut_sink is None:
        journal.reponse("Q2", "pactl absent ou en échec — si PortAudio ne suffit pas à "
                              "identifier le bon moniteur, `Depends: pulseaudio-utils` "
                              "devient obligatoire")
    else:
        journal.info(f"pactl get-default-sink → {defaut_sink}")
        journal.info(f"pactl sinks →\n{_pactl('list', 'short', 'sinks') or '(vide)'}")
        journal.info(f"pactl sources →\n{_pactl('list', 'short', 'sources') or '(vide)'}")
        journal.reponse("Q2", f"pactl disponible, sortie par défaut = {defaut_sink} "
                              f"(moniteur attendu : {defaut_sink}.monitor)")

    try:
        index_defaut_out = sd.default.device[1]
        journal.info(f"PortAudio sortie par défaut : [{index_defaut_out}] "
                     f"{sd.query_devices(index_defaut_out)['name']!r}")
    except Exception as exc:
        journal.erreur(f"sortie par défaut PortAudio illisible : {exc}")

    return entrees_moniteur


def choisir_moniteur(journal: Journal, moniteurs: list[dict]) -> int | None:
    """Moniteur correspondant à la sortie par défaut, sinon le premier trouvé."""
    if not moniteurs:
        return None
    defaut_sink = _pactl("get-default-sink")
    if defaut_sink:
        for m in moniteurs:
            # PortAudio expose « Monitor of <description> », pactl rend le nom technique :
            # on tente une correspondance souple avant de retomber sur le premier.
            if defaut_sink.lower() in m["name"].lower():
                journal.info(f"Moniteur retenu (concordance pactl) : [{m['index']}] {m['name']!r}")
                return m["index"]
    journal.info(f"Moniteur retenu (premier de la liste) : [{moniteurs[0]['index']}] "
                 f"{moniteurs[0]['name']!r}")
    return moniteurs[0]["index"]


def rafraichir_peripheriques(journal: Journal) -> None:
    """Force PortAudio à re-scanner les périphériques.

    PortAudio **fige sa table de périphériques à l'initialisation** : un casque
    connecté après le lancement du process reste invisible de `query_devices()`.
    C'est le même piège que celui déjà rencontré côté micro sur macOS (docs/25,
    « table PortAudio figée au lancement ») — et il rend une simple relecture
    inutile. Seul un cycle terminate/initialize rafraîchit la liste.

    Conséquence directe pour l'adaptateur : la source `.monitor` d'une sortie
    apparue en cours de réunion (casque BT allumé, dock branché) n'est atteignable
    qu'après ce cycle."""
    try:
        sd._terminate()
        sd._initialize()
        journal.info("Table PortAudio rafraîchie (terminate/initialize)")
    except Exception as exc:
        journal.erreur(f"Rafraîchissement PortAudio impossible : {exc}")


def resoudre_moniteur_courant(journal: Journal) -> int | None:
    """Ré-inventorie et rend le moniteur de la sortie par défaut À CET INSTANT.

    Indispensable entre deux phases : la sortie par défaut peut avoir changé depuis
    l'inventaire initial (c'est arrivé lors du premier passage terrain, 2026-08-12 —
    le casque BT avait été connecté entre les phases 2 et 3, et la phase 3 a
    enregistré 63 s de silence parfait sur le moniteur devenu inactif)."""
    rafraichir_peripheriques(journal)
    moniteurs = [
        {"index": i, "name": d["name"], "max_input_channels": d["max_input_channels"],
         "default_samplerate": d["default_samplerate"]}
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0 and _est_moniteur(d["name"])
    ]
    journal.info(f"Sortie par défaut à cet instant : {_pactl('get-default-sink')}")
    return choisir_moniteur(journal, moniteurs)


# ── Capture ──────────────────────────────────────────────────────────────────────

class Enregistreur:
    """Capture un périphérique en continu, logge le RMS par tranche d'une seconde."""

    def __init__(self, journal: Journal, index: int, etiquette: str,
                 canaux: int | None = None, taux: int | None = None) -> None:
        self._journal = journal
        self._index = index
        self._etiquette = etiquette
        infos = sd.query_devices(index)
        self._canaux = canaux or min(2, infos["max_input_channels"])
        self._taux = taux or int(infos["default_samplerate"])
        self._blocs: list[np.ndarray] = []
        self._flux: sd.InputStream | None = None
        self._verrou = threading.Lock()

    @property
    def taux(self) -> int:
        return self._taux

    def _rappel(self, indata, frames, temps, statut) -> None:  # noqa: ARG002
        if statut:
            # Underflow/overflow : précieux au moment d'une bascule de périphérique.
            self._journal.erreur(f"{self._etiquette} statut PortAudio : {statut}")
        with self._verrou:
            self._blocs.append(indata.copy())

    def demarrer(self) -> None:
        self._flux = sd.InputStream(
            device=self._index, channels=self._canaux, samplerate=self._taux,
            dtype="float32", callback=self._rappel,
        )
        self._flux.start()
        self._journal.info(f"{self._etiquette} ouvert : device={self._index} "
                           f"{self._canaux}ch @ {self._taux} Hz")

    def rms_recent(self) -> float:
        with self._verrou:
            recents = self._blocs[-20:]
        if not recents:
            return 0.0
        echantillons = np.concatenate(recents, axis=0)
        return float(np.sqrt(np.mean(echantillons.astype(np.float64) ** 2)))

    def arreter(self) -> np.ndarray:
        if self._flux is not None:
            self._flux.stop()
            self._flux.close()
            self._flux = None
        with self._verrou:
            if not self._blocs:
                return np.zeros((0, self._canaux), dtype="float32")
            return np.concatenate(self._blocs, axis=0)

    def ecrire_wav(self, chemin: Path, audio: np.ndarray) -> None:
        if audio.size == 0:
            self._journal.erreur(f"{self._etiquette} : aucun échantillon capturé — pas de WAV")
            return
        pcm = np.clip(audio, -1.0, 1.0)
        with wave.open(str(chemin), "wb") as f:
            f.setnchannels(self._canaux)
            f.setsampwidth(2)
            f.setframerate(self._taux)
            f.writeframes((pcm * 32767).astype("<i2").tobytes())
        duree = len(audio) / self._taux
        self._journal.info(f"{self._etiquette} → {chemin.name} ({duree:.1f} s, "
                           f"RMS global {float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))):.5f})")


def _surveiller(journal: Journal, enregistreurs: dict[str, Enregistreur],
                secondes: int | None, arret: threading.Event) -> None:
    """Logge le RMS de chaque flux une fois par seconde (trace continue à relire).

    `secondes=None` = jusqu'à l'arrêt explicite. Indispensable pour les phases dont la
    durée dépend de l'utilisateur : au premier passage terrain, le veilleur s'est tu
    après 45 s alors que la phase a duré 13 min — toute la trace des transitions
    manquait, et il a fallu la reconstituer depuis le WAV."""
    restant = secondes
    while restant is None or restant > 0:
        if arret.wait(1.0):
            return
        if restant is not None:
            restant -= 1
        mesures = " | ".join(f"{nom} RMS={e.rms_recent():.5f}" for nom, e in enregistreurs.items())
        journal.info(f"  {mesures}")


# ── Phase 2 — capture simultanée micro + moniteur (Q5) ──────────────────────────

def phase_capture(journal: Journal, sortie: Path, index_moniteur: int, secondes: int) -> None:
    journal.info("═══ Phase 2 — capture simultanée micro + moniteur ═══")

    micro = Enregistreur(journal, sd.default.device[0], "micro")
    moniteur = Enregistreur(journal, index_moniteur, "moniteur")

    demander(
        journal,
        "FAIS JOUER DU SON sur cet ordinateur, puis reviens dans ce terminal",
        [
            "Par exemple : ouvre une vidéo YouTube dans ton navigateur et lance-la,",
            "ou ouvre un fichier de musique avec le lecteur de ton choix.",
            "",
            "Important :",
            "  • le son doit sortir des HAUT-PARLEURS de l'ordinateur (pas d'un casque)",
            "  • volume clairement audible, et surtout PAS coupé (pas de mute)",
            "  • LAISSE-LE JOUER pendant toute la mesure : ne mets pas en pause,",
            "    ne ferme pas l'onglet, tu peux juste revenir sur ce terminal.",
        ],
    )
    micro.demarrer()
    moniteur.demarrer()
    print()
    print(f"  ⏺  Mesure en cours pendant {secondes} secondes — ne touche à rien.")
    print("     PARLE À VOIX HAUTE quelques mots pendant ce temps (n'importe quoi :")
    print("     compte jusqu'à dix), pour qu'on distingue ta voix du son de la vidéo.")
    print()
    journal.info(f"Capture de {secondes} s en cours (musique + voix attendues)…")

    arret = threading.Event()
    _surveiller(journal, {"micro": micro, "moniteur": moniteur}, secondes, arret)

    audio_micro = micro.arreter()
    audio_moniteur = moniteur.arreter()
    micro.ecrire_wav(sortie / "phase2_micro.wav", audio_micro)
    moniteur.ecrire_wav(sortie / "phase2_monitor.wav", audio_moniteur)

    rms_moniteur = float(np.sqrt(np.mean(audio_moniteur.astype(np.float64) ** 2))) if audio_moniteur.size else 0.0

    # Seuils : de la musique à volume audible donne un RMS de l'ordre de 0,05. Un
    # seuil à 1e-4 laisserait passer le simple bruit de fond et validerait à tort un
    # moniteur muet — d'où la zone intermédiaire, qui dit « douteux » plutôt que « bon ».
    if rms_moniteur > 1e-2:
        journal.reponse("Q5", f"le moniteur capte bien le son des applications "
                              f"(RMS {rms_moniteur:.5f}) — voie validée")
    elif rms_moniteur > 1e-4:
        journal.reponse("Q5", f"signal DOUTEUX sur le moniteur (RMS {rms_moniteur:.5f}, "
                              f"attendu > 0.01) : volume trop bas, son mis en pause, ou "
                              f"moniteur suivant un sink inactif — ne pas conclure sans "
                              f"écouter phase2_monitor.wav")
        print()
        print("  ⚠  Le son capté est très faible. Si tu avais coupé le son ou mis la")
        print("     vidéo en pause, relance le test : il ne dure que 3 minutes.")
    else:
        journal.reponse("Q5", f"le moniteur est SILENCIEUX (RMS {rms_moniteur:.5f}) alors "
                              f"qu'un son jouait : mauvais périphérique, ou le moniteur "
                              f"suit un sink inactif — à instruire avant l'adaptateur")
        print()
        print("  ⚠  Aucun son n'a été capté. Vérifie que la vidéo jouait bien et que le")
        print("     volume n'était pas coupé, puis relance le test.")


# ── Phase 3 — bascule de sortie à chaud (Q4) ────────────────────────────────────

def phase_bascule(journal: Journal, sortie: Path, index_moniteur: int, secondes: int) -> None:
    journal.info("═══ Phase 3 — bascule de la sortie par défaut, flux ouvert ═══")
    journal.info("C'est LA phase qui dimensionne la logique de réouverture à chaud de "
                 "l'adaptateur : on ne coupe jamais le flux, on observe.")

    poursuivre = demander(
        journal,
        "Prépare un casque USB ou BLUETOOTH — mais NE LE CONNECTE PAS ENCORE",
        [
            "On va observer ce qui se passe quand le son change de destination",
            "PENDANT qu'on enregistre. Il faut donc partir des haut-parleurs.",
            "",
            "  ⚠ TRÈS IMPORTANT : à ce stade, le casque doit être ÉTEINT ou",
            "    DÉBRANCHÉ. Ne l'allume pas, ne le connecte pas : le test te dira",
            "    quand le faire, un peu plus loin.",
            "",
            "Si tu n'as ni casque USB ni casque Bluetooth, saute cette étape : ce",
            "n'est pas grave, les deux premières phases sont déjà utiles.",
        ],
        optionnel=True,
    )
    if not poursuivre:
        journal.reponse("Q4", "NON MESURÉE — étape sautée faute de casque disponible")
        return

    demander(
        journal,
        "REMETS DU SON EN LECTURE sur les HAUT-PARLEURS, puis reviens ici",
        [
            "Même chose qu'à l'étape précédente : une vidéo YouTube ou un morceau",
            "de musique, son audible sur les haut-parleurs de l'ordinateur.",
            "Laisse-le jouer jusqu'à la fin de cette phase (environ 1 minute).",
        ],
    )

    # Le moniteur est RE-RÉSOLU ici, et pas repris de la phase 1 : la sortie par
    # défaut a pu changer entre-temps. C'est précisément ce qui a invalidé le premier
    # passage terrain (2026-08-12) — le casque BT avait été connecté pendant l'attente,
    # et la phase 3 a enregistré 63 s de silence sur le moniteur de l'ancienne sortie.
    index_courant = resoudre_moniteur_courant(journal)
    if index_courant is None:
        journal.erreur("Aucun moniteur exploitable au moment de la phase 3 — abandon")
        journal.reponse("Q4", "NON MESURÉE — plus aucun moniteur visible")
        return
    if index_courant != index_moniteur:
        journal.info(f"Moniteur différent de celui de la phase 2 "
                     f"([{index_moniteur}] → [{index_courant}]) : la sortie par défaut "
                     f"a changé entre les deux phases")

    moniteur = Enregistreur(journal, index_courant, "moniteur")
    moniteur.demarrer()
    avant = _pactl("get-default-sink")
    journal.info(f"Sortie par défaut au démarrage du flux : {avant}")
    journal.info(f"État des sinks au démarrage :\n{_pactl('list', 'short', 'sinks') or '(vide)'}")

    # Vérification immédiate : si le moniteur choisi est déjà muet alors qu'une musique
    # est censée jouer, inutile de dérouler la phase — on le dit tout de suite.
    time.sleep(2)
    if moniteur.rms_recent() < 1e-4:
        print()
        print("  ⚠  Le moniteur ne capte rien alors qu'une musique devrait jouer.")
        print("     Vérifie que le son sort bien des HAUT-PARLEURS (pas d'un casque")
        print("     déjà connecté) et que la lecture est en cours, puis relance :")
        print("         sh lancer.sh --phases 3")
        journal.erreur("Moniteur muet au démarrage de la phase 3 — mesure non valable")

    arret = threading.Event()
    veilleur = threading.Thread(
        target=_surveiller, args=(journal, {"moniteur": moniteur}, None, arret), daemon=True)
    veilleur.start()

    print()
    print("  ⏺  Enregistrement démarré — il ne s'arrête plus jusqu'à la fin de la phase.")
    time.sleep(min(5, secondes))
    demander(
        journal,
        "BRANCHE LE CASQUE MAINTENANT (sans rien arrêter d'autre)",
        [
            "Casque USB : branche-le sur un port USB.",
            "Casque Bluetooth : allume-le / connecte-le depuis le menu Bluetooth.",
            "",
            "Le son de la vidéo doit basculer dans le casque (les haut-parleurs se",
            "taisent). Si Ubuntu te demande quoi faire, choisis d'utiliser le casque.",
            "Ne mets PAS la vidéo en pause, ne ferme pas ce terminal.",
        ],
    )
    apres = _pactl("get-default-sink")
    journal.info(f"Sortie par défaut après branchement : {apres} "
                 f"({'CHANGÉE' if apres != avant else 'INCHANGÉE — le casque n a pas pris la main'})")
    journal.info(f"État des sinks après branchement :\n{_pactl('list', 'short', 'sinks') or '(vide)'}")
    # La question décisive : le sink que l'on surveille existe-t-il encore ? Un sink
    # simplement SUSPENDED rend du silence ; un sink DISPARU peut tuer le flux.
    if avant and apres and avant != apres:
        sinks = _pactl("list", "short", "sinks") or ""
        journal.info(f"Ancien sink toujours présent : {'OUI' if avant in sinks else 'NON — NŒUD DISPARU'}")
    print("  ⏺  On continue d'enregistrer quelques secondes, ne touche à rien…")
    time.sleep(min(8, secondes))

    demander(
        journal,
        "DÉBRANCHE LE CASQUE (le son doit revenir dans les haut-parleurs)",
        [
            "Casque USB : retire-le du port USB.",
            "Casque Bluetooth : éteins-le, ou déconnecte-le depuis le menu Bluetooth.",
        ],
    )
    retour = _pactl("get-default-sink")
    journal.info(f"Sortie par défaut après débranchement : {retour}")
    print("  ⏺  Dernières secondes d'enregistrement, ne touche à rien…")
    time.sleep(min(5, secondes))

    arret.set()
    veilleur.join(timeout=2)
    audio = moniteur.arreter()
    moniteur.ecrire_wav(sortie / "phase3_monitor.wav", audio)

    journal.reponse("Q4", "à conclure en relisant les RMS par seconde ci-dessus, alignés "
                          "sur les marqueurs ACTION : le flux a-t-il continué à rendre du "
                          "son après la bascule (il suit tout seul), est-il passé à "
                          "RMS≈0 (moniteur devenu muet → réouverture nécessaire), ou "
                          "PortAudio a-t-il remonté une erreur/un statut ?")


# ── Phase 4 — le sink surveillé DISPARAÎT (Q6), sans matériel ni manipulation ───

def phase_sink_disparu(journal: Journal, secondes: int) -> None:
    """Q6 — que devient un flux dont le sink surveillé est DÉTRUIT sous ses pieds ?

    Cas réel le plus probable en réunion : l'utilisateur porte un casque Bluetooth
    (donc on capture le moniteur du sink `bluez_output.*`) et le casque se
    déconnecte — batterie vide, sortie de portée. Le nœud PipeWire disparaît, ce qui
    n'est PAS la même chose qu'un sink simplement inactif (mesuré en phase 3 : silence
    numérique, flux intact).

    Simulé avec `module-null-sink`, un sink virtuel qu'on crée puis détruit à volonté :
    aucune manipulation humaine — les deux passages terrain précédents ont échoué
    exactement là-dessus — et aucun matériel requis.

    Le sink créé n'est **jamais** défini comme sortie par défaut : la configuration
    audio de la machine n'est pas touchée, et le module est déchargé même en cas
    d'erreur."""
    journal.info("═══ Phase 4 — disparition du sink surveillé (automatique) ═══")

    if shutil.which("pactl") is None:
        journal.erreur("pactl absent — phase 4 impossible")
        journal.reponse("Q6", "NON MESURÉE — pactl absent")
        return

    nom_sink = "debriefmeet_sonde"
    id_module = _pactl("load-module", "module-null-sink", f"sink_name={nom_sink}")
    if not id_module or not id_module.strip().isdigit():
        journal.erreur(f"Création du sink virtuel impossible (retour : {id_module!r})")
        journal.reponse("Q6", "NON MESURÉE — module-null-sink indisponible")
        return
    journal.info(f"Sink virtuel « {nom_sink} » créé (module {id_module.strip()})")

    flux = None
    try:
        rafraichir_peripheriques(journal)
        index = next((i for i, d in enumerate(sd.query_devices())
                      if d["max_input_channels"] > 0 and nom_sink in d["name"]), None)
        if index is None:
            journal.erreur(f"Moniteur de « {nom_sink} » introuvable côté PortAudio "
                           "après rafraîchissement")
            journal.reponse("Q6", "NON MESURÉE — moniteur du sink virtuel invisible")
            return
        journal.info(f"Moniteur du sink virtuel : [{index}] {sd.query_devices(index)['name']!r}")

        # On ne compte pas le son (le sink virtuel est muet) mais la VIE du flux :
        # les rappels continuent-ils d'arriver après la destruction du sink ?
        blocs = {"n": 0, "trames": 0}
        incidents: list[str] = []

        def _rappel(indata, frames, temps, statut):  # noqa: ARG001
            blocs["n"] += 1
            blocs["trames"] += frames
            if statut:
                incidents.append(f"statut PortAudio : {statut}")

        flux = sd.InputStream(device=index, channels=2, samplerate=48_000,
                              dtype="float32", callback=_rappel)
        flux.start()
        journal.info(f"Flux ouvert sur le moniteur virtuel — actif={flux.active}")

        time.sleep(3)
        avant = dict(blocs)
        journal.info(f"Avant destruction : {avant['n']} rappels, {avant['trames']} trames, "
                     f"actif={flux.active}")

        journal.action(f"DESTRUCTION du sink « {nom_sink} » (simule un casque déconnecté)")
        _pactl("unload-module", id_module.strip())
        id_module = None  # déchargé : ne pas retenter dans le finally

        for i in range(max(3, min(secondes, 10))):
            time.sleep(1)
            journal.info(f"  +{i+1}s après destruction : {blocs['n']} rappels cumulés, "
                         f"{blocs['trames']} trames, actif={flux.active}, "
                         f"incidents={len(incidents)}")

        apres = dict(blocs)
        vivant = apres["trames"] > avant["trames"]
        journal.reponse(
            "Q6",
            f"sink détruit sous un flux ouvert → "
            f"{'le flux CONTINUE de livrer des trames' if vivant else 'le flux NE LIVRE PLUS rien'}"
            f" ; actif={flux.active} ; incidents PortAudio : "
            f"{incidents or 'AUCUN'} ; trames {avant['trames']} → {apres['trames']}")
    except Exception as exc:
        # Une exception ICI est en soi la réponse : le flux meurt bruyamment.
        journal.reponse("Q6", f"sink détruit sous un flux ouvert → EXCEPTION {exc!r} "
                              "(l'adaptateur doit la rattraper et rouvrir)")
        journal.erreur(traceback_court())
    finally:
        if flux is not None:
            try:
                flux.stop()
                flux.close()
                journal.info("Flux refermé sans erreur")
            except Exception as exc:
                journal.reponse("Q6bis", f"la FERMETURE du flux lève après disparition "
                                         f"du sink : {exc!r}")
        if id_module:
            _pactl("unload-module", id_module.strip())
            journal.info("Sink virtuel retiré (nettoyage)")


def traceback_court() -> str:
    import traceback
    return traceback.format_exc()


# ── Point d'entrée ───────────────────────────────────────────────────────────────

def main() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--secondes", type=int, default=15,
                         help="durée de la capture de la phase 2 (défaut : 15)")
    parseur.add_argument("--phases", default="1,2,3,4",
                         help="phases à jouer, séparées par des virgules (défaut : 1,2,3,4). "
                              "La phase 4 est entièrement automatique.")
    args = parseur.parse_args()
    phases = {p.strip() for p in args.phases.split(",")}

    racine = Path(__file__).parent / "sorties" / f"{dt.datetime.now():%Y-%m-%d_%H-%M-%S}"
    racine.mkdir(parents=True, exist_ok=True)
    journal = Journal(racine / "sonde.log")

    journal.info(f"Spike capture moniteur Linux — sortie : {racine}")
    journal.info(f"Python {sys.version.split()[0]} / plate-forme {sys.platform}")
    for variable in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "PIPEWIRE_RUNTIME_DIR"):
        import os
        journal.info(f"  {variable}={os.environ.get(variable, '(absent)')}")
    version_pw = _pactl("info")
    if version_pw:
        for ligne in version_pw.splitlines():
            if "Server Name" in ligne or "Server Version" in ligne:
                journal.info(f"  {ligne.strip()}")

    code = 0
    try:
        moniteurs = inventorier(journal)
        index = choisir_moniteur(journal, moniteurs)
        if index is None:
            journal.erreur("Aucun moniteur exploitable — phases 2 et 3 sautées. "
                           "Vérifier `pactl list short sources` et la config PipeWire.")
            code = 1
        else:
            if "2" in phases:
                phase_capture(journal, racine, index, args.secondes)
            if "3" in phases:
                phase_bascule(journal, racine, index, args.secondes)
        # Phase 4 indépendante des précédentes : elle crée son propre sink, donc elle
        # tourne même si aucun moniteur matériel n'est exploitable.
        if "4" in phases:
            phase_sink_disparu(journal, args.secondes)
    except KeyboardInterrupt:
        journal.erreur("Interrompu par l'utilisateur (Ctrl+C)")
        code = 130
    except Exception as exc:  # le spike ne doit jamais mourir sans laisser de trace
        journal.erreur(f"Exception non rattrapée : {exc!r}")
        import traceback
        journal.erreur(traceback.format_exc())
        code = 1

    journal.info("═══ Terminé ═══")
    journal.fermer()

    # Un seul fichier à renvoyer plutôt qu'un dossier : moins d'occasions de se
    # tromper pour quelqu'un qui exécute ça une seule fois.
    archive = shutil.make_archive(str(racine), "zip", root_dir=racine.parent,
                                 base_dir=racine.name)

    print()
    print("═══════════════════════════════════════════════════════════════════════")
    if code == 0:
        print("  C'est terminé, merci !")
    else:
        print("  Le test s'est arrêté avant la fin — ce n'est pas grave.")
        print("  Ce qui a été mesuré jusque-là est utile, envoie-le quand même.")
    print()
    print("  UN SEUL FICHIER À RENVOYER À SYLVAIN :")
    print(f"    {archive}")
    print()
    print("  Il contient le journal de la mesure et les enregistrements audio")
    print("  (uniquement ce qui a été capté pendant les phases ci-dessus).")
    print("═══════════════════════════════════════════════════════════════════════")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
