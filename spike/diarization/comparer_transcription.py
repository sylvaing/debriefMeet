#!/usr/bin/env python
"""
POC transcription passe finale — **re-transcrire l'audio complet** vs **ré-étiqueter
les tranches 30 s** (cf. doc 07 §2, point « texte de la passe finale »).

Sur une vraie réunion, mesure pour CHAQUE approche :
- temps de réalisation (wall-clock),
- charge : CPU-secondes (process) + mémoire pic (RSS),
- et produit les 2 transcripts diarizés (locuteurs via pyannote) à comparer.

Note : MLX Whisper et pyannote utilisent le **GPU (Metal/MPS)** — le coût « ressenti »
est surtout le **temps** et la **mémoire** ; les CPU-secondes sous-estiment (le GPU n'y est
pas compté), mais c'est justement pourquoi le CPU **reste utilisable** pendant le run.

Usage : .venv/bin/python spike/diarization/comparer_transcription.py --wav fichier_16k.wav
"""
from __future__ import annotations

import argparse
import resource
import sys
import time
from pathlib import Path

import numpy as np

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
import comparer as C  # noqa: E402  (charger, diariser_pyannote, attribuer, ecrire_md, _token_hf)

SR = 16_000
TRANCHE_S = 30


def _mesure():
    """(wall, cpu_s, rss_mo) — à appeler avant/après via les deltas."""
    r = resource.getrusage(resource.RUSAGE_SELF)
    return time.perf_counter(), r.ru_utime + r.ru_stime, r.ru_maxrss / (1024 * 1024)


def transcrire_full(audio: np.ndarray, langue: str) -> list:
    import mlx_whisper
    res = mlx_whisper.transcribe(
        audio, path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
        language=langue, verbose=None, condition_on_previous_text=False)
    return [(s["start"], s["end"], s["text"].strip()) for s in res.get("segments", [])]


def transcrire_tranches(audio: np.ndarray, langue: str, tranche_s: int = TRANCHE_S) -> list:
    """Simule l'app : chaque tranche de 30 s transcrite INDÉPENDAMMENT, puis recollée."""
    import mlx_whisper
    pas = tranche_s * SR
    segs = []
    for deb in range(0, len(audio), pas):
        bloc = audio[deb:deb + pas]
        if len(bloc) < SR // 2:
            continue
        res = mlx_whisper.transcribe(
            bloc, path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
            language=langue, verbose=None, condition_on_previous_text=False)
        off = deb / SR
        segs += [(s["start"] + off, s["end"] + off, s["text"].strip())
                 for s in res.get("segments", [])]
    return segs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", type=Path, required=True)
    ap.add_argument("--langue", default="fr")
    args = ap.parse_args()

    C.SORTIES.mkdir(parents=True, exist_ok=True)
    audio = C.charger(args.wav)
    dur = len(audio) / SR
    nom = args.wav.stem.replace("_16k", "")
    print(f"=== {nom} — {dur:.0f}s ({dur/60:.0f} min) ===")

    # Diarization (commune aux deux approches) — pyannote, comme acté.
    token = C._token_hf()
    if not token:
        sys.exit("Pas de token HF (hf auth login).")
    print("Diarization pyannote…")
    segs_diar, dt_diar = C.diariser_pyannote(args.wav, token)
    print(f"  {dt_diar:.0f}s, {len({s[2] for s in segs_diar})} locuteurs")

    mesures = {}
    for label, fn in (("full", transcrire_full), ("tranches", transcrire_tranches)):
        print(f"Transcription « {label} »…")
        w0, c0, _ = _mesure()
        segs = fn(audio, args.langue)
        w1, c1, m1 = _mesure()
        mesures[label] = {"wall": w1 - w0, "cpu": c1 - c0, "rss": m1, "n": len(segs)}
        C.ecrire_md(C.SORTIES / f"{nom}_locuteurs_{label}.md",
                    f"{nom} — passe finale ({label})",
                    C.attribuer(segs, segs_diar), mesures[label]["wall"], dur,
                    len({s[2] for s in segs_diar}))
        print(f"  {mesures[label]['wall']:.0f}s wall, {mesures[label]['cpu']:.0f}s CPU, "
              f"pic {mesures[label]['rss']:.0f} Mo, {mesures[label]['n']} segments")

    print("\n" + "=" * 60)
    print(f"SYNTHÈSE — {nom} ({dur/60:.0f} min)")
    print("=" * 60)
    print(f"{'approche':<12} {'wall':>8} {'×RT':>6} {'CPU-s':>8} {'mém pic':>9} {'segments':>9}")
    for label, m in mesures.items():
        print(f"{label:<12} {m['wall']:>7.0f}s {m['wall']/dur:>5.2f}× {m['cpu']:>7.0f}s "
              f"{m['rss']:>7.0f}Mo {m['n']:>9}")
    print("\nComparer la QUALITÉ : sorties/*_locuteurs_full.md vs *_locuteurs_tranches.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
