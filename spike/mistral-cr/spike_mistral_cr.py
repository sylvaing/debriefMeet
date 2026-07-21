#!/usr/bin/env python3
"""Spike Mistral — faisabilité « 2 pistes audio → transcription → CR » (cf. docs/42).

Isolé de l'app (pur script, httpx + ffmpeg système). Ne dépend PAS du paquet
debrief_meet. But : valider empiriquement, sur de vraies pistes de réunion, la chaîne
en deux étapes retenue au cadrage :

    piste Moi (.opus/.wav)          ┐
    piste Participants (.opus/.wav) ┘─→  /v1/audio/transcriptions (Voxtral, à la minute)
                                          → fusion chronologique étiquetée
                                          → /v1/chat/completions (modèle texte + prompt CR)
                                          → CR.md

Questions de faisabilité que ce spike répond (voir rapport.json + logs) :
  1. L'endpoint transcription accepte-t-il notre .opus (Ogg Opus) tel quel, ou faut-il
     ré-encoder ? (on tente le fichier d'origine ; repli ffmpeg → wav 16 kHz mono si refus)
  2. Les réunions > ~15 min passent-elles ? (découpage automatique en segments ≤ --limite-min)
  3. La séparation Moi/Participants (2 pistes, SANS diarize) donne-t-elle un CR propre ?
  4. Qualité FR + noms propres (context_bias) ?
  5. Coût réel (minutes audio + tokens CR).

Usage :
    export MISTRAL_API_KEY=...        # jamais en dur, jamais commité
    python spike/mistral-cr/spike_mistral_cr.py \\
        --moi /chemin/reunion_moi.opus \\
        --participants /chemin/reunion_systeme.opus \\
        --sujet "Point produit" --langue fr --noms "Alice Martin,Bob Durand"

Sorties (dans --sortie, gitignoré) : transcript_moi.md, transcript_participants.md,
transcript_fusionne.md, CR.md, rapport.json.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

import httpx

BASE_URL = "https://api.mistral.ai"
EP_TRANSCRIPTION = "/v1/audio/transcriptions"
EP_CHAT = "/v1/chat/completions"

# Tarifs indicatifs (USD) — À VÉRIFIER sur https://mistral.ai/pricing/api/ le jour du run.
# Ne servent qu'à donner un ordre de grandeur dans le rapport, pas une facturation exacte.
TARIF_TRANSCRIPTION_USD_MIN = 0.003          # facturé à la minute d'audio
TARIF_CR_USD_IN_PAR_M = 0.10                 # mistral-small : $/million tokens entrée
TARIF_CR_USD_OUT_PAR_M = 0.30               # mistral-small : $/million tokens sortie

# Copie du prompt CR de l'app (source : src/debrief_meet/core/prompts.py::CR_SIMPLE_CONTENU).
# Dupliqué ici pour garder le spike autonome ; garder synchronisé si le prompt évolue.
PROMPT_CR = """\
Tu es un assistant spécialisé dans la rédaction de comptes-rendus au format markdown de réunion professionnels. À partir de la transcription que je te fournis, génère un CR concis et structuré en respectant les règles suivantes :

Format
- Titre : "CR — [Sujet] — [Date]"
- Participants listés sous le titre
- Séparateurs --- entre les sections
- Sections en gras et numérotées
- Listes à tirets pour les sous-points

Contenu
- Une section courte "Contexte" (1-2 phrases max) pour poser le cadre
- Une section "Points discutés" numérotés, chacun avec un titre en gras et un paragraphe court suivi de tirets si nécessaire
- Une section "Actions" listant uniquement les tâches concrètes avec le responsable, sans reformuler ce qui a déjà été dit plus haut

Règles de rédaction
- Phrases courtes et directes, pas de style administratif lourd
- Ne pas paraphraser inutilement : si un chiffre ou un terme technique est mentionné, le conserver tel quel
- Ne pas inventer de décisions ou d'actions qui ne sont pas explicitement dans la transcription
- Ignorer les apartés, problèmes techniques de connexion et digressions sans rapport avec le sujet

