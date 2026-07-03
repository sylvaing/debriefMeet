#!/usr/bin/env python
"""
Spike AEC WebRTC — Étape 1 : capture guidée des 2 pistes (sans casque).

Enregistre EN PARALLÈLE le micro (« Moi ») et l'audio système (« Participants »)
en réutilisant les briques de l'app (CaptureMicroSounddevice + CaptureAudioSCK),
selon le protocole minuté du README, et produit les 3 fichiers attendus par
`traiter_offline.py` :

    moi.wav            micro (mono, 44,1 kHz)
    participants.wav   système (stéréo, 48 kHz)
    phases.txt         bornes minutées des phases

⚠️ AVANT de lancer (sans casque !) :
  1. Préparer un podcast / extrait CONNU prêt à jouer sur les haut-parleurs.
  2. Avoir sous les yeux un texte à lire (→ le copier dans texte_lu.txt pour le WER).
  3. macOS demandera les autorisations Micro et Enregistrement d'écran si besoin.

Déroulé (durées réglables) : pré-roll → CLAP → « participants seuls » (silence) →
« moi parle » (lecture) → post-roll. Lancer le podcast au tout début, le laisser
tourner pendant les deux phases.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from debrief_meet.platform.commun.micro_sounddevice import CaptureMicroSounddevice
from debrief_meet.platform.macos.capture_systeme import CaptureAudioSCK


def _accumuler(capture, sacs: list[np.ndarray]) -> None:
    ech = capture.recuperer_echantillons()
    if ech is not None and len(ech):
        sacs.append(np.asarray(ech))


def _barre(reste: float, total: float, etiquette: str) -> None:
    largeur = 24
    rempli = int(largeur * (1 - reste / total)) if total else largeur
    barre = "█" * rempli + "·" * (largeur - rempli)
    sys.stdout.write(f"\r  [{barre}] {etiquette}  ({reste:4.1f}s restantes)   ")
    sys.stdout.flush()


def capturer(sortie: Path, pre: float, clap: float, participants: float,
             pause: float, moi: float, post: float, cycles: int = 1) -> None:
    mic = CaptureMicroSounddevice()
    sck = CaptureAudioSCK()
    if not mic.disponible():
        sys.exit("ERREUR : micro indisponible.")
    if not sck.disponible():
        sys.exit("ERREUR : capture système (SCKAudioPOC) indisponible — voir helpers/macos.")

    sortie.mkdir(parents=True, exist_ok=True)

    # Séquence des étapes : (libellé, durée, nom_phase_ou_None).
    # `cycles` > 1 → alternance répétée (Étape 2 : mesure début vs fin de session).
    source = "YouTube/podcast"
    sequence = [
        (f"Préparez-vous… lancez {source} sur les HP", pre, None),
        (">>> CLAP UNIQUE, SEC, MAINTENANT ! <<<", clap, None),
    ]
    for c in range(1, cycles + 1):
        suff = f" [{c}/{cycles}]" if cycles > 1 else ""
        sequence += [
            (f"PARTICIPANTS SEULS — restez SILENCIEUX{suff}", participants, "participants_seuls"),
            ("(transition)", pause, None),
            (f"MOI PARLE — LISEZ le texte à voix haute{suff}", moi, "moi_parle"),
            ("(transition)", pause, None),
        ]
    sequence.append(("Terminé — fin de l'enregistrement", post, None))

    print("\nDémarrage des captures (micro + système)…")
    sck.demarrer()
    mic.demarrer()
    sr_mic = mic.taux_echantillonnage
    sr_sck = sck.taux_echantillonnage
    print(f"  micro {sr_mic} Hz · système {sr_sck} Hz")
    print("  Le podcast doit déjà tourner. C'est parti.\n")

    sacs_mic: list[np.ndarray] = []
    sacs_sck: list[np.ndarray] = []
    phases: list[tuple[str, float, float]] = []

    t0 = time.perf_counter()
    for libelle, duree, nom_phase in sequence:
        debut = time.perf_counter() - t0
        fin_prevue = debut + duree
        while True:
            maintenant = time.perf_counter() - t0
            reste = fin_prevue - maintenant
            if reste <= 0:
                break
            _accumuler(mic, sacs_mic)
            _accumuler(sck, sacs_sck)
            _barre(reste, duree, libelle)
            time.sleep(0.05)
        if nom_phase:
            # marge aux bords pour éviter les transitions, sans jamais inverser
            marge = min(0.3, duree * 0.15)
            phases.append((nom_phase, round(debut + marge, 2), round(fin_prevue - marge, 2)))
        print()

    # Dernière collecte + arrêt propre
    _accumuler(mic, sacs_mic)
    _accumuler(sck, sacs_sck)
    mic.arreter()
    sck.arreter()
    mic.terminer()
    sck.terminer()

    audio_mic = np.concatenate(sacs_mic).astype(np.float32) if sacs_mic else np.zeros(0, np.float32)
    audio_sck = np.concatenate(sacs_sck).astype(np.float32) if sacs_sck else np.zeros((0, 2), np.float32)

    f_mic = sortie / "moi.wav"
    f_sck = sortie / "participants.wav"
    f_phases = sortie / "phases.txt"
    wavfile.write(f_mic, sr_mic, audio_mic)
    wavfile.write(f_sck, sr_sck, audio_sck)
    f_phases.write_text(
        "# nom debut_s fin_s — bornes des phases (le clap initial sert d'ancre d'alignement)\n"
        + "\n".join(f"{n} {d} {f}" for n, d, f in phases) + "\n"
    )

    dur_mic = len(audio_mic) / sr_mic if sr_mic else 0
    print("\n── Enregistrement terminé ──")
    print(f"  {f_mic}        ({dur_mic:.1f}s, {len(audio_mic)} éch.)")
    print(f"  {f_sck} ({audio_sck.shape[0] / sr_sck:.1f}s, {audio_sck.shape} )")
    print(f"  {f_phases} :")
    for n, d, f in phases:
        print(f"      {n} {d} {f}")
    if dur_mic < 1:
        print("\n⚠️  Piste micro quasi vide — vérifiez l'autorisation Micro.")
    if audio_sck.shape[0] < sr_sck:
        print("⚠️  Piste système quasi vide — vérifiez l'autorisation Enregistrement d'écran.")
    print("\nÉtape suivante :")
    print(f"  .venv/bin/python spike/aec-webrtc/traiter_offline.py \\")
    print(f"      --micro {f_mic} --systeme {f_sck} --phases {f_phases} \\")
    print(f"      --texte-lu texte_lu.txt --transcrire --langue fr")


def main() -> int:
    ap = argparse.ArgumentParser(description="Spike AEC WebRTC — capture guidée 2 pistes")
    ap.add_argument("--sortie", type=Path, default=Path("spike/aec-webrtc/captures"),
                    help="dossier de sortie")
    ap.add_argument("--pre", type=float, default=3.0, help="pré-roll (s)")
    ap.add_argument("--clap", type=float, default=2.0, help="fenêtre du clap (s)")
    ap.add_argument("--participants", type=float, default=12.0, help="phase « participants seuls » (s)")
    ap.add_argument("--pause", type=float, default=1.5, help="transition (s)")
    ap.add_argument("--moi", type=float, default=15.0, help="phase « moi parle » (s)")
    ap.add_argument("--post", type=float, default=1.5, help="post-roll (s)")
    ap.add_argument("--cycles", type=int, default=1,
                    help="nb de cycles participants/moi (Étape 2 : 6–8 pour ~4 min)")
    args = ap.parse_args()
    capturer(args.sortie, args.pre, args.clap, args.participants,
             args.pause, args.moi, args.post, args.cycles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
