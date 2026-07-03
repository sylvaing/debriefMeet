"""Validation guidée de la capture audio système + AEC.

Scénario interactif en console (le bench ne tourne qu'une fois → on guide
l'utilisateur et on logge tout). Chaque étape est skippable et isolée : un
échec dégrade le rapport, ne casse jamais le run. `auto_skip=True` permet de
tout sauter (tests / exécution non-interactive).

La capture système (loopback) est la partie la plus divergente entre OS :
- Windows : WASAPI loopback via la lib `soundcard` (PortAudio/sounddevice n'expose
  aucun flag loopback) ;
- Linux : source « monitor » de PipeWire/PulseAudio (pactl + parec) ;
- macOS : non géré nativement (nécessite un périphérique virtuel) → étape sautée.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np

from benchmark import materiel
from benchmark.journalisation import journal

SR_SONDE = 48_000        # taux natif courant des sorties (on relèvera le réel)
SEUIL_SON = 0.005        # RMS au-delà duquel on considère « du son capté »

TEXTE_REFERENCE = (
    "Le renard brun et rapide saute par-dessus le chien paresseux. "
    "Cette phrase sert à mesurer la qualité de la transcription du micro, "
    "avant et après l'annulation d'écho."
)


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) if len(audio) else 0.0


def _vers_mono(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    return audio.mean(axis=1) if audio.ndim == 2 else audio


def demander(prompt: str, auto_skip: bool) -> str | None:
    """Affiche une consigne et attend l'utilisateur. None si auto_skip (non-interactif)."""
    journal().info(prompt)
    if auto_skip:
        journal().debug("auto_skip → étape sautée")
        return None
    try:
        return input("  → " + prompt + " [Entrée pour continuer, 'n' pour sauter] ")
    except (EOFError, KeyboardInterrupt):
        return None


def lister_peripheriques() -> list[dict]:
    """Inventaire des périphériques audio (jamais d'exception)."""
    try:
        import sounddevice as sd

        defaut_in, defaut_out = sd.default.device
        out = []
        for i, d in enumerate(sd.query_devices()):
            nom = d.get("name", "")
            out.append({
                "index": i,
                "nom": nom,
                "canaux_entree": d.get("max_input_channels", 0),
                "canaux_sortie": d.get("max_output_channels", 0),
                "monitor": "monitor" in nom.lower(),
                "bluetooth": any(m in nom.lower() for m in ("bluetooth", "airpods", "bt")),
                "defaut_entree": i == defaut_in,
                "defaut_sortie": i == defaut_out,
            })
        return out
    except Exception:
        journal().debug("sounddevice indisponible : périphériques non listés", exc_info=True)
        return []


# ── Capture loopback Linux via PipeWire/PulseAudio (pactl + parec) ──────────────
#
# PortAudio (sounddevice) n'expose quasiment jamais les sources « monitor » de
# PipeWire/PulseAudio → la détection par nom de device échoue (faux négatif).
# On passe donc par les outils Pulse/PipeWire : `pactl` pour trouver le monitor,
# `parec` pour capturer (marche sur PulseAudio ET PipeWire via pipewire-pulse).

def _monitor_depuis_pactl(default_sink: str, sources_short: str) -> str | None:
    """Nom de la source monitor à capturer, depuis les sorties `pactl`.

    Priorité au monitor du **sink par défaut** (`<sink>.monitor`) ; sinon la 1ʳᵉ
    source dont le nom finit par `.monitor`. None si aucune."""
    monitors: list[str] = []
    for ligne in (sources_short or "").splitlines():
        champs = ligne.split("\t")        # <index>\t<nom>\t<module>\t<format>\t<état>
        if len(champs) >= 2 and champs[1].endswith(".monitor"):
            monitors.append(champs[1])
    cible = (default_sink or "").strip()
    if cible and (cible + ".monitor") in monitors:
        return cible + ".monitor"
    return monitors[0] if monitors else None