Voici la transcription :"""


def log(msg: str) -> None:
    print(f"[spike] {msg}", flush=True)


# --------------------------------------------------------------------------- ffmpeg


def _exiger(binaire: str) -> str:
    chemin = shutil.which(binaire)
    if not chemin:
        sys.exit(f"'{binaire}' introuvable dans le PATH — installe-le (brew install ffmpeg).")
    return chemin


def duree_secondes(chemin: Path) -> float:
    """Durée du fichier audio via ffprobe."""
    ffprobe = _exiger("ffprobe")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(chemin)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def transcoder_wav16k(source: Path, dest: Path) -> None:
    """Ré-encode en WAV mono 16 kHz (format universellement accepté par l'API)."""
    ffmpeg = _exiger("ffmpeg")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
         "-ac", "1", "-ar", "16000", str(dest)],
        check=True,
    )


def decouper_copie(source: Path, dossier: Path, limite_s: int) -> list[Path]:
    """Découpe la source en segments ≤ limite_s SANS ré-encoder (Opus reste Opus).

    Chunks compacts (~2-3 Mo pour 14 min d'Opus 24 kbps) → upload rapide et robuste,
    contrairement à un WAV 16 kHz (~27 Mo/14 min) qui exposait aux coupures réseau.
    Sortie en conteneur Ogg (`.ogg`), mime audio/ogg. `-reset_timestamps 1` : chaque
    segment redémarre à t=0, donc l'offset externe (i × limite_s) suffit à recaler.
    """
    ffmpeg = _exiger("ffmpeg")
    motif = str(dossier / "seg_%03d.ogg")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
         "-f", "segment", "-segment_time", str(limite_s),
         "-reset_timestamps", "1", "-c", "copy", motif],
        check=True,
    )
    return sorted(dossier.glob("seg_*.ogg"))


# --------------------------------------------------------------------------- API


@dataclass
class Segment:
    debut: float
    fin: float
    texte: str
    locuteur: str = ""


@dataclass
class ResultatPiste:
    locuteur: str
    texte: str = ""
    segments: list[Segment] = field(default_factory=list)
    minutes: float = 0.0
    upload_direct_ok: bool | None = None  # None = non testé (fichier découpé)


def _mime(chemin: Path) -> str:
    return {
        ".opus": "audio/ogg", ".ogg": "audio/ogg", ".wav": "audio/wav",
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".flac": "audio/flac",
    }.get(chemin.suffix.lower(), "application/octet-stream")


def _parser_segments(payload: dict, offset: float) -> tuple[str, list[Segment]]:
    """Extrait texte + segments d'une réponse transcription, en décalant les temps."""
    texte = (payload.get("text") or "").strip()
    segs: list[Segment] = []
    for s in payload.get("segments") or []:
        debut = float(s.get("start", s.get("debut", 0.0))) + offset
        fin = float(s.get("end", s.get("fin", debut))) + offset
        t = (s.get("text") or s.get("texte") or "").strip()
        if t:
            segs.append(Segment(debut=debut, fin=fin, texte=t))
    if not segs and texte:  # pas de segments renvoyés → un bloc unique
        segs.append(Segment(debut=offset, fin=offset, texte=texte))
    return texte, segs


def transcrire_unite(client: httpx.Client, chemin: Path, modele: str,
                     langue: str | None, context_bias: list[str],
                     offset: float) -> dict:
    """Un appel /v1/audio/transcriptions. Lève httpx.HTTPStatusError sur erreur.

    NB httpx : en multipart (avec `files`), `data` DOIT être un dict ; une valeur-liste
    est émise en champs répétés (une liste de tuples plante l'encodage du corps).
    """
    data: dict[str, object] = {"model": modele, "timestamp_granularities": "segment"}
    if langue:
        data["language"] = langue
    if context_bias:
        data["context_bias"] = context_bias[:100]  # → champs `context_bias` répétés
    with chemin.open("rb") as f:
        files = {"file": (chemin.name, f, _mime(chemin))}
        r = client.post(EP_TRANSCRIPTION, data=data, files=files)
    r.raise_for_status()
    payload = r.json()
    payload["_offset"] = offset
    return payload


# Codes HTTP qui signalent un fichier/format refusé (→ repli transcodage WAV).
_CODES_FORMAT = {400, 415, 422}


