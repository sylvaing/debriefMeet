"""Orchestrateur spike backends Windows : matrice complète → rapport zippé.

Usage :
    python -m spike.backends_windows [options]

Chaque (backend × modèle) est isolé en try/except : un échec dégrade une ligne,
ne casse jamais le run. En fin de run : rapport.json + rapport.md + zip.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from spike.backends_windows import (
    accel as sond,
    audio_io,
    chemins,
    materiel as mat,
    mesure,
    modeles,
    qualite,
    rapport,
)
from spike.backends_windows.journalisation import configurer_journal, journal


# ── Matrice (backend, modèle, moteur factory) ─────────────────────────────────

def _backends_actifs(accel: dict) -> list[str]:
    """Retourne les noms de backends à tenter sur cette machine."""
    actifs = ["faster-whisper"]  # toujours disponible (CPU)
    if accel.get("openvino", {}).get("disponible"):
        actifs.append("openvino")
    if sond.gate_directml(accel):
        actifs.append("directml")
    binaire = chemins.binaire_whispercpp()
    if sond.gate_vulkan(accel, binaire):
        actifs.append("vulkan")
    return actifs


def _moteur_pour(backend: str, accel: dict):
    """Crée le moteur correspondant au backend. Peut lever à l'import."""
    if backend == "faster-whisper":
        from spike.backends_windows.moteur_faster import MoteurFaster
        return MoteurFaster()
    if backend == "openvino":
        from spike.backends_windows.moteur_openvino import MoteurOpenVINO
        device = "GPU" if sond.gate_openvino_gpu(accel) else "CPU"
        return MoteurOpenVINO(device=device)
    if backend == "directml":
        from spike.backends_windows.moteur_directml import MoteurDirectML
        return MoteurDirectML()
    if backend == "vulkan":
        from spike.backends_windows.moteur_whispercpp import MoteurWhisperCpp
        return MoteurWhisperCpp()
    raise ValueError(f"Backend inconnu : {backend!r}")


def _info_device(moteur, backend: str, accel: dict) -> dict:
    try:
        if hasattr(moteur, "info_device"):
            if callable(moteur.info_device) and not isinstance(moteur.info_device, dict):
                return moteur.info_device() if not hasattr(moteur.info_device, "__self__") \
                    else moteur.info_device()
            return moteur.info_device
    except Exception:
        pass
    return {"device_reel": backend, "compute_type": "?"}


# ── Sweep d'un backend ─────────────────────────────────────────────────────────

def _sweep_backend(backend: str, tailles: list[str], tranches: list[np.ndarray],
                   sr: int, langue: str | None, dossier: Path,
                   accel: dict) -> list[dict]:
    log = journal()
    log.info("=== Backend : %s ===", backend)
    resultats: list[dict] = []

    for taille in tailles:
        log.info("  Modèle : %s", taille)
        artefact = dossier / f"transcription_{backend}_{taille}.txt"
        try:
            moteur = _moteur_pour(backend, accel)
            dev_info = _info_device(moteur, backend, accel)
            r = mesure.mesurer_moteur(moteur, taille, tranches, sr, langue, artefact)
            r["backend"] = backend
            r.update(dev_info)
            resultats.append(r)
            rtf_s = max(v for v in (r.get("rtf_moyen"), r.get("rtf_fin")) if v) if \
                any(v for v in (r.get("rtf_moyen"), r.get("rtf_fin")) if v) else None
            log.info("    RTF soutenu=%.3f hallu=%s wer=%s",
                     rtf_s or 0, r.get("hallucination"), r.get("wer"))
        except FileNotFoundError as exc:
            log.warning("  %s/%s : modèle absent (%s)", backend, taille, exc)
            resultats.append({"backend": backend, "modele": taille,
                               "statut": "indisponible", "erreur": str(exc)})
        except Exception as exc:
            log.warning("  %s/%s : ÉCHEC (%s)", backend, taille, exc, exc_info=True)
            resultats.append({"backend": backend, "modele": taille,
                               "statut": "erreur", "erreur": str(exc)})

    qualite.appliquer_wer_relatif(resultats)
    return resultats


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    # Force UTF-8 sur les flux Windows (évite UnicodeEncodeError dans les logs).
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parseur = argparse.ArgumentParser(
        prog="spike.backends_windows",
        description="Spike comparatif backends Windows — 4 backends × 4 modèles.")
    parseur.add_argument("--audio", type=Path, default=None)
    parseur.add_argument("--modeles", nargs="+", default=modeles.SWEEP)
    parseur.add_argument("--langue", default="fr")
    parseur.add_argument("--backends", nargs="+", default=None,
                         help="Forcer une liste de backends (défaut : auto-détectés).")
    parseur.add_argument("--sortie", type=Path, default=None)
    parseur.add_argument("--sans-emballage", action="store_true")
    args = parseur.parse_args(argv)

    dossier = args.sortie or chemins.dossier_sortie()
    dossier.mkdir(parents=True, exist_ok=True)
    log = configurer_journal(dossier / "journal.log")
    log.info("=== Spike backends Windows ===")

    # 1. Matériel + accélérateurs.
    materiel = mat.detecter_materiel()
    libs = mat.versions_libs()
    log.debug("Versions libs : %s", libs)
    accel = sond.sonder_tout()

    # 2. Audio.
    audio_path = args.audio or chemins.audio_canonique()
    audio = np.zeros(0, dtype=np.float32)
    duree = 0.0
    try:
        audio, _ = audio_io.charger(audio_path)
        duree = len(audio) / mesure.SR
        log.info("Audio : %s (%.0f s)", audio_path, duree)
    except Exception as exc:
        log.error("Chargement audio impossible (%s) — pas de transcription.", exc, exc_info=True)

    tranches = mesure.decouper(audio, mesure.SR) if len(audio) else []
    audio_info = {
        "fichier": Path(audio_path).name,
        "duree_s": round(duree, 1),
        "langue": args.langue,
    }

    # 3. Matrice backends × modèles.
    backends = args.backends or _backends_actifs(accel)
    log.info("Backends actifs : %s", backends)
    log.info("Modèles : %s", args.modeles)

    tous_resultats: list[dict] = []
    if tranches:
        for backend in backends:
            try:
                resultats_backend = _sweep_backend(
                    backend, args.modeles, tranches, mesure.SR, args.langue, dossier, accel)
                tous_resultats.extend(resultats_backend)
            except Exception as exc:
                log.warning("Backend %s : ÉCHEC global (%s)", backend, exc, exc_info=True)

    # 4. Rapport.
    rap = rapport.construire_rapport(
        materiel=materiel, libs=libs, accelerateurs=accel,
        audio=audio_info, resultats=tous_resultats)
    chemins_ecrits = rapport.ecrire(rap, dossier)
    log.info("Rapport : %s", chemins_ecrits["json"])
    v = rap["verdict_machine"]
    log.info("Verdict : %s — %s", v["niveau"], v["details"])

    if not args.sans_emballage:
        archive = rapport.emballer(dossier, materiel)
        log.info("")
        log.info("✓ Terminé. Envoie CE fichier :")
        log.info("    %s", archive.resolve())

    return 0


if __name__ == "__main__":
    sys.exit(main())
