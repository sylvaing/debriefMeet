"""Détection matérielle cross-platform, best-effort (ne lève jamais).

Renvoie un dictionnaire homogène sur tous les OS, intégré tel quel au rapport.
Toutes les dépendances optionnelles (psutil, py-cpuinfo, torch) sont importées
en lazy avec repli : sur une machine où elles manquent, on dégrade au lieu de
planter.
"""
from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version

from benchmark.journalisation import journal

# Libs dont on veut tracer la version dans le journal (run unique → on note tout).
LIBS_SUIVIES = [
    "faster-whisper", "ctranslate2", "mlx-whisper", "torch", "torchaudio",
    "sherpa-onnx", "pyannote-audio", "livekit", "sounddevice", "numpy",
    "scipy", "psutil", "py-cpuinfo", "huggingface-hub",
]


def os_normalise() -> str:
    """'macos' | 'windows' | 'linux' (mappe sys.platform)."""
    p = sys.platform
    if p == "darwin":
        return "macos"
    if p.startswith("win"):
        return "windows"
    return "linux"


def classer_gpu(nom: str) -> str:
    """Classe un nom de GPU → 'nvidia' | 'amd' | 'intel' | 'autre'."""
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
        import cpuinfo  # py-cpuinfo

        info = cpuinfo.get_cpu_info()
        nom = info.get("brand_raw") or info.get("brand")
        if nom:
            return str(nom)
    except Exception:
        journal().debug("py-cpuinfo indisponible", exc_info=True)
    if os_normalise() == "macos":
        sortie = _commande(["sysctl", "-n", "machdep.cpu.brand_string"])
        if sortie and sortie.strip():
            return sortie.strip()
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
    """Source d'alimentation : contextualise la perf (batterie ≠ secteur)."""
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


def _commande(args: list[str]) -> str | None:
    try:
        sortie = subprocess.run(
            args, capture_output=True, text=True, timeout=15, check=False
        )
        if sortie.returncode == 0:
            return sortie.stdout
    except Exception:
        journal().debug("commande échouée : %s", " ".join(args), exc_info=True)
    return None


def _nvidia_smi() -> dict | None:
    sortie = _commande(
        ["nvidia-smi", "--query-gpu=name,memory.total",
         "--format=csv,noheader,nounits"]
    )
    if not sortie:
        return None
    ligne = sortie.strip().splitlines()[0]
    morceaux = [m.strip() for m in ligne.split(",")]
    nom = morceaux[0] if morceaux else "GPU NVIDIA"
    vram = None
    if len(morceaux) > 1:
        try:
            vram = round(float(morceaux[1]))
        except ValueError:
            pass
    return {"type": "nvidia", "name": nom, "vram_mb": vram, "cuda": None}


def _gpu_systeme() -> str | None:
    """Nom du GPU via outil système (iGPU Intel, AMD, etc.)."""
    osys = os_normalise()
    if osys == "windows":
        sortie = _commande(
            ["wmic", "path", "win32_VideoController", "get", "name"]
        )
        if sortie:
            lignes = [l.strip() for l in sortie.splitlines() if l.strip()]
            if len(lignes) > 1:  # 1re ligne = en-tête "Name"
                return lignes[1]
    elif osys == "linux":
        sortie = _commande(["lspci"])
        if sortie:
            for ligne in sortie.splitlines():
                if "VGA" in ligne or "3D controller" in ligne:
                    return ligne.split(":", 2)[-1].strip()
    elif osys == "macos":
        sortie = _commande(["system_profiler", "SPDisplaysDataType"])
        if sortie:
            for ligne in sortie.splitlines():
                if "Chipset Model:" in ligne:
                    return ligne.split(":", 1)[1].strip()
    return None


def _gpu() -> dict:
    # 1. NVIDIA / Metal via torch (le plus fiable quand dispo)
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {
                "type": "nvidia",
                "name": torch.cuda.get_device_name(0),
                "vram_mb": round(props.total_memory / 1e6),
                "cuda": getattr(torch.version, "cuda", None),
            }
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return {"type": "metal", "name": "Apple Silicon GPU",
                    "vram_mb": None, "cuda": None}
    except Exception:
        journal().debug("détection GPU via torch indisponible", exc_info=True)

    # 2. nvidia-smi (NVIDIA sans torch)
    nv = _nvidia_smi()
    if nv:
        return nv

    # 3. Outil système (iGPU Intel / AMD)
    nom = _gpu_systeme()
    if nom:
        return {"type": classer_gpu(nom), "name": nom, "vram_mb": None, "cuda": None}

    return {"type": "none", "name": None, "vram_mb": None, "cuda": None}


def versions_libs() -> dict:
    """Versions installées des libs clés (None si absente)."""
    out: dict[str, str | None] = {"python": platform.python_version()}
    for nom in LIBS_SUIVIES:
        try:
            out[nom] = version(nom)
        except PackageNotFoundError:
            out[nom] = None
        except Exception:
            out[nom] = None
    return out


def detecter_materiel() -> dict:
    """Inventaire matériel complet, best-effort. Ne lève jamais."""
    log = journal()
    materiel: dict = {
        "hostname": None,
        "os": os_normalise(),
        "os_version": None,
        "arch": platform.machine(),
        "cpu": None,
        "cpu_cores": {"physiques": None, "logiques": None},
        "cpu_freq_mhz": None,
        "ram_gb": None,
        "gpu": {"type": "inconnu", "name": None, "vram_mb": None, "cuda": None},
        "alimentation": {"source": "inconnu", "niveau_pct": None},
    }
    try:
        materiel["hostname"] = socket.gethostname()
    except Exception:
        log.debug("hostname indisponible", exc_info=True)
    try:
        materiel["os_version"] = f"{platform.system()} {platform.release()}"
    except Exception:
        log.debug("os_version indisponible", exc_info=True)

    materiel["cpu"] = _cpu_modele()
    materiel["cpu_cores"] = _coeurs()
    materiel["cpu_freq_mhz"] = _freq_mhz()
    materiel["ram_gb"] = _ram_go()
    materiel["gpu"] = _gpu()
    materiel["alimentation"] = _alimentation()

    log.info(
        "Matériel : %s | %s | %s cœurs | %s Go RAM | GPU %s (%s)",
        materiel["os"], materiel["cpu"], materiel["cpu_cores"]["logiques"],
        materiel["ram_gb"], materiel["gpu"]["type"], materiel["gpu"]["name"],
    )
    return materiel
