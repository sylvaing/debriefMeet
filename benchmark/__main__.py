"""Point d'entrée du benchmark : `python -m benchmark`.

Enchaîne (1) une phase guidée interactive (capture audio / AEC), puis (2) une
phase automatique (sweep transcription + diarisation + sondes accélérateurs),
et produit en sortie UN SEUL zip à transmettre. Chaque étape est isolée : un
échec dégrade le rapport, ne casse jamais le run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from benchmark import (
    audio_io,
    chemins,
    diarisation,
    materiel as mat,
    modeles,
    moteurs,
    pipeline,
    rapport,
    sondes_accel,
    sondes_capture,
)
from benchmark.journalisation import configurer_journal, journal


def _transcripteur_capture(mode: dict):
    """Fournit une fonction de transcription (modèle small) pour le WER de capture.

    Le modèle est chargé paresseusement et réutilisé. Renvoie None si indisponible.
    """
    etat: dict = {}

    def fn(audio16k: np.ndarray) -> str:
        if "moteur" not in etat:
            m = moteurs.MoteurBench(mode)
            m.charger("small")
            etat["moteur"] = m
        return etat["moteur"].transcrire(audio16k, "fr").texte

    return fn


def _observations(auto_skip: bool) -> str:
    if auto_skip:
        return ""
    journal().info("")
    try:
        return input("As-tu remarqué quelque chose d'anormal (lenteur, son, plantage) ? "
                     "(Entrée pour passer)\n  → ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(
        prog="benchmark",
        description="Benchmark debriefMeet — mesure si la machine fait tourner le soft.")
    parseur.add_argument("--audio", type=Path, default=None,
                         help="Audio de test (défaut : audio canonique embarqué).")
    parseur.add_argument("--modeles", nargs="+", default=modeles.SWEEP,
                         help="Tailles Whisper à balayer (défaut : small medium large-v3).")
    parseur.add_argument("--langue", default="fr")
    parseur.add_argument("--duree-max-s", type=float, default=600.0,
                         help="Durée max d'audio pour le sweep transcription (défaut 600 s = "
                              "10 min ; 0 = tout). La diarisation utilise l'audio complet.")
    parseur.add_argument("--sortie", type=Path, default=None,
                         help="Dossier de sortie (défaut : ./resultats_benchmark).")
    parseur.add_argument("--auto-skip", action="store_true",
                         help="Phase guidée non-interactive (tout sauté).")
    parseur.add_argument("--duree-sonde", type=float, default=6.0)
    parseur.add_argument("--sans-diarisation", action="store_true")
    parseur.add_argument("--sans-capture", action="store_true")
    parseur.add_argument("--sans-accel", action="store_true")
    parseur.add_argument("--sans-openvino", action="store_true",
                         help="Désactive le comparatif OpenVINO (GPU Intel).")
    parseur.add_argument("--sans-emballage", action="store_true")
    args = parseur.parse_args(argv)

    dossier = args.sortie or chemins.dossier_sortie()
    dossier.mkdir(parents=True, exist_ok=True)
    log = configurer_journal(dossier / "journal.log")
    log.info("=== Benchmark debriefMeet ===")

    # 0. Diagnostic environnement (run unique → on note tout).
    materiel = mat.detecter_materiel()
    log.debug("Versions libs : %s", mat.versions_libs())
    mode = moteurs.choisir_mode(materiel)
    log.info("Mode retenu : %s", mode)

    # 1. Phase guidée interactive (capture audio + AEC) — d'abord, utilisateur présent.
    capture: dict = {}
    if not args.sans_capture:
        try:
            transcripteur = None if args.auto_skip else _transcripteur_capture(mode)
            capture = sondes_capture.scenario(
                auto_skip=args.auto_skip, duree=args.duree_sonde, transcrire_fn=transcripteur)
        except Exception as exc:
            log.warning("Phase capture : ÉCHEC global (%s)", exc, exc_info=True)
            capture = {"erreur": str(exc)}

    # 2. Phase automatique.
    audio_path = args.audio or chemins.audio_canonique()
    audio = np.zeros(0, dtype=np.float32)
    duree = 0.0
    try:
        audio, _ = audio_io.charger(audio_path)
        duree = len(audio) / pipeline.SR
        log.info("Audio : %s (%.0f s)", audio_path, duree)
    except Exception as exc:
        log.error("Chargement audio impossible (%s) — pas de transcription.", exc, exc_info=True)

    # Sweep transcription sur un extrait borné (RTF/WER/throttling restent valides) ;
    # la diarisation garde l'audio complet (rapide + diversité de locuteurs).
    audio_sweep = pipeline.tronquer(audio, pipeline.SR, args.duree_max_s)
    duree_sweep = len(audio_sweep) / pipeline.SR
    if len(audio_sweep) < len(audio):
        log.info("Sweep transcription borné à %.0f s (sur %.0f s) ; diarisation sur l'audio complet.",
                 duree_sweep, duree)

    transcription: list = []
    if len(audio_sweep):
        transcription = pipeline.executer_sweep(
            mode, args.modeles, audio_sweep, pipeline.SR, args.langue, dossier)

    diar: list = []
    if len(audio) and not args.sans_diarisation:
        diar = pipeline.executer_diarisation(audio, pipeline.SR, dossier, diarisation.token_hf())

    # Comparatif OpenVINO : seulement si un GPU Intel est détecté (sinon sauté).
    openvino: list = []
    if len(audio_sweep) and not args.sans_openvino:
        try:
            if sondes_accel.gpu_intel_disponible():
                log.info("GPU Intel détecté → comparatif OpenVINO")
                openvino = pipeline.executer_comparatif_openvino(
                    args.modeles, audio_sweep, pipeline.SR, args.langue, dossier)
            else:
                log.info("Pas de GPU Intel (ou openvino absent) → comparatif OpenVINO sauté")
        except Exception as exc:
            log.warning("Comparatif OpenVINO : ÉCHEC global (%s)", exc, exc_info=True)

    accel: dict = {}
    if not args.sans_accel:
        accel = sondes_accel.sonder_tout()

    observations = _observations(args.auto_skip)

    # 3. Rapport + emballage.
    rap = rapport.construire_rapport(
        materiel=materiel, mode=mode,
        audio={"fichier": Path(audio_path).name, "duree_s": round(duree, 1),
               "duree_transcription_s": round(duree_sweep, 1)},
        transcription=transcription, diarisation=diar, openvino=openvino,
        capture=capture, accelerateurs=accel, observations=observations)
    chemins_ecrits = rapport.ecrire(rap, dossier)
    log.info("Rapport : %s", chemins_ecrits["json"])
    log.info("Verdict : %s — %s", rap["verdict"]["niveau"], rap["verdict"]["details"])

    if not args.sans_emballage:
        archive = rapport.emballer(dossier, materiel)
        log.info("")
        log.info("✓ Terminé. Envoie CE fichier :")
        log.info("    %s", archive.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
