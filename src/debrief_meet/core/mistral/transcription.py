"""Transcription via l'endpoint Mistral `/v1/audio/transcriptions` (Voxtral).

Défaut (§7.1, tranché par le spike) : on envoie la piste **entière** telle quelle
(l'Ogg Opus est accepté directement, y compris long — 37,6 min validées en un seul
appel). Le découpage (`decoupage.py`) et le repli WAV ne sont que des **filets de
sécurité**, déclenchés uniquement sur échec — jamais le chemin normal.
"""
from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from debrief_meet.core.audio import decoder_audio_16k, preparer_asr
from debrief_meet.core.mistral.client import ClientMistral, ErreurFormatMistral, ErreurReseauMistral
from debrief_meet.core.mistral.decoupage import LIMITE_SEGMENT_S, decouper_piste

logger = logging.getLogger(__name__)

_MIME_PAR_EXT = {
    ".opus": "audio/ogg", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".flac": "audio/flac",
}


@dataclass
class Segment:
    debut: float
    fin: float
    texte: str


@dataclass
class TranscriptionMistral:
    texte: str
    segments: list[Segment] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


@dataclass
class AnalysePiste:
    """Durée + détection de silence — un seul décodage sert aux deux (§7.4)."""
    duree_s: float
    silencieuse: bool


def _mime(chemin: Path) -> str:
    return _MIME_PAR_EXT.get(chemin.suffix.lower(), "application/octet-stream")


def analyser_piste(chemin: Path) -> AnalysePiste:
    """Durée (s) et détection de silence (§7.4).

    Le verdict « silencieuse » réutilise `core.audio.preparer_asr` (normalisation PUIS
    porte anti-silence, docs/27), et non le RMS brut : une piste faible mais parlée
    (micro discret / post-AEC, ex. RMS ~0,0076) serait rejetée à tort par une simple
    comparaison au seuil, alors que le vrai chemin de transcription la normalise d'abord.
    Décodage impossible (fichier corrompu…) : traité comme non silencieux, durée nulle
    — Voxtral tranchera. Ne lève jamais."""
    try:
        audio = decoder_audio_16k(chemin)
    except Exception:  # noqa: BLE001 — laisser Voxtral trancher plutôt que planter ici
        return AnalysePiste(duree_s=0.0, silencieuse=False)
    if not len(audio):
        return AnalysePiste(duree_s=0.0, silencieuse=True)
    return AnalysePiste(duree_s=len(audio) / 16_000, silencieuse=preparer_asr(audio) is None)


def _jetons_context_bias(noms: list[str]) -> list[str]:
    """Voxtral (`context_bias_input_method=comma_separated`) refuse tout item contenant
    une virgule OU une espace (400, code 3051, constaté 2026-07-28 avec les invités
    BlueMind) : un nom complet « Sylvain Garcia » est donc invalide tel quel. On découpe
    chaque entrée en jetons (mots), dédoublonnés en conservant l'ordre — « Sylvain Garcia »
    → [« Sylvain », « Garcia »]. Le biais reste utile (Voxtral favorise ces mots)."""
    jetons: list[str] = []
    vus: set[str] = set()
    for nom in noms:
        for jeton in re.split(r"[,\s]+", (nom or "").strip()):
            if jeton and jeton not in vus:
                vus.add(jeton)
                jetons.append(jeton)
    return jetons


def _construire_donnees(modele: str, langue: str | None, context_bias: list[str]) -> dict[str, object]:
    """`data` DOIT être un dict en multipart httpx (valeurs-listes = champs répétés) —
    une liste de tuples casse l'encodage du corps (piège rencontré par le spike)."""
    data: dict[str, object] = {"model": modele, "timestamp_granularities": "segment"}
    if langue:
        data["language"] = langue
    jetons = _jetons_context_bias(context_bias)
    if jetons:
        data["context_bias"] = jetons[:100]
    return data


