"""Transcription via l'endpoint Mistral `/v1/audio/transcriptions` (Voxtral).

Défaut (§7.1, tranché par le spike) : on envoie la piste **entière** telle quelle
(l'Ogg Opus est accepté directement, y compris long — 37,6 min validées en un seul
appel). Le découpage (`decoupage.py`) et le repli WAV ne sont que des **filets de
sécurité**, déclenchés uniquement sur échec — jamais le chemin normal. Depuis le
2026-08-05, le quota (429) déclenche aussi le découpage : en tier gratuit, une piste
longue peut dépasser à elle seule la fenêtre tokens/minute (74 min refusées, alors
que le spike était passé à 37,6 min).

Depuis le 2026-08-18, les **silences sont retirés avant l'envoi** quand cela retire
une part significative de la piste (`silences.py`, §10.2) — une piste système de
réunion physique tient alors en quelques dizaines de secondes au lieu de 98 minutes.
"""
from __future__ import annotations

import logging
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from debrief_meet.core.audio import decoder_audio_16k, preparer_asr
from debrief_meet.core.mistral.client import (
    ClientMistral,
    ErreurFormatMistral,
    ErreurQuotaMistral,
    ErreurReseauMistral,
    ErreurServeurMistral,
)
from debrief_meet.core.mistral.decoupage import LIMITE_SEGMENT_S, decouper_piste
from debrief_meet.core.mistral.silences import PlanCompaction, compacter_piste, plan_compaction

logger = logging.getLogger(__name__)

_MIME_PAR_EXT = {
    ".opus": "audio/ogg", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".flac": "audio/flac",
}

# La fenêtre de rate-limit Mistral est PAR MINUTE glissante : quand la piste
# précédente vient de passer entière en la remplissant, attendre juste au-delà
# d'une minute suffit pour qu'un nouvel envoi entier reparte sur une fenêtre vide.
_ATTENTE_FENETRE_S = 65.0


def _dormir(secondes: float) -> None:
    """Isolé pour être monkeypatché en test (évite de vraiment dormir)."""
    time.sleep(secondes)


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
    #: True si la piste a dû être découpée (repli §10) — le pipeline s'en sert pour
    #: découper directement la piste suivante (son envoi entier échouerait pareil).
    decoupee: bool = False


@dataclass
class AnalysePiste:
    """Durée, détection de silence et plan de compaction — un seul décodage sert aux
    trois (§7.4). `plan` est None si le décodage a échoué."""
    duree_s: float
    silencieuse: bool
    plan: PlanCompaction | None = None


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
    return AnalysePiste(duree_s=len(audio) / 16_000,
                        silencieuse=preparer_asr(audio) is None,
                        plan=plan_compaction(audio))


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
                         langue: str | None, context_bias: list[str],
                         retries_429: bool = True) -> dict:
    data = _construire_donnees(modele, langue, context_bias)
    contenu = chemin.read_bytes()
    r = client.poster_transcription(
        "v1/audio/transcriptions", data, chemin.name, contenu, _mime(chemin),
        retries_429=retries_429)
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


def _transcrire_entier(client: ClientMistral, chemin: Path, modele: str,
                       langue: str | None, context_bias: list[str]) -> TranscriptionMistral:
    payload = _appel_transcription(client, chemin, modele, langue, context_bias,
                                   retries_429=False)
    texte, segs = _parser(payload)
    return TranscriptionMistral(texte=texte, segments=segs, usage=payload.get("usage", {}))


def transcrire_fichier(client: ClientMistral, chemin: Path, modele: str,
                      langue: str | None = None,
                      context_bias: list[str] | None = None,
                      precedente_entiere: bool | None = None,
                      plan: PlanCompaction | None = None) -> TranscriptionMistral:
    """Transcrit une piste, silences retirés si cela vaut le coup (§10.2).

    `plan` vient de `analyser_piste` (aucun décodage supplémentaire). Quand il est
    `utile`, on envoie un WAV ne contenant que les plages sonores puis on remet les
    horodatages dans la timeline d'origine : une piste système de réunion physique
    passe ainsi de 98 min à quelques dizaines de secondes (mesuré : 43 s), ce qui
    économise du quota et réduit d'autant la surface d'hallucination sur du
    quasi-silence (docs/22). La compaction est un **confort** : tout échec (ffmpeg
    absent, erreur de filtre) retombe sur l'envoi intégral plutôt que de faire
    perdre le CR. Les replis ci-dessous s'appliquent ensuite à ce qui est envoyé."""
    if plan is not None and plan.utile:
        try:
            with tempfile.TemporaryDirectory(prefix="mistral_compact_") as tmp:
                compacte = compacter_piste(chemin, Path(tmp), plan)
                logger.info(
                    "Silences retirés de %s : %.0f min → %.0f s envoyées (%d plage(s))",
                    chemin.name, plan.duree_totale_s / 60, plan.duree_gardee_s, len(plan.plages))
                res = _transcrire_avec_replis(client, compacte, modele, langue,
                                              context_bias or [], precedente_entiere)
            return _remettre_horodatages(res, plan)
        except Exception as exc:  # noqa: BLE001 — jamais au prix du CR (cf. docstring)
            logger.warning("Compaction des silences impossible pour %s (%s) — envoi intégral",
                           chemin.name, exc)
    return _transcrire_avec_replis(client, chemin, modele, langue, context_bias or [],
                                   precedente_entiere)