def transcrire_avec_repli(client: httpx.Client, chemin: Path, modele: str,
                          langue: str | None, context_bias: list[str], offset: float,
                          tmp: Path, tentatives: int = 3,
                          repli_wav: bool = True) -> tuple[dict, bool]:
    """Transcrit une unité, avec reprises réseau + repli WAV si le format est refusé.

    Retourne (payload, format_origine_ok). `format_origine_ok` = True si le fichier a
    été accepté tel quel (sans transcodage), None-équivalent False sinon.
    `repli_wav=False` (mode diagnostic --pas-de-decoupage) : on remonte l'erreur brute
    au lieu de transcoder, pour observer la vraie réponse de l'API.
    """
    cible, format_ok = chemin, True
    for essai in range(1, tentatives + 1):
        try:
            return transcrire_unite(client, cible, modele, langue, context_bias, offset), format_ok
        except httpx.HTTPStatusError as e:
            if repli_wav and e.response.status_code in _CODES_FORMAT and format_ok:
                log(f"    format refusé ({e.response.status_code}) → repli transcodage WAV 16k")
                wav = tmp / (cible.stem + "_16k.wav")
                transcoder_wav16k(cible, wav)
                cible, format_ok = wav, False
                continue  # réessaie immédiatement en WAV
            raise  # autre erreur HTTP (auth, quota, durée…) : on remonte
        except httpx.TransportError as e:  # broken pipe, read/connect error, veille…
            if essai == tentatives:
                raise
            attente = 2 * essai
            log(f"    coupure réseau ({type(e).__name__}) — reprise {essai}/{tentatives - 1} "
                f"dans {attente}s")
            time.sleep(attente)
    raise RuntimeError("inatteignable")


@dataclass
class Unite:
    """Une unité transcriptible indépendante (fichier entier court, ou 1 segment)."""
    locuteur: str
    chemin: Path
    offset: float
    index: int  # ordre au sein de la piste (pour recoller texte + segments)


def preparer_unites(chemin: Path, locuteur: str, limite_s: int, tmp: Path,
                    decouper: bool = True) -> tuple[float, list[Unite]]:
    """Découpe si nécessaire et renvoie (minutes, unités). Aucun appel réseau ici.

    `decouper=False` (--pas-de-decoupage) : envoie TOUJOURS le fichier entier en 1 unité,
    même > limite → sert à tester si Voxtral accepte une longue piste sans découpage.
    """
    duree = duree_secondes(chemin)
    log(f"{locuteur} : {chemin.name} ({duree / 60:.1f} min)")
    if not decouper:
        log(f"  → 1 unité SANS découpage ({chemin.suffix}, {duree / 60:.1f} min) — test direct")
        return duree / 60, [Unite(locuteur, chemin, 0.0, 0)]
    if duree <= limite_s:
        log(f"  → 1 unité (upload direct {chemin.suffix})")
        return duree / 60, [Unite(locuteur, chemin, 0.0, 0)]
    dossier = tmp / (chemin.stem + "_segments")
    dossier.mkdir(exist_ok=True)
    segments = decouper_copie(chemin, dossier, limite_s)
    tailles = ", ".join(f"{p.stat().st_size // 1024} Ko" for p in segments)
    log(f"  → {len(segments)} segment(s) Opus ({tailles})")
    return duree / 60, [Unite(locuteur, p, i * limite_s, i) for i, p in enumerate(segments)]


def transcrire_unite_chrono(client: httpx.Client, u: Unite, modele: str,
                            langue: str | None, context_bias: list[str],
                            tmp: Path, repli_wav: bool = True
                            ) -> tuple[Unite, dict, bool, float]:
    """Transcrit une unité (avec reprises/repli) en la chronométrant. Pour le pool."""
    t = time.perf_counter()
    payload, format_ok = transcrire_avec_repli(
        client, u.chemin, modele, langue, context_bias, u.offset, tmp, repli_wav=repli_wav)
    dt = time.perf_counter() - t
    log(f"  ⇠ [{u.locuteur} #{u.index + 1}] {dt:.1f}s "
        f"({len(payload.get('text') or '')} car.)")
    return u, payload, format_ok, dt


