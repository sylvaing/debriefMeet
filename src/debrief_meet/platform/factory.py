"""Fabrique de plate-forme — détecte l'OS/matériel et injecte les bons adaptateurs."""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

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


@dataclass
class Adaptateurs:
    moteur: MoteurTranscription
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

    moteur: MoteurTranscription
    if _plat.machine() == "arm64":
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
    # Phase 5 : MoteurFasterWhisper, WASAPI, Registre
    return Adaptateurs(
        moteur=MoteurStub(),
        micro=MicroStub(),
        systeme=SystemeStub(),
        presse_papiers=PressePapiersStub(),
        demarrage_auto=DemarrageAutoStub(),
        raccourcis=RaccourcisStub(),
    )


def _linux() -> Adaptateurs:
    # Phase 6 : MoteurFasterWhisper, PipeWire, systemd
    return Adaptateurs(
        moteur=MoteurStub(),
        micro=MicroStub(),
        systeme=SystemeStub(),
        presse_papiers=PressePapiersStub(),
        demarrage_auto=DemarrageAutoStub(),
        raccourcis=RaccourcisStub(),
    )
