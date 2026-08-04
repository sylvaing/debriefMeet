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

from debrief_meet.core import edition


def _est_windows() -> bool:
    return sys.platform == "win32"


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


def collecter_infos_systeme() -> dict:
    """OS, CPU, RAM, GPU, versions libs, périphériques audio.

    Ne lève jamais : chaque rubrique en échec vaut "indisponible (<exc>)"."""
    entrees, sorties = _peripheriques_audio()
    windows = _est_windows()

    return {
        "os": platform.platform(),
        # Placée haut et avant `faster_whisper` : en lite cette ligne-là dira
        # « indisponible (No package metadata…) », ce qui est correct et prouve le bundle
        # allégé — mais incohérent à lire sans savoir l'édition juste au-dessus (docs/44).
        "edition": edition.edition(),
        "machine": platform.machine(),
        "processeur": platform.processor() or "indisponible",
        "coeurs": str(os.cpu_count() or "indisponible"),
        "ram_go": _ram_go_windows() if windows else "non collecté",
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