def assembler_piste(locuteur: str, minutes: float,
                    resultats: dict[int, tuple[dict, bool]]) -> ResultatPiste:
    """Recolle les unités d'une piste (triées par index) en un ResultatPiste."""
    res = ResultatPiste(locuteur=locuteur, minutes=minutes)
    origine_ok = True
    for _idx, (payload, format_ok) in sorted(resultats.items()):
        origine_ok = origine_ok and format_ok
        texte, segs = _parser_segments(payload, payload.get("_offset", 0.0))
        for s in segs:
            s.locuteur = locuteur
        res.segments.extend(segs)
        res.texte = (res.texte + " " + texte).strip()
    res.upload_direct_ok = origine_ok
    log(f"  ✓ {locuteur} : {len(res.texte)} car., {len(res.segments)} segments, "
        f"format d'origine accepté={origine_ok}")
    return res


def fusionner(pistes: list[ResultatPiste]) -> str:
    """Entrelace les segments de toutes les pistes par timestamp → markdown étiqueté."""
    tous = sorted(
        (s for p in pistes for s in p.segments),
        key=lambda s: s.debut,
    )
    lignes: list[str] = []
    courant = None
    tampon: list[str] = []

    def vider() -> None:
        if courant and tampon:
            lignes.append(f"**{courant} :** " + " ".join(tampon).strip())
            lignes.append("")

    for s in tous:
        if s.locuteur != courant:
            vider()
            courant = s.locuteur
            tampon = []
        tampon.append(s.texte)
    vider()
    return "\n".join(lignes).strip()


