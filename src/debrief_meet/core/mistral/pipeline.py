"""Orchestration bout-en-bout (§4) : `.md` de réunion → `<stem>_CR.md`.

Point d'entrée **pur** (aucun Qt) appelé par le worker de fond (`ui/generateur_cr_mistral.py`).
Logique adaptative (décision 1, §1) :

1. par défaut, réutilise le **transcript local** déjà produit par l'app (rapide, pas
   d'upload audio) ;
2. repli automatique vers la **transcription Voxtral** des pistes retenues quand il
   n'y a pas de transcript local exploitable (mode enregistrement-seul) ;
3. forçable vers Voxtral via `mistral_source_transcription="voxtral"` (§8).

Dans tous les cas, la rédaction du CR (`cr.py`) est identique (source-agnostique).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from debrief_meet.core.fichiers import (
    chemin_locuteurs,
    chemins_audio_reunion,
    titre_reunion,
    transcription_en_attente,
)
from debrief_meet.core.mistral.client import ClientMistral, ErreurMistral
from debrief_meet.core.mistral.cr import generer_cr
from debrief_meet.core.mistral.fusion import fusionner
from debrief_meet.core.mistral.transcription import analyser_piste, transcrire_fichier
from debrief_meet.core.prompts import CR_SIMPLE_CONTENU, contenu_actif

if TYPE_CHECKING:
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)


def disponible(config: "Config") -> bool:
    """Vrai si une clé API Mistral est configurée (bouton visible, §9.2)."""
    return bool(config.get("mistral_cle_api"))


def _localiser_piste(base: Path) -> Path | None:
    """Piste retenue (.opus prioritaire, sinon .wav) à côté du `.md` ; None si absente."""
    for ext in (".opus", ".wav"):
        candidat = base.with_suffix(ext)
        if candidat.exists():
            return candidat
    return None


def _lire_transcript_local(chemin_md: Path) -> str | None:
    """Contenu du débrief locuteurs s'il existe, sinon du `.md` — None si aucun texte
    exploitable (placeholder « audio seul » ou fichier vide)."""
    if transcription_en_attente(chemin_md):
        return None
    cible = chemin_locuteurs(chemin_md)
    if not cible.exists():
        cible = chemin_md
    try:
        texte = cible.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return texte or None


def _context_bias(chemin_md: Path) -> list[str]:
    """Noms d'invités BlueMind (sidecar `<stem>.bluemind.json`, §7.5) — [] si absent."""
    try:
        from debrief_meet.core.bluemind import association
    except ImportError:
        return []
    asso = association.lire(chemin_md)
    if asso is None:
        return []
    return [i.nom for i in asso.invites if i.nom]


def _transcrire_si_utile(client: ClientMistral, piste: Path | None, analyse,
                         modele: str, langue: str | None, context_bias: list[str]):
    if piste is None or analyse is None or analyse.silencieuse:
        return None
    return transcrire_fichier(client, piste, modele, langue, context_bias)


def _transcrire_via_voxtral(chemin_md: Path, client: ClientMistral, config: "Config") -> str:
    """Branche repli (§4 étapes 5-6) : transcrit les pistes retenues puis les fusionne."""
    base_moi, base_systeme = chemins_audio_reunion(chemin_md)
    piste_moi = _localiser_piste(base_moi)
    piste_systeme = _localiser_piste(base_systeme)
    if piste_moi is None and piste_systeme is None:
        raise FileNotFoundError(
            f"Aucune piste audio retenue à côté de {chemin_md.name} "
            "(rétention désactivée ou audio supprimé) — rien à transcrire.")

    analyse_moi = analyser_piste(piste_moi) if piste_moi else None
    analyse_systeme = analyser_piste(piste_systeme) if piste_systeme else None

    duree_max = config.get("mistral_duree_max_min")
    duree_totale_min = sum(
        a.duree_s / 60 for a in (analyse_moi, analyse_systeme) if a is not None and not a.silencieuse
    )
    if duree_max is not None and duree_totale_min > duree_max:
        raise ErreurMistral(
            f"Réunion trop longue pour la transcription cloud "
            f"({duree_totale_min:.0f} min > limite {duree_max} min configurée dans les préférences).")

    langue = config.get("langue")
    modele = config.get("mistral_modele_transcription")
    context_bias = _context_bias(chemin_md)

    res_moi = _transcrire_si_utile(client, piste_moi, analyse_moi, modele, langue, context_bias)
    res_systeme = _transcrire_si_utile(client, piste_systeme, analyse_systeme, modele, langue, context_bias)
    if res_moi is None and res_systeme is None:
        raise ErreurMistral("Transcription Mistral : aucune piste exploitable (silence ou échec).")
    return fusionner(res_moi, res_systeme)


def generer_cr_reunion(chemin_md: Path, config: "Config") -> Path:
    """Point d'entrée unique du pipeline — produit `<stem>_CR.md` et retourne son chemin.

    Lève `ErreurMistral` (ou une sous-classe de `core.mistral.client`) sur tout échec
    — jamais de fichier partiel écrit."""
    chemin_md = Path(chemin_md)
    cle_api = config.get("mistral_cle_api")
    if not cle_api:
        raise ErreurMistral("Aucune clé API Mistral configurée (Préférences › Remote IA).")

    prompt = contenu_actif(config.get("prompts"), config.get("prompt_actif")) or CR_SIMPLE_CONTENU
    forcer_voxtral = config.get("mistral_source_transcription") == "voxtral"
    transcript = None if forcer_voxtral else _lire_transcript_local(chemin_md)
    source = "local"

    with ClientMistral(config.get("mistral_base_url"), cle_api) as client:
        if transcript is None:
            transcript = _transcrire_via_voxtral(chemin_md, client, config)
            source = "voxtral"
        cr_markdown, _usage_cr = generer_cr(
            client, transcript, prompt, config.get("mistral_modele_cr"),
            sujet=titre_reunion(chemin_md))

    chemin_cr = chemin_md.with_name(chemin_md.stem + "_CR.md")
    chemin_cr.write_text(cr_markdown.strip() + "\n", encoding="utf-8")
    logger.info("CR Mistral généré (source=%s) : %s", source, chemin_cr)
    return chemin_cr
