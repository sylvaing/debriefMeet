"""Fabrique de plate-forme — détecte l'OS/matériel et injecte les bons adaptateurs."""
from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass

from debrief_meet.core import mode_transcription
from debrief_meet.platform.interfaces import (
    CaptureMicro,
    CaptureAudioSysteme,
    DemarrageAuto,
    MoteurTranscription,
    PressePapiers,
    RaccourcisGlobaux,
)
from debrief_meet.platform.stubs import (
    DemarrageAutoStub,
    MicroStub,
    MoteurStub,
    PressePapiersStub,
    RaccourcisStub,
    SystemeStub,
)

logger = logging.getLogger(__name__)


@dataclass
class Adaptateurs:
    # None en édition lite (docs/44) : pas de moteur local du tout. Volontairement pas
    # un `MoteurStub` — `GestionnaireDiarization.disponible()` est `moteur is not None`,
    # un stub rendrait donc « Transcrire la réunion » actif et écrirait sa sortie
    # « [stub — pas de transcription réelle] » par-dessus une vraie réunion.
    moteur: MoteurTranscription | None
    micro: CaptureMicro
    systeme: CaptureAudioSysteme
    presse_papiers: PressePapiers
    demarrage_auto: DemarrageAuto
    raccourcis: RaccourcisGlobaux


def _os_courant() -> str:
    s = sys.platform
    if s == "darwin":
        return "macos"
    if s == "win32":
        return "windows"
    return "linux"


def creer_adaptateurs() -> Adaptateurs:
    os_id = _os_courant()

    if os_id == "macos":
        return _macos()
    if os_id == "windows":
        return _windows()
    return _linux()


def _macos() -> Adaptateurs:
    import platform as _plat

    moteur: MoteurTranscription | None
    if not mode_transcription.avec_transcription_locale():
        logger.info("Mode distant — aucun moteur de transcription local")
        moteur = None
    elif _plat.machine() == "arm64":
        try:
            from debrief_meet.platform.macos.moteur_mlx import MoteurMLX
            moteur = MoteurMLX()
        except ImportError:
            moteur = MoteurStub()
    else:
        moteur = MoteurStub()

    try:
        from debrief_meet.platform.commun.micro_sounddevice import CaptureMicroSounddevice
        micro: CaptureMicro = CaptureMicroSounddevice()
    except ImportError:
        micro = MicroStub()

    try:
        from debrief_meet.platform.macos.capture_systeme import CaptureAudioSCK
        systeme: CaptureAudioSysteme = CaptureAudioSCK()
    except ImportError:
        systeme = SystemeStub()

    from debrief_meet.platform.macos.presse_papiers import PressePapiersMaxOS
    from debrief_meet.platform.macos.demarrage_auto import DemarrageAutoMacOS

    raccourcis: RaccourcisGlobaux
    try:
        from debrief_meet.platform.macos.raccourcis_carbon import RaccourcisGlobauxMacOS
        raccourcis = RaccourcisGlobauxMacOS()
    except Exception:
        raccourcis = RaccourcisStub()

    return Adaptateurs(
        moteur=moteur,
        micro=micro,
        systeme=systeme,
        presse_papiers=PressePapiersMaxOS(),
        demarrage_auto=DemarrageAutoMacOS(),
        raccourcis=raccourcis,
    )


def _windows() -> Adaptateurs:
    # Sur Windows, un repli stub est un événement grave (docs/34 §0) : loggé en
    # WARNING avec l'exception d'origine — jamais un silence, seul canal de debug
    # une fois livré à Bastien/Alix.
    # Gate sur le MODE et non sur un `except ImportError` : `moteur_faster_whisper.py`
    # n'importe `faster_whisper` nulle part au niveau module (c'est le sous-processus
    # worker qui le fait), donc un moteur construit à tort ne mourrait qu'à la première
    # transcription (docs/45).
    moteur: MoteurTranscription | None
    if not mode_transcription.avec_transcription_locale():
        logger.info("Mode distant — aucun moteur de transcription local "
                    "(transcription et CR délégués à l'API Mistral)")
        moteur = None
    else:
        try:
            from debrief_meet.platform.windows.moteur_faster_whisper import MoteurFasterWhisper
            moteur = MoteurFasterWhisper()
        except ImportError as exc:
            logger.warning("Moteur Windows indisponible (%s) — repli stub", exc)
            moteur = MoteurStub()

    try:
        from debrief_meet.platform.commun.micro_sounddevice import CaptureMicroSounddevice
        micro: CaptureMicro = CaptureMicroSounddevice()
    except ImportError as exc:
        logger.warning("Micro indisponible (%s) — repli stub", exc)
        micro = MicroStub()

    try:
        from debrief_meet.platform.windows.capture_systeme_wasapi import CaptureAudioSystemeWasapi
        systeme: CaptureAudioSysteme = CaptureAudioSystemeWasapi()
    except ImportError as exc:
        logger.warning("Capture système indisponible (%s) — repli stub", exc)
        systeme = SystemeStub()

    try:
        from debrief_meet.platform.windows.presse_papiers import PressePapiersWindows
        presse_papiers: PressePapiers = PressePapiersWindows()
    except ImportError as exc:
        logger.warning("Presse-papiers indisponible (%s) — repli stub", exc)
        presse_papiers = PressePapiersStub()

    try:
        from debrief_meet.platform.windows.demarrage_auto import DemarrageAutoWindows
        demarrage_auto: DemarrageAuto = DemarrageAutoWindows()
    except ImportError as exc:
        logger.warning("Démarrage auto indisponible (%s) — repli stub", exc)
        demarrage_auto = DemarrageAutoStub()

    raccourcis: RaccourcisGlobaux
    try:
        from debrief_meet.platform.windows.raccourcis_win32 import RaccourcisGlobauxWindows
        raccourcis = RaccourcisGlobauxWindows()
    except Exception as exc:
        logger.warning("Raccourcis indisponibles (%s) — repli stub", exc)
        raccourcis = RaccourcisStub()

    return Adaptateurs(
        moteur=moteur,
        micro=micro,
        systeme=systeme,
        presse_papiers=presse_papiers,
        demarrage_auto=demarrage_auto,
        raccourcis=raccourcis,
    )


