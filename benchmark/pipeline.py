"""Orchestration du pipeline benchmark : transcription (sweep) + diarisation.

Instrumente chaque étape : RTF moyen ET par tranche (révèle le throttling),
mémoire pic RAM/VRAM (décision mode réunion 2 flux), qualité (WER relatif à
large-v3). Chaque étape est isolée : un échec dégrade le rapport, ne casse pas le run.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from benchmark import diarisation, modeles, moteurs, qualite
from benchmark.journalisation import journal

SR = 16_000
DUREE_TRANCHE_S = 30.0


class MesureMemoire:
    """Échantillonne le pic de RAM (RSS) et de VRAM pendant un bloc `with`."""

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


def tronquer(audio: np.ndarray, sr: int, duree_max_s: float) -> np.ndarray:
    """Limite l'audio aux `duree_max_s` premières secondes (0 ou négatif = pas de limite).

    Sert à raccourcir le sweep transcription (RTF/WER/throttling restent valides sur
    ~10 min) sans toucher la diarisation, qui garde l'audio complet pour la diversité
    de locuteurs.
    """
    if duree_max_s and duree_max_s > 0:
        return audio[:int(duree_max_s * sr)]
    return audio


def decouper(audio: np.ndarray, sr: int = SR, duree_tranche_s: float = DUREE_TRANCHE_S) -> list[np.ndarray]:
    """Découpe l'audio en tranches (comme le mode réunion) pour mesurer le débit soutenu."""
    n = max(1, int(duree_tranche_s * sr))
    return [audio[i:i + n] for i in range(0, len(audio), n)]


def _mesurer_transcription(moteur, taille: str, tranches: list[np.ndarray],
                           sr: int, langue: str | None, artefact: Path) -> dict:
    """Transcrit toutes les tranches avec un moteur déjà construit, en mesurant
    tout (RTF par tranche, mémoire pic). Commun à faster-whisper et OpenVINO. Peut lever."""
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
        log.info("  [%s] modèle chargé en %.1fs, transcription de %d tranches…",
                 taille, load_s, len(tranches))
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

    try:
        artefact.write_text(texte, encoding="utf-8")
    except Exception:
        log.debug("écriture artefact %s échouée", artefact, exc_info=True)

    return {
        "modele": taille,
        "load_s": load_s,
        "infer_s": round(total_dt, 2),
        "rtf_moyen": rtf_moyen,
        "rtf_fin": rtf_fin,
        "rtf_tranches": rtf_tranches,
        "ram_pic_mb": mem.ram_pic_mb,
        "vram_pic_mb": mem.vram_pic_mb,
        "n_segments": n_segments,
        "langue": langue_detectee,
        "n_mots": len(qualite.normaliser(texte)),
        "artefact_txt": artefact.name,
        "_texte": texte,  # interne, retiré du rapport final
    }


def transcrire_modele(mode: dict, taille: str, tranches: list[np.ndarray],
                      sr: int, langue: str | None, dossier: Path) -> dict:
    """Transcrit toutes les tranches avec faster-whisper/mlx, en mesurant tout. Peut lever."""
    moteur = moteurs.MoteurBench(mode)
    return _mesurer_transcription(
        moteur, taille, tranches, sr, langue, dossier / f"transcription_{taille}.txt")


def _appliquer_wer_relatif(resultats: list[dict]) -> None:
    """Calcule le WER de chaque résultat relativement au plus gros modèle réussi
    (large-v3 → medium → small). Attend une clé interne `_texte` ; la retire ensuite.
    Partagé par le sweep faster-whisper et le comparatif OpenVINO."""
    reussis = [r for r in resultats if r.get("_texte")]
    reference = None
    for pref in ("large-v3", "medium", "small"):
        for r in reussis:
            if r.get("modele") == pref:
                reference = r
                break
        if reference:
            break
    if reference is None and reussis:
        reference = reussis[-1]

    for r in resultats:
        if "_texte" in r:
            if reference is not None:
                r["wer"] = round(qualite.wer(reference["_texte"], r["_texte"]), 4)
                r["wer_reference"] = reference["modele"]
            del r["_texte"]