def generer_cr(client: httpx.Client, transcript: str, modele: str,
               sujet: str | None) -> tuple[str, dict]:
    """Un appel /v1/chat/completions avec le prompt CR debriefMeet + le transcript."""
    invite = PROMPT_CR
    if sujet:
        invite += f"\n(Sujet de la réunion : {sujet})"
    corps = {
        "model": modele,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": f"{invite}\n\n{transcript}"}],
    }
    r = client.post(EP_CHAT, json=corps)
    r.raise_for_status()
    payload = r.json()
    texte = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    return texte, usage


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description="Spike Mistral : 2 pistes → transcription → CR")
    ap.add_argument("--moi", required=True, type=Path, help="piste micro (Moi)")
    ap.add_argument("--participants", required=True, type=Path, help="piste système (Participants)")
    ap.add_argument("--sujet", default=None, help="sujet de la réunion (indice pour le CR)")
    ap.add_argument("--langue", default="fr", help="code langue (défaut fr ; vide = auto)")
    ap.add_argument("--noms", default="", help="noms propres, séparés par des virgules (context_bias)")
    ap.add_argument("--modele-transcription", default="voxtral-mini-latest")
    ap.add_argument("--modele-cr", default="mistral-small-latest")
    ap.add_argument("--limite-min", type=int, default=14, help="taille max d'un segment (min)")
    ap.add_argument("--paralleles", type=int, default=4, help="appels transcription simultanés")
    ap.add_argument("--pas-de-decoupage", action="store_true",
                    help="envoyer chaque piste entière sans découpage (test de la limite Voxtral) ; "
                         "désactive aussi le repli WAV pour voir la réponse brute de l'API")
    ap.add_argument("--sortie", type=Path, default=Path(__file__).parent / "sorties")
    args = ap.parse_args()

    cle = os.environ.get("MISTRAL_API_KEY")
    if not cle:
        sys.exit("Définis MISTRAL_API_KEY dans l'environnement (jamais en dur).")
    for p in (args.moi, args.participants):
        if not p.exists():
            sys.exit(f"Fichier introuvable : {p}")

    context_bias = [n.strip() for n in args.noms.split(",") if n.strip()]
    langue = args.langue or None
    limite_s = args.limite_min * 60
    args.sortie.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"Bearer {cle}", "Accept": "application/json"}
    timeout = httpx.Timeout(connect=10.0, read=600.0, write=600.0, pool=10.0)
    t0 = time.perf_counter()
    rapport: dict = {"modeles": {"transcription": args.modele_transcription, "cr": args.modele_cr},
                     "langue": langue, "context_bias": context_bias}

    with tempfile.TemporaryDirectory(prefix="spike_mistral_") as tmpdir:
        tmp = Path(tmpdir)
        # Découpage (local, rapide) puis fan-out : toutes les unités des 2 pistes en parallèle.
        decouper = not args.pas_de_decoupage
        min_moi, u_moi = preparer_unites(args.moi, "Moi", limite_s, tmp, decouper=decouper)
        min_part, u_part = preparer_unites(args.participants, "Participants", limite_s, tmp,
                                           decouper=decouper)
        toutes = u_moi + u_part
        par_locuteur: dict[str, dict[int, tuple[dict, bool]]] = {"Moi": {}, "Participants": {}}

        with httpx.Client(base_url=BASE_URL, headers=headers, timeout=timeout) as client:
            t_trans = time.perf_counter()
            if args.pas_de_decoupage:
                log("mode --pas-de-decoupage : pistes entières, repli WAV désactivé (réponse brute)")
            log(f"transcription de {len(toutes)} unité(s), {args.paralleles} en parallèle …")
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max(1, min(args.paralleles, len(toutes)))) as ex:
                futs = [ex.submit(transcrire_unite_chrono, client, u,
                                  args.modele_transcription, langue, context_bias, tmp,
                                  not args.pas_de_decoupage)
                        for u in toutes]
                try:
                    for fut in concurrent.futures.as_completed(futs):
                        u, payload, format_ok, _dt = fut.result()
                        par_locuteur[u.locuteur][u.index] = (payload, format_ok)
                except httpx.HTTPStatusError as e:
                    sys.exit(f"Erreur API transcription {e.response.status_code} : "
                             f"{e.response.text[:500]}")
                except httpx.TransportError as e:
                    sys.exit(f"Erreur réseau transcription : {type(e).__name__}: {e}")
            log(f"transcription terminée en {time.perf_counter() - t_trans:.1f}s")

            piste_moi = assembler_piste("Moi", min_moi, par_locuteur["Moi"])
            piste_part = assembler_piste("Participants", min_part, par_locuteur["Participants"])

            # Sorties intermédiaires
            (args.sortie / "transcript_moi.md").write_text(piste_moi.texte, encoding="utf-8")
            (args.sortie / "transcript_participants.md").write_text(piste_part.texte, encoding="utf-8")
            transcript = fusionner([piste_moi, piste_part])
            (args.sortie / "transcript_fusionne.md").write_text(transcript, encoding="utf-8")
            log(f"transcript fusionné : {len(transcript)} caractères")

            log("génération du CR …")
            try:
                cr, usage = generer_cr(client, transcript, args.modele_cr, args.sujet)
            except httpx.HTTPStatusError as e:
                sys.exit(f"Erreur API CR {e.response.status_code} : {e.response.text[:500]}")
            (args.sortie / "CR.md").write_text(cr, encoding="utf-8")

    # Rapport / coût estimé
    minutes = piste_moi.minutes + piste_part.minutes
    tok_in = usage.get("prompt_tokens", 0)
    tok_out = usage.get("completion_tokens", 0)
    cout = (minutes * TARIF_TRANSCRIPTION_USD_MIN
            + tok_in / 1e6 * TARIF_CR_USD_IN_PAR_M
            + tok_out / 1e6 * TARIF_CR_USD_OUT_PAR_M)
    rapport.update({
        "minutes_audio_total": round(minutes, 2),
        "upload_direct_ok": {"moi": piste_moi.upload_direct_ok,
                             "participants": piste_part.upload_direct_ok},
        "cr_usage": usage,
        "cout_estime_usd": round(cout, 4),
        "duree_run_s": round(time.perf_counter() - t0, 1),
        "avertissement_cout": "tarifs indicatifs, à vérifier sur mistral.ai/pricing/api",
    })
    (args.sortie / "rapport.json").write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")

    log("──────── FEASIBILITÉ ────────")
    log(f"upload .opus direct accepté ? moi={piste_moi.upload_direct_ok} "
        f"participants={piste_part.upload_direct_ok}")
    log(f"minutes audio : {minutes:.1f} | tokens CR : {tok_in}+{tok_out} "
        f"| coût estimé : ~${cout:.3f}")
    log(f"sorties écrites dans : {args.sortie}")
    log("→ relire CR.md et transcript_fusionne.md pour juger la qualité.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