def _linux() -> Adaptateurs:
    # Phase 6 (docs/49). Même discipline que `_windows()` : tout repli stub est loggé
    # en WARNING avec l'exception d'origine — l'utilisateur cible est un collègue en
    # production, les logs sont le seul canal de debug.
    #
    # v1 = mode distant seul (décision L1) : aucun moteur local n'est écrit pour
    # Linux. Un utilisateur qui force `mode_transcription: local` obtient le stub —
    # comportement honnête et loggé, plutôt qu'un moteur qui mourrait à la première
    # transcription. Le mode local viendra en remontant le worker faster-whisper de
    # `platform/windows/` dans `platform/commun/` (docs/49 §4.3).
    moteur: MoteurTranscription | None
    if not mode_transcription.avec_transcription_locale():
        logger.info("Mode distant — aucun moteur de transcription local "
                    "(transcription et CR délégués à l'API Mistral)")
        moteur = None
    else:
        logger.warning("Mode local demandé mais aucun moteur local n'existe sur Linux "
                       "(docs/49 L1 : v1 = mode distant seul) — repli stub")
        moteur = MoteurStub()

    try:
        from debrief_meet.platform.commun.micro_sounddevice import CaptureMicroSounddevice
        micro: CaptureMicro = CaptureMicroSounddevice()
    except ImportError as exc:
        logger.warning("Micro indisponible (%s) — repli stub", exc)
        micro = MicroStub()

    # Capture système : source `.monitor` PipeWire — écrite après le spike
    # `spike/capture_monitor_linux/` (docs/49 §5.1, étape 4). Stub jusque-là : la
    # réunion tourne en micro seul, ce qui est déjà un livrable de bout en bout.
    systeme: CaptureAudioSysteme = SystemeStub()
    logger.warning("Capture audio système Linux pas encore implémentée "
                   "(docs/49 §5.1) — repli stub, réunion en micro seul")

    try:
        from debrief_meet.platform.linux.presse_papiers import PressePapiersLinux
        presse_papiers: PressePapiers = PressePapiersLinux()
    except ImportError as exc:
        logger.warning("Presse-papiers indisponible (%s) — repli stub", exc)
        presse_papiers = PressePapiersStub()

    try:
        from debrief_meet.platform.linux.demarrage_auto import DemarrageAutoLinux
        demarrage_auto: DemarrageAuto = DemarrageAutoLinux()
    except ImportError as exc:
        logger.warning("Démarrage auto indisponible (%s) — repli stub", exc)
        demarrage_auto = DemarrageAutoStub()

    # Raccourcis globaux : hors v1 (décision L2). Ubuntu 26.04 est en GNOME Wayland
    # par défaut, où `XGrabKey` ne fonctionne pas ; la voie propre est le portail XDG
    # `org.freedesktop.portal.GlobalShortcuts`. En mode distant, dictée et journal
    # sont de toute façon désactivés — seul le toggle réunion perd son raccourci, et
    # le tray le couvre.
    logger.info("Raccourcis globaux non implémentés sur Linux (docs/49 L2 : "
                "Wayland, reportés au portail XDG) — actions disponibles au tray")

    return Adaptateurs(
        moteur=moteur,
        micro=micro,
        systeme=systeme,
        presse_papiers=presse_papiers,
        demarrage_auto=demarrage_auto,
        raccourcis=RaccourcisStub(),
    )
