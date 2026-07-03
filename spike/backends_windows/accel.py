"""Sondes accélérateurs + gates pour les 4 backends du spike.

Gates (renvoient bool) : indiquent si un backend est pertinent sur cette machine.
Un backend non pertinent est sauté proprement (ligne statut=indisponible dans le rapport).
"""
from __future__ import annotations

import json
import subprocess
import sys

from spike.backends_windows.journalisation import journal


def _safe(fn) -> dict:
    try:
        return fn()
    except Exception as exc:
        journal().debug("sonde accélérateur échouée", exc_info=True)
        return {"disponible": False, "erreur": str(exc)}


# ── Sondes ────────────────────────────────────────────────────────────────────

def sonde_cuda() -> dict:
    def _go():
        res: dict = {"disponible": False, "version": None, "cudnn": None}
        try:
            import torch
            res["disponible"] = bool(torch.cuda.is_available())
            res["version"] = getattr(torch.version, "cuda", None)
            if torch.backends.cudnn.is_available():
                res["cudnn"] = torch.backends.cudnn.version()
        except Exception as exc:
            res["erreur"] = str(exc)
        return res
    return _safe(_go)


def sonde_openvino() -> dict:
    def _go():
        import openvino as ov
        core = ov.Core()
        return {"disponible": True, "version": ov.__version__,
                "peripheriques": core.available_devices,
                "gpu_intel": any(str(d).upper().startswith("GPU")
                                 for d in core.available_devices)}
    return _safe(_go)


def sonde_directml() -> dict:
    def _go():
        import onnxruntime as ort
        providers = ort.get_available_providers()
        return {"disponible": "DmlExecutionProvider" in providers,
                "providers": providers}
    return _safe(_go)


def sonde_amd_rocm() -> dict:
    def _go():
        import torch
        hip = getattr(torch.version, "hip", None)
        return {"disponible": bool(hip), "version": hip}
    return _safe(_go)


def _vulkan_loader() -> dict | None:
    proc = subprocess.run(
        [sys.executable, "-m", "spike.backends_windows.vulkan_probe"],
        capture_output=True, text=True, timeout=20, check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    data = json.loads(proc.stdout)
    if not isinstance(data, list):
        return None
    return {"disponible": len(data) > 0, "methode": "loader", "gpus": data}


def _vulkan_cli() -> dict | None:
    sortie = subprocess.run(["vulkaninfo", "--summary"], capture_output=True,
                            text=True, timeout=15, check=False)
    if sortie.returncode != 0:
        return None
    noms = [l.split("=")[-1].strip() for l in sortie.stdout.splitlines() if "deviceName" in l]
    return {"disponible": "GPU" in sortie.stdout, "methode": "vulkaninfo",
            "gpus": [{"nom": n} for n in noms[:4]]}


def sonde_vulkan() -> dict:
    def _go():
        for tentative in (_vulkan_loader, _vulkan_cli):
            try:
                res = tentative()
                if res is not None:
                    return res
            except Exception:
                journal().debug("sonde Vulkan (%s) échouée", tentative.__name__, exc_info=True)
        return {"disponible": False, "methode": None, "gpus": []}
    return _safe(_go)


def sonder_tout() -> dict:
    log = journal()
    log.info("Sondes accélérateurs…")
    resultats = {
        "cuda": sonde_cuda(),
        "openvino": sonde_openvino(),
        "directml": sonde_directml(),
        "amd_rocm": sonde_amd_rocm(),
        "vulkan": sonde_vulkan(),
    }
    for nom, r in resultats.items():
        log.info("  %s : %s", nom, "disponible" if r.get("disponible") else "non")
    return resultats


# ── Gates ─────────────────────────────────────────────────────────────────────

def gate_openvino_gpu(accel: dict) -> bool:
    """True si OpenVINO voit un GPU Intel (entrée GPU* dans available_devices)."""
    return bool(accel.get("openvino", {}).get("gpu_intel"))


def gate_directml(accel: dict) -> bool:
    """True si DmlExecutionProvider est disponible dans ONNX Runtime."""
    return bool(accel.get("directml", {}).get("disponible"))


def gate_vulkan(accel: dict, binaire) -> bool:
    """True si Vulkan voit un GPU ET le binaire whisper.cpp est présent."""
    from pathlib import Path
    return (bool(accel.get("vulkan", {}).get("disponible")) and
            Path(binaire).exists())
