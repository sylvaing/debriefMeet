"""Mesure RTF + mémoire pour n'importe quel moteur exposant charger/transcrire/liberer."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from spike.backends_windows import qualite
from spike.backends_windows.journalisation import journal

SR = 16_000
DUREE_TRANCHE_S = 30.0


class MesureMemoire:
    """Échantillonne le pic RAM (RSS) et VRAM pendant un bloc `with`."""

    def __init__(self, intervalle: float = 0.25) -> None:
        self._intervalle = intervalle
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc = None
        self.ram_pic_mb: float | None = None
        self.vram_pic_mb: float | None = None

    def __enter__(self) -> "MesureMemoire":
        try:
            import psutil
            self._proc = psutil.Process()
            self.ram_pic_mb = self._proc.memory_info().rss / 1e6
            self._thread = threading.Thread(target=self._boucle, daemon=True)
            self._thread.start()
        except Exception:
            journal().debug("psutil indisponible : pic RAM non mesuré", exc_info=True)
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass
        return self

    def _boucle(self) -> None:
        while not self._stop.wait(self._intervalle):
            try:
                rss = self._proc.memory_info().rss / 1e6
                if self.ram_pic_mb is None or rss > self.ram_pic_mb:
                    self.ram_pic_mb = rss
            except Exception:
                break

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        try:
            import torch
            if torch.cuda.is_available():
                self.vram_pic_mb = round(torch.cuda.max_memory_allocated() / 1e6, 1)
        except Exception:
            pass
        if self.ram_pic_mb is not None:
            self.ram_pic_mb = round(self.ram_pic_mb, 1)


def decouper(audio: np.ndarray, sr: int = SR, duree_tranche_s: float = DUREE_TRANCHE_S) -> list[np.ndarray]:
    """Découpe l'audio en tranches de 30 s (comme le mode Réunion)."""
    n = max(1, int(duree_tranche_s * sr))
    return [audio[i:i + n] for i in range(0, len(audio), n)]


def mesurer_moteur(moteur, taille: str, tranches: list[np.ndarray],
                   sr: int, langue: str | None, artefact: Path) -> dict:
    """Transcrit toutes les tranches et collecte RTF/mémoire/hallucination. Peut lever."""
    log = journal()
    rtf_tranches: list[float] = []
    textes: list[str] = []
    n_segments = 0
    total_dt = 0.0
    total_dur = 0.0
    langue_detectee: str | None = None

    with MesureMemoire() as mem:
        t0 = time.perf_counter()
        moteur.charger(taille)
        load_s = round(time.perf_counter() - t0, 2)
        log.info("  [%s] modèle chargé en %.1f s, %d tranches…", taille, load_s, len(tranches))
        for tr in tranches:
            dur = len(tr) / sr
            if dur <= 0:
                continue
            t1 = time.perf_counter()
            res = moteur.transcrire(tr, langue)
            dt = time.perf_counter() - t1
            total_dt += dt
            total_dur += dur
            rtf_tranches.append(round(dt / dur, 3))
            textes.append(res.texte)
            n_segments += len(res.segments)
            langue_detectee = langue_detectee or res.langue_detectee
    moteur.liberer()

    texte = " ".join(t for t in textes if t).strip()
    rtf_moyen = round(total_dt / total_dur, 3) if total_dur else None
    derniers = rtf_tranches[-3:] if rtf_tranches else []
    rtf_fin = round(sum(derniers) / len(derniers), 3) if derniers else None
    ratio_rep = qualite.calculer_ratio_repetition(texte)
    hallu = ratio_rep > qualite.SEUIL_REPETITION

    try:
        artefact.write_text(texte, encoding="utf-8")
    except Exception:
        log.debug("écriture artefact %s échouée", artefact, exc_info=True)

    return {
        "modele": taille,
        "statut": "ok",
        "load_s": load_s,
        "infer_s": round(total_dt, 2),
        "rtf_moyen": rtf_moyen,
        "rtf_fin": rtf_fin,
        "rtf_tranches": rtf_tranches,
        "ram_pic_mb": mem.ram_pic_mb,
        "vram_pic_mb": mem.vram_pic_mb,
        "n_segments": n_segments,
        "n_mots": len(qualite.normaliser(texte)),
        "langue_detectee": langue_detectee,
        "ratio_repetition": ratio_rep,
        "hallucination": hallu,
        "artefact_txt": artefact.name,
        "_texte": texte,
    }