def _appel_transcription(client: ClientMistral, chemin: Path, modele: str,
                         langue: str | None, context_bias: list[str]) -> dict:
    data = _construire_donnees(modele, langue, context_bias)
    contenu = chemin.read_bytes()
    r = client.poster_transcription(
        "v1/audio/transcriptions", data, chemin.name, contenu, _mime(chemin))
    return r.json()


def _parser(payload: dict, offset: float = 0.0) -> tuple[str, list[Segment]]:
    texte = (payload.get("text") or "").strip()
    segs: list[Segment] = []
    for s in payload.get("segments") or []:
        debut = float(s.get("start", 0.0)) + offset
        fin = float(s.get("end", debut)) + offset
        t = (s.get("text") or "").strip()
        if t:
            segs.append(Segment(debut=debut, fin=fin, texte=t))
    if not segs and texte:
        segs.append(Segment(debut=offset, fin=offset, texte=texte))
    return texte, segs


def transcrire_fichier(client: ClientMistral, chemin: Path, modele: str,
                      langue: str | None = None,
                      context_bias: list[str] | None = None) -> TranscriptionMistral:
    """Transcrit un fichier audio **entier** (chemin normal, §7.1).

    Repli automatique : format refusé (4xx) → transcodage WAV puis réessai ; erreur
    réseau persistante (timeout malgré les reprises du client) → découpage (§10)."""
    context_bias = context_bias or []
    try:
        payload = _appel_transcription(client, chemin, modele, langue, context_bias)
        texte, segs = _parser(payload)
        return TranscriptionMistral(texte=texte, segments=segs, usage=payload.get("usage", {}))
    except ErreurFormatMistral:
        logger.warning("Format refusé pour %s — repli transcodage WAV 16k", chemin.name)
        return _transcrire_avec_repli_wav(client, chemin, modele, langue, context_bias)
    except ErreurReseauMistral:
        logger.warning("Échec réseau persistant pour %s — repli découpage", chemin.name)
        return _transcrire_decoupe(client, chemin, modele, langue, context_bias)


def _transcrire_avec_repli_wav(client: ClientMistral, chemin: Path, modele: str,
                               langue: str | None, context_bias: list[str]) -> TranscriptionMistral:
    import subprocess

    from debrief_meet.core.fichiers import ErreurFfmpegIntrouvable, chemin_ffmpeg

    exe = chemin_ffmpeg()
    if exe is None:
        raise ErreurFfmpegIntrouvable()
    with tempfile.TemporaryDirectory(prefix="mistral_repli_") as tmp:
        wav = Path(tmp) / (chemin.stem + "_16k.wav")
        subprocess.run(
            [exe, "-y", "-loglevel", "error", "-i", str(chemin), "-ac", "1", "-ar", "16000", str(wav)],
            check=True, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        payload = _appel_transcription(client, wav, modele, langue, context_bias)
    texte, segs = _parser(payload)
    return TranscriptionMistral(texte=texte, segments=segs, usage=payload.get("usage", {}))


def _transcrire_decoupe(client: ClientMistral, chemin: Path, modele: str,
                        langue: str | None, context_bias: list[str]) -> TranscriptionMistral:
    with tempfile.TemporaryDirectory(prefix="mistral_decoupe_") as tmp:
        segments_fichiers = decouper_piste(chemin, Path(tmp))
        texte_total = ""
        segs_total: list[Segment] = []
        usage_total: dict = {}
        for i, seg_chemin in enumerate(segments_fichiers):
            offset = i * LIMITE_SEGMENT_S
            payload = _appel_transcription(client, seg_chemin, modele, langue, context_bias)
            texte, segs = _parser(payload, offset=offset)
            texte_total = (texte_total + " " + texte).strip()
            segs_total.extend(segs)
            usage_seg = payload.get("usage") or {}
            for cle, valeur in usage_seg.items():
                usage_total[cle] = usage_total.get(cle, 0) + (valeur or 0)
    return TranscriptionMistral(texte=texte_total, segments=segs_total, usage=usage_total)