def _cmd_parec(monitor: str, sr: int, canaux: int) -> list[str]:
    """Commande `parec` capturant un monitor en PCM float32le brut sur stdout."""
    return ["parec", "--device=" + monitor, "--format=float32le",
            "--rate=" + str(sr), "--channels=" + str(canaux)]


def _decoder_pcm_f32(data: bytes, canaux: int) -> np.ndarray:
    """Octets PCM float32le → tableau (N, canaux) (ou (N,) si mono)."""
    a = np.frombuffer(data, dtype="<f4")
    if canaux > 1:
        n = (len(a) // canaux) * canaux
        return np.ascontiguousarray(a[:n].reshape(-1, canaux)).astype(np.float32)
    return a.astype(np.float32)


def _lire_n(stream, n: int, deadline_s: float) -> bytes:
    """Lit jusqu'à `n` octets d'un flux, borné par `deadline_s` (best-effort)."""
    buf = bytearray()
    fin = time.monotonic() + deadline_s
    while len(buf) < n and time.monotonic() < fin:
        chunk = stream.read(min(65536, n - len(buf)))
        if not chunk:
            break
        buf += chunk
    return bytes(buf)


def _capturer_via_parec(duree: float, sr: int = SR_SONDE, canaux: int = 2) -> dict | None:
    """Capture le monitor via pactl+parec. None si les outils/le monitor manquent."""
    import shutil
    import subprocess

    if not (shutil.which("pactl") and shutil.which("parec")):
        return None

    def _pactl(args: list[str]) -> str:
        try:
            return subprocess.run(["pactl", *args], capture_output=True,
                                  text=True, timeout=5).stdout
        except Exception:
            journal().debug("pactl %s a échoué", args, exc_info=True)
            return ""

    monitor = _monitor_depuis_pactl(_pactl(["get-default-sink"]),
                                    _pactl(["list", "sources", "short"]))
    if not monitor:
        return None

    proc = subprocess.Popen(_cmd_parec(monitor, sr, canaux),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        data = _lire_n(proc.stdout, int(duree * sr) * canaux * 4, duree + 3)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
    audio = _decoder_pcm_f32(data, canaux)
    return {"audio": _vers_mono(audio), "sr": sr, "canaux": canaux,
            "methode": "parec-monitor:" + monitor, "dtype": "float32"}


def _capturer_loopback_windows(duree: float, sr: int = SR_SONDE) -> dict:
    """Capture le son système Windows via WASAPI loopback (bibliothèque `soundcard`).

    sounddevice/PortAudio **n'expose aucun flag loopback** WASAPI (`WasapiSettings`
    ne connaît qu'`exclusive`/`auto_convert`/`explicit_sample_format`, et la demande
    upstream traîne ouverte depuis 2020) → impossible par cette voie. `soundcard` ouvre
    le **haut-parleur par défaut comme micro loopback** (`include_loopback=True`) et lit
    les frames jouées. cf. docs/08-benchmark.md § « Capture loopback Windows ».

    ⚠ On capture en **stéréo puis on downmixe** : sur WASAPI, `soundcard` renvoie du
    bruit si on lui demande explicitement **un seul** canal (bug documenté). On laisse
    donc le nombre de canaux du périphérique (≥2) et `_vers_mono` réduit ensuite."""
    import soundcard as sc

    hp = sc.default_speaker()
    if hp is None:
        raise RuntimeError("aucun haut-parleur par défaut (capture loopback impossible)")
    mic = sc.get_microphone(hp.name, include_loopback=True)
    if mic is None:
        raise RuntimeError(f"pas de micro loopback pour « {hp.name} »")
    audio = np.asarray(mic.record(samplerate=sr, numframes=int(duree * sr)),
                       dtype=np.float32)
    canaux = audio.shape[1] if audio.ndim == 2 else 1
    return {"audio": _vers_mono(audio), "sr": sr, "canaux": canaux,
            "methode": "wasapi-loopback(soundcard)", "dtype": "float32"}


def _enregistrer_systeme(duree: float) -> dict:
    """Capture le son système (loopback) selon l'OS. Retourne audio + format réel + méthode."""
    import sounddevice as sd

    osys = materiel.os_normalise()
    methode = None
    audio = None
    sr = SR_SONDE
    canaux = 2

    if osys == "windows":
        # WASAPI loopback via soundcard (sounddevice/PortAudio ne sait pas le faire).
        return _capturer_loopback_windows(duree)
    elif osys == "linux":
        # Voie principale : pactl + parec (PipeWire/PulseAudio). Robuste, contrairement
        # à PortAudio qui n'expose pas les monitors.
        cap = _capturer_via_parec(duree)
        if cap is not None:
            return cap
        # Repli : ancienne méthode sounddevice (monitor exposé par nom — rare).
        methode = "sounddevice-monitor"
        moniteur = next((d for d in lister_peripheriques()
                         if d["monitor"] and d["canaux_entree"] > 0), None)
        if moniteur is None:
            raise RuntimeError(
                "aucune source monitor : ni pactl/parec, ni périphérique PortAudio « monitor » "
                "(installer pipewire-pulse/pulseaudio-utils, ou vérifier qu'un son joue)")
        info = sd.query_devices(moniteur["index"])
        sr = int(info.get("default_samplerate") or SR_SONDE)
        canaux = max(1, moniteur["canaux_entree"])
        audio = sd.rec(int(duree * sr), samplerate=sr, channels=canaux,
                       dtype="float32", device=moniteur["index"])
        sd.wait()
    else:
        raise RuntimeError(f"capture système non gérée sur {osys} (périphérique virtuel requis)")

    mono = _vers_mono(audio)
    return {
        "audio": mono, "sr": sr, "canaux": canaux, "methode": methode,
        "dtype": "float32",
    }


def _enregistrer_micro(duree: float) -> dict:
    import sounddevice as sd

    defaut_in = sd.default.device[0]
    info = sd.query_devices(defaut_in)
    sr = int(info.get("default_samplerate") or 44_100)
    audio = sd.rec(int(duree * sr), samplerate=sr, channels=1, dtype="float32", device=defaut_in)
    sd.wait()
    return {"audio": _vers_mono(audio), "sr": sr, "canaux": 1, "dtype": "float32"}


# ── Étapes du scénario ────────────────────────────────────────────────────────

def etape_youtube(auto_skip: bool, duree: float) -> dict:
    rep = demander(
        "Ouvre un navigateur et lance une vidéo YouTube avec du son, puis valide.",
        auto_skip)
    if rep is None or rep.strip().lower() == "n":
        return {"realise": False}
    try:
        cap = _enregistrer_systeme(duree)
        rms = _rms(cap["audio"])
        res = {"realise": True, "son_capte": rms > SEUIL_SON, "rms": round(rms, 5),
               "methode": cap["methode"],
               "format_capte": {"sample_rate": cap["sr"], "canaux": cap["canaux"],
                                "dtype": cap["dtype"]}}
        journal().info("  capture système : RMS=%.5f → %s (%s)", rms,
                       "SON CAPTÉ" if res["son_capte"] else "MUET", cap["methode"])
        return res
    except Exception as exc:
        journal().warning("  capture système : ÉCHEC (%s)", exc, exc_info=True)
        return {"realise": True, "erreur": str(exc)}


def etape_lecture_voix(auto_skip: bool, duree: float,
                       transcrire_fn: Callable[[np.ndarray], str] | None) -> dict:
    rep = demander(
        f"Pendant que la vidéo joue, lis ce texte à voix haute :\n    « {TEXTE_REFERENCE} »",
        auto_skip)
    if rep is None or rep.strip().lower() == "n":
        return {"realise": False}
    try:
        micro = systeme = None

        def _rec_sys():
            nonlocal systeme
            systeme = _enregistrer_systeme(duree)

        def _rec_mic():
            nonlocal micro
            micro = _enregistrer_micro(duree)

        t_sys = threading.Thread(target=_rec_sys)
        t_mic = threading.Thread(target=_rec_mic)
        t_sys.start(); t_mic.start()
        t_sys.join(); t_mic.join()

        res: dict = {"realise": True}
        if micro is None:
            return {"realise": True, "erreur": "micro non capturé"}

        # AEC : nettoie le micro avec le système comme référence.
        attenuation = None
        micro_nettoye = None
        if systeme is not None:
            try:
                from debrief_meet.core.aec import ProcesseurAEC

                proc = ProcesseurAEC(sr_micro=micro["sr"], sr_systeme=systeme["sr"])
                proc.demarrer()
                micro_nettoye = proc.pousser(micro["audio"], systeme["audio"])
                attenuation = proc.derniere_attenuation_db
                proc.terminer()
            except Exception as exc:
                journal().warning("  AEC : ÉCHEC (%s)", exc, exc_info=True)
        res["attenuation_echo_db"] = (round(attenuation, 1)
                                      if attenuation not in (None, float("-inf")) else attenuation)

        # WER avant/après AEC (si une fonction de transcription est fournie).
        if transcrire_fn is not None:
            from benchmark import qualite
            from debrief_meet.core.audio import reechantillonner

            brut16 = reechantillonner(micro["audio"], micro["sr"])
            res["wer_avant_aec"] = round(qualite.wer(TEXTE_REFERENCE, transcrire_fn(brut16)), 4)
            if micro_nettoye is not None and len(micro_nettoye):
                res["wer_apres_aec"] = round(
                    qualite.wer(TEXTE_REFERENCE, transcrire_fn(micro_nettoye)), 4)
        return res
    except Exception as exc:
        journal().warning("  lecture voix : ÉCHEC (%s)", exc, exc_info=True)
        return {"realise": True, "erreur": str(exc)}


def sonde_livekit() -> dict:
    """Disponibilité de l'AEC3 (livekit) sur cet OS : import + instanciation."""
    res: dict = {"disponible": False, "version": None, "plateforme_wheel": None}
    try:
        from importlib.metadata import version
        try:
            res["version"] = version("livekit")
        except Exception:
            pass
        from livekit import rtc

        rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=False,
                                  high_pass_filter=True)
        res["disponible"] = True
    except Exception as exc:
        journal().debug("livekit indisponible", exc_info=True)
        res["erreur"] = str(exc)
    try:
        import sysconfig
        res["plateforme_wheel"] = sysconfig.get_platform()
    except Exception:
        pass
    return res


def scenario(auto_skip: bool = False, duree: float = 6.0,
             transcrire_fn: Callable[[np.ndarray], str] | None = None) -> dict:
    """Déroule le scénario guidé complet et renvoie le bloc 'capture' du rapport."""
    log = journal()
    log.info("=== Validation capture audio système + AEC ===")
    if materiel.os_normalise() == "macos" and not auto_skip:
        log.info("(macOS : capture système non gérée nativement — sondes informatives)")
    youtube = etape_youtube(auto_skip, duree)
    lecture_voix = etape_lecture_voix(auto_skip, duree, transcrire_fn)
    # Plus aucune étape n'a besoin du son système → on libère l'utilisateur.
    if not auto_skip:
        log.info("✓ Phase capture terminée — tu peux ARRÊTER / fermer la vidéo YouTube. "
                 "La suite (transcription) est automatique et peut être longue : "
                 "rien d'autre à faire.")
    return {
        "youtube": youtube,
        "lecture_voix": lecture_voix,
        "peripheriques": lister_peripheriques(),
        "aec_livekit": sonde_livekit(),
    }
