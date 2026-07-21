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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from debrief_meet.core.fichiers import (
    chemin_cr_mistral,
    chemin_locuteurs,
    chemins_audio_reunion,
    date_heure_reunion,
    definir_duree,
    duree_reunion,
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


# Mention ajoutée au .md quand la transcription vient de Voxtral (et non du moteur local).
_NOTE_VOXTRAL = "> Transcription générée par Voxtral (Mistral) depuis l'audio retenu."


@dataclass
class _ResultatVoxtral:
    transcript: str
    avec_moi: bool
    avec_systeme: bool


@dataclass
class _InfosEvenement:
    """Éléments d'association BlueMind exploités pour la transcription et le CR (§7.5)."""
    titre: str | None = None
    noms_invites: list[str] = None  # tous les invités (context_bias transcription)
    participants: list[str] = None  # invités cochés (injectés dans le prompt CR)

    def __post_init__(self) -> None:
        self.noms_invites = self.noms_invites or []
        self.participants = self.participants or []


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


def _infos_evenement(chemin_md: Path) -> _InfosEvenement:
    """Éléments d'association BlueMind (sidecar `<stem>.bluemind.json`, docs/40) —
    titre de l'événement + invités. Vide si aucune association ou module absent."""
    try:
        from debrief_meet.core.bluemind import association
    except ImportError:
        return _InfosEvenement()
    asso = association.lire(chemin_md)
    if asso is None:
        return _InfosEvenement()
    return _InfosEvenement(
        titre=asso.titre or None,
        noms_invites=[i.nom for i in asso.invites if i.nom],
        participants=[i.nom for i in asso.invites if i.coche and i.nom],
    )


def _transcrire_si_utile(client: ClientMistral, piste: Path | None, analyse,
                         modele: str, langue: str | None, context_bias: list[str]):
    if piste is None or analyse is None or analyse.silencieuse:
        return None
    return transcrire_fichier(client, piste, modele, langue, context_bias)


def _transcrire_via_voxtral(chemin_md: Path, client: ClientMistral, config: "Config",
                            context_bias: list[str]) -> _ResultatVoxtral:
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

    res_moi = _transcrire_si_utile(client, piste_moi, analyse_moi, modele, langue, context_bias)
    res_systeme = _transcrire_si_utile(client, piste_systeme, analyse_systeme, modele, langue, context_bias)
    if res_moi is None and res_systeme is None:
        raise ErreurMistral("Transcription Mistral : aucune piste exploitable (silence ou échec).")
    return _ResultatVoxtral(
        transcript=fusionner(res_moi, res_systeme),
        avec_moi=res_moi is not None and bool(res_moi.texte.strip()),
        avec_systeme=res_systeme is not None and bool(res_systeme.texte.strip()),
    )


def _ecrire_transcript_local(chemin_md: Path, res: _ResultatVoxtral) -> None:
    """Réécrit le `.md` local avec la transcription Voxtral (remplace le placeholder
    « audio seul »), en mentionnant que la transcription vient de Voxtral. Préserve le
    titre et la durée. Miroir de `core.transcription_differee._ecrire_md`."""
    dh = date_heure_reunion(chemin_md)
    titre = titre_reunion(chemin_md) or (
        f"Réunion — {dh.strftime('%Y-%m-%d %H:%M')}" if dh else chemin_md.stem)
    duree = duree_reunion(chemin_md)              # lu AVANT réécriture (le commentaire est perdu)
    lignes = [f"# {titre}", "", _NOTE_VOXTRAL]
    if not res.avec_systeme:
        lignes.append("> ⚠️ Audio système non disponible — transcription micro uniquement.")
    if not res.avec_moi:
        lignes.append("> ⚠️ Microphone non disponible — transcription audio système uniquement.")
    lignes += ["", "---", "", res.transcript]
    chemin_md.write_text("\n".join(lignes).rstrip() + "\n", encoding="utf-8")
    if duree is not None:
        definir_duree(chemin_md, duree)


def generer_cr_reunion(chemin_md: Path, config: "Config") -> Path:
    """Point d'entrée unique du pipeline — produit `<stem>_CR.md` et retourne son chemin.

    Lève `ErreurMistral` (ou une sous-classe de `core.mistral.client`) sur tout échec
    — jamais de fichier partiel écrit."""
    chemin_md = Path(chemin_md)
    cle_api = config.get("mistral_cle_api")
    if not cle_api:
        raise ErreurMistral("Aucune clé API Mistral configurée (Préférences › Remote IA).")

    prompt = contenu_actif(config.get("prompts"), config.get("prompt_actif")) or CR_SIMPLE_CONTENU
    infos = _infos_evenement(chemin_md)                       # éléments d'association (§7.5)
    sujet = infos.titre or titre_reunion(chemin_md)
    forcer_voxtral = config.get("mistral_source_transcription") == "voxtral"
    # « transcription pas encore réalisée » = placeholder audio-seul : dans ce cas la
    # transcription Voxtral est réécrite dans le .md local (avec mention Voxtral).
    en_attente = transcription_en_attente(chemin_md)
    transcript = None if forcer_voxtral else _lire_transcript_local(chemin_md)
    source = "local"

    with ClientMistral(config.get("mistral_base_url"), cle_api) as client:
        if transcript is None:
            res = _transcrire_via_voxtral(chemin_md, client, config, infos.noms_invites)
            transcript = res.transcript
            source = "voxtral"
            if en_attente:
                _ecrire_transcript_local(chemin_md, res)      # récupère la transcription en local
        cr_markdown, _usage_cr = generer_cr(
            client, transcript, prompt, config.get("mistral_modele_cr"),
            sujet=sujet, participants=infos.participants)

    chemin_cr = chemin_cr_mistral(chemin_md)
    chemin_cr.write_text(cr_markdown.strip() + "\n", encoding="utf-8")
    logger.info("CR Mistral généré (source=%s, %d invité(s)) : %s",
                source, len(infos.participants), chemin_cr)
    return chemin_cr
