"""Sondes accélérateurs : détecte les chemins d'inférence disponibles.

But : éclairer les choix de backend pour les ports (CUDA/cuDNN bien embarqués ?
faut-il un backend Intel OpenVINO/DirectML pour les iGPU ? AMD ROCm/Vulkan ?).
Chaque sonde renvoie {disponible, ...} et ne lève jamais.
"""
from __future__ import annotations

import json
import subprocess
import sys

from benchmark.journalisation import journal


def _safe(fn) -> dict:
    try:
        return fn()
    except Exception as exc:
        journal().debug("sonde accélérateur échouée", exc_info=True)
        return {"disponible": False, "erreur": str(exc)}


def sonde_cuda() -> dict:
    """CUDA + cuDNN vus par torch/ctranslate2 (valide aussi le bundling des DLL)."""
    def _go():
        res: dict = {"disponible": False, "cudnn": None, "erreur": None}
        try:
            import torch

            res["disponible"] = bool(torch.cuda.is_available())
            res["version_cuda"] = getattr(torch.version, "cuda", None)
            if torch.backends.cudnn.is_available():
                res["cudnn"] = torch.backends.cudnn.version()
            if res["disponible"]:
                res["gpu"] = torch.cuda.get_device_name(0)
        except Exception as exc:
            res["erreur"] = f"torch: {exc}"
        # ctranslate2 (moteur réel de faster-whisper)
        try:
            import ctranslate2

            res["ctranslate2_cuda"] = "cuda" in ctranslate2.get_supported_compute_types("cuda") \
                if hasattr(ctranslate2, "get_supported_compute_types") else None
        except Exception:
            res["ctranslate2_cuda"] = None
        return res

    return _safe(_go)


def sonde_intel_openvino() -> dict:
    def _go():
        import openvino as ov

        core = ov.Core()
        return {"disponible": True, "version": ov.__version__,
                "peripheriques": core.available_devices}
    return _safe(_go)


def gpu_intel_disponible() -> bool:
    """True si OpenVINO voit un GPU Intel (entrée `GPU*` dans available_devices).

    Sert de gate au comparatif OpenVINO : sur une machine sans GPU Intel (ou sans
    openvino installé), renvoie False → le comparatif est sauté.
    """
    res = sonde_intel_openvino()
    peripheriques = res.get("peripheriques") or []
    return any(str(d).upper().startswith("GPU") for d in peripheriques)


def sonde_intel_directml() -> dict:
    def _go():
        import torch_directml

        return {"disponible": True, "n_peripheriques": torch_directml.device_count()}
    return _safe(_go)


def sonde_amd_rocm() -> dict:
    def _go():
        import torch

        hip = getattr(torch.version, "hip", None)
        return {"disponible": bool(hip), "version_hip": hip}
    return _safe(_go)


def _vulkan_loader() -> dict | None:
    """Énumère les GPU via le loader du driver, dans un SOUS-PROCESSUS isolé.

    L'énumération ctypes peut segfault (driver) — non rattrapable par try/except.
    En l'isolant, un crash ne tue que l'enfant : on détecte le code de retour
    anormal / timeout / stdout vide et on renvoie None (→ repli). Jamais d'exception
    propagée au run principal.
    """
    proc = subprocess.run([sys.executable, "-m", "benchmark.vulkan_probe"],
                          capture_output=True, text=True, timeout=20, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None  # loader absent, crash natif, timeout, ou rien → repli
    data = json.loads(proc.stdout)
    if not isinstance(data, list):
        return None
    return {"disponible": len(data) > 0, "methode": "loader", "gpus": data}


def _vulkan_cli() -> dict | None:
    """Repli : ancien CLI `vulkaninfo` (présent uniquement si le SDK Vulkan est installé)."""
    sortie = subprocess.run(["vulkaninfo", "--summary"], capture_output=True,
                            text=True, timeout=15, check=False)
    if sortie.returncode != 0:
        return None
    noms = [l.split("=")[-1].strip() for l in sortie.stdout.splitlines() if "deviceName" in l]
    return {"disponible": "GPU" in sortie.stdout, "methode": "vulkaninfo",
            "gpus": [{"nom": n} for n in noms[:4]]}


def sonde_vulkan() -> dict:
    """Vulkan multi-fournisseurs (Intel/AMD/NVIDIA). Interroge le loader du driver
    (sous-processus isolé), repli sur `vulkaninfo`. Ne plante jamais le run."""
    def _go():
        for tentative in (_vulkan_loader, _vulkan_cli):
            try:
                res = tentative()
                if res is not None:
                    return res
            except Exception:
                journal().debug("sonde Vulkan (%s) indisponible", tentative.__name__,
                                exc_info=True)
        return {"disponible": False, "methode": None, "gpus": []}
    return _safe(_go)


def sonder_tout() -> dict:
    """Lance toutes les sondes accélérateurs."""
    log = journal()
    log.info("Sondes accélérateurs…")
    resultats = {
        "cuda": sonde_cuda(),
        "intel_openvino": sonde_intel_openvino(),
        "intel_directml": sonde_intel_directml(),
        "amd_rocm": sonde_amd_rocm(),
        "vulkan": sonde_vulkan(),
    }
    for nom, r in resultats.items():
        log.info("  %s : %s", nom, "disponible" if r.get("disponible") else "non")
    return resultats
