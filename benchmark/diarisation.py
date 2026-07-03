"""Diarisation comparative pour le benchmark : sherpa-onnx vs pyannote.

Logique reprise de spike/diarization/comparer.py, rendue autonome et tolérante
aux pannes (imports lazy). Chaque moteur renvoie (segments, durée) où segments
est une liste de (début, fin, "Locuteur N").
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from benchmark import modeles
from benchmark.journalisation import journal

SR = 16_000


def nb_locuteurs(segments: list) -> int:
    return len({s[2] for s in segments})


def _progress_sherpa(log, pas: float = 10.0):
    """Callback de progression pour `sd.process` : journalise l'avancement par paliers.

    sherpa-onnx traite tout l'audio d'un bloc (plusieurs minutes sur CPU) sans rien
    afficher → l'utilisateur croit que c'est figé et coupe (Ctrl+C). Ce callback
    montre que ça avance. Signature sherpa : `(traités, total) -> int` (0 = continuer)."""
    etat = {"dernier": -pas}

    def cb(traites: int, total: int, *_args) -> int:
        pct = (traites / total * 100.0) if total else 0.0
        if pct >= etat["dernier"] + pas or pct >= 100.0:
            etat["dernier"] = pct
            log.info("  sherpa-onnx : %3.0f %%", pct)
        return 0

    return cb


def diariser_sherpa(audio: np.ndarray) -> tuple[list, float]:
    """Diarisation sherpa-onnx (ONNX, sans licence). Lève si modèles/lib absents."""
    import sherpa_onnx

    seg = str(modeles.chemin_sherpa_segmentation())
    emb = str(modeles.chemin_sherpa_embedding())
    nt = max(1, (os.cpu_count() or 4) - 2)
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=seg),
            num_threads=nt),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=emb, num_threads=nt),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=0.5),
        min_duration_on=0.3, min_duration_off=0.5,
    )
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    log = journal()
    log.info("  sherpa-onnx : traitement de %.0f s d'audio sur CPU (%d threads) — "
             "peut prendre plusieurs minutes…", len(audio) / SR, nt)
    audio32 = audio.astype(np.float32)
    t0 = time.perf_counter()
    try:
        res = sd.process(audio32, _progress_sherpa(log)).sort_by_start_time()
    except TypeError:                     # version de sherpa-onnx sans callback
        res = sd.process(audio32).sort_by_start_time()
    dt = time.perf_counter() - t0
    segments = [(float(s.start), float(s.end), f"Locuteur {s.speaker}") for s in res]
    return segments, dt


def diariser_pyannote(wav: Path, token: str | None = None) -> tuple[list, float]:
    """Diarisation pyannote (gated). En bundle offline, token=None + cache embarqué."""
    from pyannote.audio import Pipeline
    import torch

    pipeline = Pipeline.from_pretrained(modeles.PYANNOTE_PIPELINE, token=token)
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
    else:
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            pipeline.to(torch.device("mps"))
    t0 = time.perf_counter()
    out = pipeline(str(wav))
    dt = time.perf_counter() - t0
    ann = getattr(out, "speaker_diarization", out)
    segments = [(float(tr.start), float(tr.end), f"Locuteur {lbl}")
                for tr, _, lbl in ann.itertracks(yield_label=True)]
    segments.sort(key=lambda x: x[0])
    return segments, dt


def token_hf() -> str | None:
    """Token HF depuis l'env (HF_TOKEN) ou le cache (`hf auth login`)."""
    tok = os.environ.get("HF_TOKEN")
    if tok:
        return tok
    try:
        from huggingface_hub import get_token
        return get_token()
    except Exception:
        journal().debug("token HF introuvable", exc_info=True)
        return None


def ecrire_artefact(chemin: Path, titre: str, segments: list, dt: float, duree: float) -> None:
    lignes = [
        f"# {titre}", "",
        f"- Durée audio : {duree:.0f}s",
        f"- Temps de diarisation : {dt:.1f}s ({dt / duree:.3f}× temps réel)" if duree else "",
        f"- Locuteurs détectés : {nb_locuteurs(segments)}", "", "---", "",
    ]
    for deb, fin, spk in segments:
        lignes.append(f"**{spk}** [{deb:.0f}s → {fin:.0f}s]")
    chemin.write_text("\n".join(lignes), encoding="utf-8")
