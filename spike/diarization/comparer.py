#!/usr/bin/env python
"""
POC diarization — compare **sherpa-onnx** vs **pyannote** sur un MP3 de réunion réelle.

Mesure :
- **Vitesse** : facteur temps réel de chaque moteur (objectif).
- **Qualité** : transcription MLX Whisper + attribution des locuteurs par chevauchement →
  deux comptes-rendus « Locuteur N : … » côte à côte, à juger à l'œil (pas de vérité
  terrain → jugement humain).

Usage :
    # sherpa-onnx seul (aucune licence requise) :
    .venv/bin/python spike/diarization/comparer.py --audio reunion.mp3
    # avec pyannote (modèle sous licence HF) :
    HF_TOKEN=hf_xxx .venv/bin/python spike/diarization/comparer.py --audio reunion.mp3
    # rapide, sans transcription (vitesse + nb locuteurs seulement) :
    ... --audio reunion.mp3 --no-transcrire

Place tes MP3 dans spike/diarization/audio/ (ou passe --audio).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile

SR = 16_000
ICI = Path(__file__).resolve().parent
MODELES = ICI / "models"
SEG = MODELES / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMB = MODELES / "emb.onnx"
SORTIES = ICI / "sorties"
PYANNOTE_PIPELINE = "pyannote/speaker-diarization-community-1"  # modèle pyannote 4.0 (gated)


# ── Audio ────────────────────────────────────────────────────────────────────

def mp3_vers_wav16k(src: Path, wav: Path) -> None:
    """Décode n'importe quel MP3/audio → WAV mono 16 kHz via ffmpeg."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", str(SR), "-f", "wav", str(wav)],
        check=True, capture_output=True,
    )


def charger(wav: Path) -> np.ndarray:
    sr, data = wavfile.read(wav)
    data = data.astype(np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if np.issubdtype(np.dtype(data.dtype), np.integer) or np.max(np.abs(data)) > 1.5:
        data = data / 32768.0
    return data.astype(np.float32)


# ── Diarization ──────────────────────────────────────────────────────────────

def diariser_sherpa(audio: np.ndarray) -> tuple[list, float]:
    import sherpa_onnx

    nt = max(1, (os.cpu_count() or 4) - 2)
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(SEG)),
            num_threads=nt),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(EMB), num_threads=nt),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
        min_duration_on=0.3, min_duration_off=0.5,
    )
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    t0 = time.perf_counter()
    res = sd.process(audio).sort_by_start_time()
    dt = time.perf_counter() - t0
    segs = [(s.start, s.end, f"Locuteur {s.speaker}") for s in res]
    return segs, dt


def _token_hf() -> str | None:
    """Token HF depuis l'env (HF_TOKEN) ou le cache (`hf auth login`)."""
    tok = os.environ.get("HF_TOKEN")
    if tok:
        return tok
    try:
        from huggingface_hub import get_token   # API courante (lit env + cache)
        return get_token()
    except Exception:
        try:
            from huggingface_hub import HfFolder
            return HfFolder.get_token()
        except Exception:
            return None


def diariser_pyannote(wav: Path, token: str) -> tuple[list, float]:
    from pyannote.audio import Pipeline
    import torch

    pipeline = Pipeline.from_pretrained(PYANNOTE_PIPELINE, token=token)
    if torch.backends.mps.is_available():
        pipeline.to(torch.device("mps"))
    t0 = time.perf_counter()
    out = pipeline(str(wav))
    dt = time.perf_counter() - t0
    # pyannote 4.0 renvoie un DiarizeOutput ; l'annotation est dans .speaker_diarization.
    ann = getattr(out, "speaker_diarization", out)
    segs = [(tr.start, tr.end, f"Locuteur {lbl}")
            for tr, _, lbl in ann.itertracks(yield_label=True)]
    segs.sort(key=lambda x: x[0])
    return segs, dt


# ── Transcription + attribution ──────────────────────────────────────────────

def transcrire(audio: np.ndarray, langue: str | None) -> list:
    import mlx_whisper

    res = mlx_whisper.transcribe(
        audio, path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
        language=langue, verbose=None, condition_on_previous_text=False,
    )
    return [(s["start"], s["end"], s["text"].strip()) for s in res.get("segments", [])]


def attribuer(segs_whisper: list, segs_diar: list) -> list:
    """Attribue à chaque segment Whisper le locuteur au plus grand chevauchement."""
    out = []
    for deb, fin, txt in segs_whisper:
        meilleur, best = "—", 0.0
        for d0, d1, spk in segs_diar:
            chevauch = max(0.0, min(fin, d1) - max(deb, d0))
            if chevauch > best:
                best, meilleur = chevauch, spk
        out.append((deb, fin, meilleur, txt))
    return out


def nb_locuteurs(segs: list) -> int:
    return len({s[2] for s in segs})