def executer_sweep(mode: dict, tailles: list[str], audio: np.ndarray, sr: int,
                   langue: str | None, dossier: Path) -> list[dict]:
    """Lance le sweep de modèles ; WER relatif à large-v3 (ou plus gros réussi)."""
    log = journal()
    tranches = decouper(audio, sr)
    resultats: list[dict] = []
    for taille in tailles:
        log.info("Transcription — modèle %s", taille)
        try:
            resultats.append(transcrire_modele(mode, taille, tranches, sr, langue, dossier))
        except Exception as exc:
            log.warning("Modèle %s : ÉCHEC (%s)", taille, exc, exc_info=True)
            resultats.append({"modele": taille, "erreur": str(exc)})

    _appliquer_wer_relatif(resultats)
    return resultats


def _ecrire_wav_temporaire(audio: np.ndarray, sr: int, chemin: Path) -> None:
    from scipy.io import wavfile

    pcm = np.clip(audio, -1.0, 1.0)
    wavfile.write(chemin, sr, (pcm * 32767).astype(np.int16))


def executer_diarisation(audio: np.ndarray, sr: int, dossier: Path,
                         token: str | None = None) -> list[dict]:
    """Diarisation comparative sherpa + pyannote. Chaque moteur isolé."""
    log = journal()
    duree = len(audio) / sr
    resultats: list[dict] = []

    # sherpa-onnx (np array direct)
    log.info("Diarisation — sherpa-onnx")
    try:
        with MesureMemoire() as mem:
            segs, dt = diarisation.diariser_sherpa(audio)
        art = dossier / "diarisation_sherpa.md"
        diarisation.ecrire_artefact(art, "Diarisation — sherpa-onnx", segs, dt, duree)
        resultats.append({"moteur": "sherpa", "rtf": round(dt / duree, 3) if duree else None,
                          "n_locuteurs": diarisation.nb_locuteurs(segs),
                          "ram_pic_mb": mem.ram_pic_mb, "artefact_md": art.name})
    except Exception as exc:
        log.warning("sherpa-onnx : ÉCHEC (%s)", exc, exc_info=True)
        resultats.append({"moteur": "sherpa", "erreur": str(exc)})

    # pyannote (nécessite un WAV sur disque)
    log.info("Diarisation — pyannote")
    wav = dossier / "_diar_pyannote.wav"
    try:
        _ecrire_wav_temporaire(audio, sr, wav)
        with MesureMemoire() as mem:
            segs, dt = diarisation.diariser_pyannote(wav, token)
        art = dossier / "diarisation_pyannote.md"
        diarisation.ecrire_artefact(art, "Diarisation — pyannote", segs, dt, duree)
        resultats.append({"moteur": "pyannote", "rtf": round(dt / duree, 3) if duree else None,
                          "n_locuteurs": diarisation.nb_locuteurs(segs),
                          "ram_pic_mb": mem.ram_pic_mb, "artefact_md": art.name})
    except Exception as exc:
        log.warning("pyannote : ÉCHEC (%s)", exc, exc_info=True)
        resultats.append({"moteur": "pyannote", "erreur": str(exc)})
    finally:
        # Nettoyage systématique du WAV temporaire (≈57 Mo), même si pyannote échoue
        # — sinon il est ramassé par l'emballage et alourdit chaque zip renvoyé.
        try:
            wav.unlink()
        except Exception:
            pass

    return resultats


def executer_comparatif_openvino(tailles: list[str], audio: np.ndarray, sr: int,
                                 langue: str | None, dossier: Path,
                                 device: str = "GPU") -> list[dict]:
    """Sweep de transcription via OpenVINO sur GPU Intel, en comparatif du sweep
    faster-whisper CPU. Même instrumentation (RTF, mémoire, WER interne). Chaque
    modèle isolé : un échec dégrade la section, ne casse pas le run."""
    from benchmark import moteur_openvino

    log = journal()
    tranches = decouper(audio, sr)
    resultats: list[dict] = []
    for taille in tailles:
        log.info("Transcription OpenVINO — modèle %s (device=%s)", taille, device)
        try:
            moteur = moteur_openvino.MoteurOpenVINO(device=device)
            base = _mesurer_transcription(
                moteur, taille, tranches, sr, langue,
                dossier / f"transcription_openvino_{taille}.txt")
            base["moteur"] = "openvino"
            base["device"] = device
            resultats.append(base)
        except Exception as exc:
            log.warning("OpenVINO %s : ÉCHEC (%s)", taille, exc, exc_info=True)
            resultats.append({"moteur": "openvino", "modele": taille, "erreur": str(exc)})

    _appliquer_wer_relatif(resultats)
    return resultats