def _remettre_horodatages(res: TranscriptionMistral,
                          plan: PlanCompaction) -> TranscriptionMistral:
    """Replace les segments d'une transcription compactée dans la timeline d'origine."""
    for seg in res.segments:
        seg.debut = plan.vers_original(seg.debut)
        seg.fin = plan.vers_original(seg.fin)
    return res


def _transcrire_avec_replis(client: ClientMistral, chemin: Path, modele: str,
                            langue: str | None, context_bias: list[str],
                            precedente_entiere: bool | None) -> TranscriptionMistral:
    """Envoi entier puis cascade de replis.

    Repli automatique : format refusé (4xx) → transcodage WAV puis réessai ; erreur
    réseau persistante (timeout malgré les reprises du client) → découpage (§10) ;
    erreur serveur persistante (5xx malgré les reprises du client) → découpage aussi.

    Le 5xx a longtemps traversé cette cascade sans être rattrapé : il remontait au
    pipeline et perdait le CR, alors que le découpage était disponible et adapté.
    Terrain 2026-08-31 : 139 min envoyées d'un bloc, 503, aucun repli — or les envois
    réussis du même poste plafonnaient à 36 min, et découper en segments de
    `LIMITE_SEGMENT_S` les aurait tous ramenés dans cet ordre de grandeur. Qu'un 503
    vienne d'un hoquet serveur ou de la taille de l'envoi, découper est la bonne
    réponse dans les deux cas (docs/42 §10.1).

    Quota (429) sur l'envoi entier : le sens du 429 dépend de `precedente_entiere`
    (comment la piste PRÉCÉDENTE de la même réunion a fini — None si aucune) :
    - `True` — la précédente est passée entière et vient de remplir la fenêtre
      tokens/minute : le 429 est transitoire. Attendre `_ATTENTE_FENETRE_S` puis
      retenter ENTIER une fois (préserve la qualité : zéro point de coupe) ;
      découpage seulement si nouveau 429. Vécu chez une utilisatrice le
      2026-08-05 : moi.opus (74 min) passait entier, systeme.opus prenait le
      429 de fenêtre pleine.
    - `False` — la précédente a dû être découpée : un envoi entier échouerait
      pareil, on découpe DIRECTEMENT (économise l'upload d'un gros fichier
      condamné).
    - `None` — pas d'information (première piste) : découpage immédiat, sans
      retry — réessayer en aveugle coûtait 30 s pour rien.
    Les segments du découpage, eux, gardent les retries du client (20/40/60 s) :
    leur 429 est toujours transitoire."""
    if precedente_entiere is False:
        logger.warning("Piste précédente découpée — découpage direct pour %s", chemin.name)
        return _transcrire_decoupe(client, chemin, modele, langue, context_bias)
    try:
        return _transcrire_entier(client, chemin, modele, langue, context_bias)
    except ErreurFormatMistral:
        logger.warning("Format refusé pour %s — repli transcodage WAV 16k", chemin.name)
        return _transcrire_avec_repli_wav(client, chemin, modele, langue, context_bias)
    except ErreurReseauMistral:
        logger.warning("Échec réseau persistant pour %s — repli découpage", chemin.name)
        return _transcrire_decoupe(client, chemin, modele, langue, context_bias)
    except ErreurServeurMistral:
        logger.warning("Erreur serveur persistante pour %s — repli découpage", chemin.name)
        return _transcrire_decoupe(client, chemin, modele, langue, context_bias)
    except ErreurQuotaMistral:
        if precedente_entiere:
            logger.warning(
                "Quota Mistral (429) pour %s — fenêtre remplie par la piste précédente, "
                "nouvel essai entier dans %.0f s", chemin.name, _ATTENTE_FENETRE_S)
            _dormir(_ATTENTE_FENETRE_S)
            try:
                return _transcrire_entier(client, chemin, modele, langue, context_bias)
            except ErreurQuotaMistral:
                logger.warning("Quota Mistral (429) persistant pour %s — repli découpage",
                               chemin.name)
        else:
            logger.warning("Quota Mistral (429) pour %s — repli découpage sans retry", chemin.name)
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
    return TranscriptionMistral(texte=texte_total, segments=segs_total, usage=usage_total,
                                decoupee=True)