def ecrire_md(chemin: Path, titre: str, items: list, dt: float, dur: float, n_spk: int) -> None:
    lignes = [f"# {titre}", "",
              f"- Durée audio : {dur:.0f}s",
              f"- Temps de diarization : {dt:.1f}s ({dt / dur:.3f}× temps réel)",
              f"- Locuteurs détectés : {n_spk}", "", "---", ""]
    for deb, fin, spk, txt in items:
        if txt:
            lignes.append(f"**{spk}** [{deb:.0f}s] : {txt}")
            lignes.append("")
    chemin.write_text("\n".join(lignes), encoding="utf-8")


# ── Pipeline principal ───────────────────────────────────────────────────────

def traiter(mp3: Path, langue: str | None, transcrire_actif: bool) -> dict:
    SORTIES.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {mp3.name} ===")
    if mp3.suffix.lower() == ".wav":
        wav = mp3                                  # déjà du WAV (ex. extrait) → pas de décodage
    else:
        wav = SORTIES / f"{mp3.stem}_16k.wav"
        print("Décodage MP3 → WAV 16k…")
        mp3_vers_wav16k(mp3, wav)
    audio = charger(wav)
    dur = len(audio) / SR
    print(f"Durée : {dur:.0f}s")

    rapport = {"fichier": mp3.name, "duree": dur}

    print("Diarization sherpa-onnx…")
    segs_s, dt_s = diariser_sherpa(audio)
    rapport["sherpa"] = {"dt": dt_s, "n": nb_locuteurs(segs_s)}
    print(f"  {dt_s:.1f}s ({dt_s/dur:.3f}× RT), {nb_locuteurs(segs_s)} locuteurs")

    token = _token_hf()
    segs_p, dt_p = None, None
    if token:
        print("Diarization pyannote…")
        try:
            segs_p, dt_p = diariser_pyannote(wav, token)
            rapport["pyannote"] = {"dt": dt_p, "n": nb_locuteurs(segs_p)}
            print(f"  {dt_p:.1f}s ({dt_p/dur:.3f}× RT), {nb_locuteurs(segs_p)} locuteurs")
        except Exception as exc:
            print(f"  pyannote ÉCHEC : {exc}")
    else:
        print("pyannote ignoré (pas de HF_TOKEN). Voir le README pour activer.")

    if transcrire_actif:
        print("Transcription MLX Whisper (pour les comptes-rendus)…")
        segs_w = transcrire(audio, langue)
        ecrire_md(SORTIES / f"{mp3.stem}_sherpa.md", f"{mp3.stem} — sherpa-onnx",
                  attribuer(segs_w, segs_s), dt_s, dur, nb_locuteurs(segs_s))
        print(f"  → {SORTIES / (mp3.stem + '_sherpa.md')}")
        if segs_p is not None:
            ecrire_md(SORTIES / f"{mp3.stem}_pyannote.md", f"{mp3.stem} — pyannote",
                      attribuer(segs_w, segs_p), dt_p, dur, nb_locuteurs(segs_p))
            print(f"  → {SORTIES / (mp3.stem + '_pyannote.md')}")
    return rapport


def main() -> int:
    ap = argparse.ArgumentParser(description="POC diarization sherpa-onnx vs pyannote")
    ap.add_argument("--audio", type=Path, help="MP3 à traiter (sinon tous ceux de audio/)")
    ap.add_argument("--langue", default="fr")
    ap.add_argument("--no-transcrire", dest="transcrire", action="store_false",
                    help="vitesse + nb locuteurs seulement (pas de compte-rendu)")
    args = ap.parse_args()

    if args.audio:
        fichiers = [args.audio]
    else:
        fichiers = sorted((ICI / "audio").glob("*.mp3")) if (ICI / "audio").exists() else []
    if not fichiers:
        sys.exit("Aucun MP3. Place-les dans spike/diarization/audio/ ou passe --audio.")

    rapports = [traiter(f, args.langue, args.transcrire) for f in fichiers]

    print("\n" + "=" * 64)
    print("SYNTHÈSE VITESSE")
    print("=" * 64)
    print(f"{'fichier':<24} {'durée':>7} {'sherpa':>16} {'pyannote':>16}")
    for r in rapports:
        s = f"{r['sherpa']['dt']:.0f}s/{r['sherpa']['dt']/r['duree']:.2f}×/{r['sherpa']['n']}spk"
        p = (f"{r['pyannote']['dt']:.0f}s/{r['pyannote']['dt']/r['duree']:.2f}×/{r['pyannote']['n']}spk"
             if r.get("pyannote") else "—")
        print(f"{r['fichier']:<24} {r['duree']:>6.0f}s {s:>16} {p:>16}")
    print("\nQualité : ouvre les .md *_sherpa / *_pyannote dans sorties/ et compare « qui parle ».")
    return 0


if __name__ == "__main__":
    sys.exit(main())
