"""Collecte d'informations système pour l'en-tête de session et le diagnostic (docs/31 §3.4).

Vit dans `platform/` (pas `core/`) : la collecte est OS-spécifique (RAM/GPU Windows via
ctypes/PowerShell). Ne lève jamais — chaque rubrique en échec devient une chaîne
"indisponible (<exc>)" plutôt que de faire échouer tout l'en-tête de session.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys

from debrief_meet.core import mode_transcription


def _est_windows() -> bool:
    return sys.platform == "win32"


def _est_linux() -> bool:
    return sys.platform.startswith("linux")


def _version_lib(nom_distribution: str) -> str:
    try:
        return importlib.metadata.version(nom_distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        return f"indisponible ({exc})"


def _peripheriques_audio() -> tuple[str, str]:
    try:
        import sounddevice as sd

        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
        defaut = sd.default.device
        defaut_in, defaut_out = defaut if isinstance(defaut, (list, tuple)) else (defaut, defaut)

        entrees, sorties = [], []
        for i, d in enumerate(devices):
            idx_hostapi = d.get("hostapi")
            nom_hostapi = (
                hostapis[idx_hostapi]["name"]
                if idx_hostapi is not None and 0 <= idx_hostapi < len(hostapis)
                else "?"
            )
            taux = int(d.get("default_samplerate", 0) or 0)
            if d.get("max_input_channels", 0) > 0:
                marque = " [défaut]" if i == defaut_in else ""
                entrees.append(
                    f"[{i}] {d['name']} ({nom_hostapi}) {taux}Hz {d['max_input_channels']}ch{marque}"
                )
            if d.get("max_output_channels", 0) > 0:
                marque = " [défaut]" if i == defaut_out else ""
                sorties.append(
                    f"[{i}] {d['name']} ({nom_hostapi}) {taux}Hz {d['max_output_channels']}ch{marque}"
                )
        return (" | ".join(entrees) or "aucun", " | ".join(sorties) or "aucun")
    except Exception as exc:
        indispo = f"indisponible ({exc})"
        return indispo, indispo


def _ram_go_windows() -> str:
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = _MemoryStatusEx()
        stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
        return str(round(stat.ullTotalPhys / (1024**3), 1))
    except Exception as exc:
        return f"indisponible ({exc})"


def _gpu_windows() -> str:
    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        resultat = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json",
            ],
            capture_output=True, text=True, timeout=10, creationflags=creationflags,
        )
        data = json.loads(resultat.stdout)
        cartes = data if isinstance(data, list) else [data]
        return " | ".join(
            f"{c.get('Name', '?')} (driver {c.get('DriverVersion', '?')})" for c in cartes
        ) or "aucune"
    except Exception as exc:
        return f"indisponible ({exc})"


def _ram_go_linux() -> str:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for ligne in f:
                if ligne.startswith("MemTotal:"):
                    return str(round(int(ligne.split()[1]) / (1024**2), 1))
        return "indisponible (MemTotal absent)"
    except Exception as exc:
        return f"indisponible ({exc})"


def _distro_linux() -> str:
    """Nom lisible de la distribution — `platform.platform()` ne rend que le noyau."""
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for ligne in f:
                if ligne.startswith("PRETTY_NAME="):
                    return ligne.split("=", 1)[1].strip().strip('"')
        return "indisponible (PRETTY_NAME absent)"
    except Exception as exc:
        return f"indisponible ({exc})"


def _session_linux() -> str:
    """Wayland ou X11, et quel bureau — détermine ce qui est possible côté tray et
    raccourcis globaux (docs/49 L2), donc à avoir sous les yeux dans tout diagnostic."""
    type_session = os.environ.get("XDG_SESSION_TYPE") or "inconnu"
    bureau = os.environ.get("XDG_CURRENT_DESKTOP") or "inconnu"
    return f"{type_session} ({bureau})"


def _serveur_audio_linux() -> str:
    """Serveur audio réellement en place (PipeWire attendu sur 26.04) — la capture
    système repose sur ses sources `.monitor` (docs/49 §5.1)."""
    try:
        resultat = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=5)
        if resultat.returncode != 0:
            return f"indisponible (pactl code {resultat.returncode})"
        champs = [ligne.strip() for ligne in resultat.stdout.splitlines()
                  if ligne.startswith(("Server Name:", "Server Version:", "Default Sink:"))]
        return " | ".join(champs) or "indisponible (champs absents)"
    except FileNotFoundError:
        return "indisponible (pactl absent)"
    except Exception as exc:
        return f"indisponible ({exc})"


def collecter_infos_systeme() -> dict:
    """OS, CPU, RAM, GPU, versions libs, périphériques audio.

    Ne lève jamais : chaque rubrique en échec vaut "indisponible (<exc>)"."""
    entrees, sorties = _peripheriques_audio()
    windows = _est_windows()
    linux = _est_linux()

    infos = {
        "os": platform.platform(),
        # Placé haut et avant `faster_whisper` : le paquet est présent dans le bundle
        # unifié quel que soit le mode, mais son usage réel (moteur construit ou non)
        # ne se lit qu'avec le mode juste au-dessus (docs/45).
        "mode_transcription": mode_transcription.mode(),
        "machine": platform.machine(),
        "processeur": platform.processor() or "indisponible",
        "coeurs": str(os.cpu_count() or "indisponible"),
        "ram_go": _ram_go_windows() if windows else (_ram_go_linux() if linux else "non collecté"),
        "gpu": _gpu_windows() if windows else "non collecté",
        "python": platform.python_version(),
        "pyside6": _version_lib("PySide6"),
        "sounddevice": _version_lib("sounddevice"),
        "numpy": _version_lib("numpy"),
        "faster_whisper": _version_lib("faster-whisper"),
        "soundcard": _version_lib("soundcard"),
        "peripheriques_audio_entree": entrees,
        "peripheriques_audio_sortie": sorties,
    }

    # Rubriques Linux ajoutées seulement là où elles ont un sens : sur les autres OS,
    # elles ne feraient qu'allonger l'en-tête de session avec des « non collecté ».
    if linux:
        infos["distribution"] = _distro_linux()
        infos["session"] = _session_linux()
        infos["serveur_audio"] = _serveur_audio_linux()

    return infos
