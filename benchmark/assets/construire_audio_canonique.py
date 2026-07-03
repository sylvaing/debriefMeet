#!/usr/bin/env python
"""Construit l'audio canonique du benchmark (~30 min, 16 kHz mono, multi-locuteurs).

Concatène des tranches issues de plusieurs enregistrements réels (sessions
différentes → locuteurs variés, utile pour la diarisation). Reproductible :
mêmes sources + mêmes tranches → même WAV.

Usage :
    .venv/bin/python benchmark/assets/construire_audio_canonique.py
    .venv/bin/python benchmark/assets/construire_audio_canonique.py --duree 1800
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile

ICI = Path(__file__).resolve().parent
SOURCES_DEFAUT = ICI.parents[1] / "spike" / "diarization" / "audio"
SORTIE_DEFAUT = ICI / "audio_canonique.wav"
SR = 16_000

# (motif de fichier, début s, durée s) — 3 sessions distinctes, 10 min chacune.
TRANCHES = [
    ("Recording at 2026-04-28*.mp3", 0, 600),
    ("Recording at 2026-04-22*.mp3", 300, 600),
    ("Recording at 2026-05-27*.mp3", 600, 600),
]


def _decoder_tranche(src: Path, debut: int, duree: int) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "t.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(debut), "-t", str(duree), "-i", str(src),
             "-ac", "1", "-ar", str(SR), "-f", "wav", str(wav)],
            check=True, capture_output=True,
        )
        _, data = wavfile.read(wav)
        return np.asarray(data)


def construire(sources: Path, sortie: Path, tranches=TRANCHES) -> Path:
    morceaux: list[np.ndarray] = []
    for motif, debut, duree in tranches:
        candidats = sorted(sources.glob(motif))
        if not candidats:
            print(f"⚠ source introuvable : {motif} dans {sources}", file=sys.stderr)
            continue
        print(f"  tranche {duree}s @ {debut}s de {candidats[0].name}")
        morceaux.append(_decoder_tranche(candidats[0], debut, duree))
    if not morceaux:
        sys.exit("Aucune tranche décodée — vérifie les sources.")
    audio = np.concatenate(morceaux).astype(np.int16)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(sortie, SR, audio)
    print(f"✓ {sortie} — {len(audio) / SR:.0f}s, {sortie.stat().st_size / 1e6:.1f} Mo")
    return sortie


def main() -> int:
    ap = argparse.ArgumentParser(description="Construit l'audio canonique du benchmark")
    ap.add_argument("--sources", type=Path, default=SOURCES_DEFAUT)
    ap.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT)
    ap.add_argument("--duree", type=int, default=None,
                    help="Durée cible (s) — ajuste chaque tranche à parts égales.")
    args = ap.parse_args()

    tranches = TRANCHES
    if args.duree:
        part = args.duree // len(TRANCHES)
        tranches = [(motif, debut, part) for motif, debut, _ in TRANCHES]
    construire(args.sources, args.sortie, tranches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
