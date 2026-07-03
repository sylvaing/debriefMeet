"""Inventaire matériel + versions de libs pour le spike.

Adapté de benchmark/materiel.py. Enrichi : fabricant iGPU dans la clé `gpu`.
"""
from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

from spike.backends_windows.journalisation import journal

LIBS_SUIVIES = [
    "faster-whisper", "ctranslate2", "onnxruntime-directml", "optimum", "transformers",
    "openvino", "sounddevice", "numpy", "scipy", "psutil", "py-cpuinfo", "huggingface-hub",
]


def os_normalise() -> str:
    p = sys.platform
    if p == "darwin":
        return "macos"
    if p.startswith("win"):
        return "windows"
    return "linux"


def classer_gpu(nom: str) -> str:
    n = (nom or "").lower()
    if any(m in n for m in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla")):
        return "nvidia"
    if any(m in n for m in ("amd", "radeon", "rx ", "vega")):
        return "amd"
    if "intel" in n:
        return "intel"
    return "autre"


def _cpu_modele() -> str:
    try:
        import cpuinfo
        info = cpuinfo.get_cpu_info()
        nom = info.get("brand_raw") or info.get("brand")
        if nom:
            return str(nom)
    except Exception:
        journal().debug("py-cpuinfo indisponible", exc_info=True)
    if os_normalise() == "macos":
        try:
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=5, check=False)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:
            pass
    return platform.processor() or platform.machine() or "inconnu"


def _coeurs() -> dict:
    physiques = logiques = None
    try:
        import psutil
        physiques = psutil.cpu_count(logical=False)
        logiques = psutil.cpu_count(logical=True)
    except Exception:
        journal().debug("psutil.cpu_count indisponible", exc_info=True)
    if logiques is None:
        logiques = os.cpu_count()
    return {"physiques": physiques, "logiques": logiques}


def _freq_mhz():
    try:
        import psutil
        f = psutil.cpu_freq()
        if f:
            return round(f.max or f.current or 0) or None
    except Exception:
        journal().debug("psutil.cpu_freq indisponible", exc_info=True)
    return None


def _ram_go():
    try:
        import psutil
        return round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        journal().debug("psutil.virtual_memory indisponible", exc_info=True)
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        taille = os.sysconf("SC_PAGE_SIZE")
        return round(pages * taille / 1e9, 1)
    except Exception:
        return None


def _alimentation() -> dict:
    try:
        import psutil
        batt = psutil.sensors_battery()
        if batt is None:
            return {"source": "secteur", "niveau_pct": None}
        return {
            "source": "secteur" if batt.power_plugged else "batterie",
            "niveau_pct": round(batt.percent) if batt.percent is not None else None,
        }
    except Exception:
        journal().debug("psutil.sensors_battery indisponible", exc_info=True)
        return {"source": "inconnu", "niveau_pct": None}


def _gpu_systeme() -> str | None:
    osys = os_normalise()
    try:
        if osys == "windows":
            out = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "name"],
                capture_output=True, text=True, timeout=15, check=False)
            if out.returncode == 0:
                lignes = [l.strip() for l in out.stdout.splitlines() if l.strip()]
                if len(lignes) > 1:
                    return lignes[1]
        elif osys == "linux":
            out = subprocess.run(["lspci"], capture_output=True, text=True,
                                 timeout=15, check=False)
            if out.returncode == 0:
                for ligne in out.stdout.splitlines():
                    if "VGA" in ligne or "3D controller" in ligne:
                        return ligne.split(":", 2)[-1].strip()
        elif osys == "macos":
            out = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                                 capture_output=True, text=True, timeout=15, check=False)
            if out.returncode == 0:
                for ligne in out.stdout.splitlines():
                    if "Chipset Model:" in ligne:
                        return ligne.split(":", 1)[1].strip()
    except Exception:
        journal().debug("_gpu_systeme échoué", exc_info=True)
    return None


def _gpu() -> dict:
    nom = _gpu_systeme()
    if nom:
        fabricant = classer_gpu(nom)
        return {"type": fabricant, "name": nom, "fabricant": fabricant, "vram_mb": None, "driver": None}
    return {"type": "none", "name": None, "fabricant": "inconnu", "vram_mb": None, "driver": None}


def versions_libs() -> dict:
    out: dict[str, str | None] = {"python": platform.python_version()}
    for nom in LIBS_SUIVIES:
        try:
            out[nom] = version(nom)
        except (PackageNotFoundError, Exception):
            out[nom] = None
    return out


def detecter_materiel() -> dict:
    """Inventaire matériel complet, best-effort. Ne lève jamais."""
    log = journal()
    m: dict = {
        "hostname": None,
        "os": os_normalise(),
        "os_version": None,
        "arch": platform.machine(),
        "cpu": None,
        "cpu_cores": {"physiques": None, "logiques": None},
        "cpu_freq_mhz": None,
        "ram_gb": None,
        "gpu": {"type": "inconnu", "name": None, "fabricant": "inconnu", "vram_mb": None, "driver": None},
        "alimentation": {"source": "inconnu", "niveau_pct": None},
    }
    try:
        m["hostname"] = socket.gethostname()
    except Exception:
        pass
    try:
        m["os_version"] = f"{platform.system()} {platform.release()}"
    except Exception:
        pass

    m["cpu"] = _cpu_modele()
    m["cpu_cores"] = _coeurs()
    m["cpu_freq_mhz"] = _freq_mhz()
    m["ram_gb"] = _ram_go()
    m["gpu"] = _gpu()
    m["alimentation"] = _alimentation()

    log.info(
        "Matériel : %s | %s | %s cœurs | %.1f Go RAM | GPU %s (%s, %s)",
        m["os"], m["cpu"], m["cpu_cores"]["logiques"], m["ram_gb"] or 0,
        m["gpu"]["type"], m["gpu"]["name"], m["gpu"]["fabricant"],
    )
    return m
