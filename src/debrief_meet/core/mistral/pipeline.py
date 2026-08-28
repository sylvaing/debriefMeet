"""Orchestration bout-en-bout (§4) : `.md` de réunion → `CR.md` (docs/43).

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
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from debrief_meet.core.fichiers import (
    chemin_cr_mistral,
    chemin_locuteurs,
    chemins_audio_reunion,
    date_heure_reunion,
    definir_duree,
    duree_reunion,
    resoudre_chemin_reunion,
    titre_reunion,
    transcription_en_attente,
)
from debrief_meet.core import lexique
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
    debut_iso: str | None = None    # début de l'événement (iso) — date injectée dans le CR

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
    """Éléments d'association BlueMind (sidecar `bluemind.json`, docs/40/43) —
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
        debut_iso=asso.debut or None,
    )


def _date_lisible(infos: _InfosEvenement, chemin_md: Path) -> str | None:
    """Date FR (« JJ/MM/AAAA HH:MM ») injectée dans le CR. Préfère la date de l'événement
    BlueMind associé (== cartouche invités) ; repli sur la date d'enregistrement (nom du
    dossier), toujours disponible même sans association."""
    if infos.debut_iso:
        try:
            return datetime.fromisoformat(infos.debut_iso).strftime("%d/%m/%Y %H:%M")
        except (ValueError, TypeError):
            pass
    dh = date_heure_reunion(chemin_md)
    return dh.strftime("%d/%m/%Y %H:%M") if dh else None


def _reinserer_bloc_invites(chemin_md: Path) -> None:
    """Après réécriture Voxtral du `.md`, ré-insère le cartouche invités BlueMind que la
    réécriture a effacé (si la réunion est associée). Le contexte CR vient du sidecar, pas
    du texte ; ce bloc est là pour la **cohérence** avec les réunions associées et la
    **portabilité** du `.md` (contexte lisible même hors sidecar). No-op si non associée.

    Logique partagée avec la transcription locale et la diarization (2026-08-24) : le
    correctif ne vivait que sur ce chemin, laissant les `.md` transcrits en local sans
    cartouche."""
    try:
        from debrief_meet.core.bluemind.participants import reinserer_depuis_sidecar
    except ImportError:
        return
    reinserer_depuis_sidecar(chemin_md)


def _transcrire_si_utile(client: ClientMistral, piste: Path | None, analyse,
                         modele: str, langue: str | None, context_bias: list[str],
                         precedente_entiere: bool | None = None):
    if piste is None or analyse is None or analyse.silencieuse:
        return None
    return transcrire_fichier(client, piste, modele, langue, context_bias,
                              precedente_entiere=precedente_entiere, plan=analyse.plan)


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

    # Durée de la RÉUNION = la plus longue des pistes, jamais leur somme : les deux
    # sont enregistrées simultanément, donc les additionner double le compte et divise
    # par deux la limite réelle. Vécu le 2026-08-18 : une réunion de 98 min refusée
    # comme « 197 min », et le chiffre affiché ne correspondait à rien que
    # l'utilisatrice pouvait reconnaître.
    duree_max = config.get("mistral_duree_max_min")
    duree_reunion_min = max(
        (a.duree_s / 60 for a in (analyse_moi, analyse_systeme) if a is not None), default=0.0)
    if duree_max is not None and duree_reunion_min > duree_max:
        raise ErreurMistral(
            f"Réunion trop longue pour la transcription cloud "
            f"({duree_reunion_min:.0f} min > limite {duree_max} min réglée dans "
            "Préférences › IA en ligne).")

    langue = config.get("langue")
    modele = config.get("mistral_modele_transcription")

    res_moi = _transcrire_si_utile(client, piste_moi, analyse_moi, modele, langue, context_bias)
    # Le sort de la 1re piste renseigne la 2e sur le sens d'un éventuel 429 : passée
    # entière → fenêtre pleine (attendre puis retenter entier) ; découpée → inutile
    # de tenter l'envoi entier ; absente/silencieuse → aucune information.
    res_systeme = _transcrire_si_utile(
        client, piste_systeme, analyse_systeme, modele, langue, context_bias,
        precedente_entiere=None if res_moi is None else not res_moi.decoupee)
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
        f"Réunion — {dh.strftime('%Y-%m-%d %H:%M')}" if dh else chemin_md.parent.name)
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


def generer_cr_reunion(chemin_md: Path, config: "Config", prompt: str | None = None) -> Path:
    """Point d'entrée unique du pipeline — produit `CR.md` et retourne son chemin.

    `prompt` : contenu de prompt ponctuel pour ce CR (choisi dans l'UI) ; None ou
    vide → prompt actif de la config, repli sur le CR simple.

    Lève `ErreurMistral` (ou une sous-classe de `core.mistral.client`) sur tout échec
    — jamais de fichier partiel écrit."""
    # Le dossier a pu être renommé entre le clic et le démarrage effectif du worker
    # (association BlueMind, édition du titre) — et il pourra l'être encore pendant les
    # minutes qui suivent : chaque écriture re-résout le chemin (docs/43 §6).
    chemin_md = resoudre_chemin_reunion(chemin_md)
    cle_api = config.get("mistral_cle_api")
    if not cle_api:
        raise ErreurMistral("Aucune clé API Mistral configurée (Préférences › Remote IA).")

    if prompt is None or not prompt.strip():
        prompt = contenu_actif(config.get("prompts"), config.get("prompt_actif")) or CR_SIMPLE_CONTENU
    # Bloc de corrections ajouté ici, APRÈS la résolution (ponctuel > actif > CR simple) :
    # un seul site couvre tous les chemins d'entrée (docs/46 §5.1).
    prompt = lexique.completer_prompt(prompt, config)
    infos = _infos_evenement(chemin_md)                       # éléments d'association (§7.5)
    sujet = infos.titre or titre_reunion(chemin_md)
    forcer_voxtral = config.get("mistral_source_transcription") == "voxtral"
    # « transcription pas encore réalisée » = placeholder audio-seul : dans ce cas la
    # transcription Voxtral est réécrite dans le .md local (avec mention Voxtral).
    en_attente = transcription_en_attente(chemin_md)
    transcript = None if forcer_voxtral else _lire_transcript_local(chemin_md)
    source = "local"

    # Biais Voxtral : invités BlueMind d'abord (prioritaires dans la coupe à 100 jetons
    # de `_construire_donnees`), puis les termes « à écrire » du lexique — même
    # interrupteur `lexique_actif` que l'injection prompt (docs/46 §5.3).
    context_bias = list(infos.noms_invites)
    if config.get("lexique_actif"):
        context_bias += lexique.termes_biais(config.get("lexique_corrections"))

    with ClientMistral(config.get("mistral_base_url"), cle_api) as client:
        if transcript is None:
            res = _transcrire_via_voxtral(chemin_md, client, config, context_bias)
            transcript = res.transcript
            source = "voxtral"
            if en_attente:
                # La transcription Voxtral a duré : le dossier a pu être renommé depuis
                # les lectures ci-dessus (cas réel du 2026-08-26 16:19, échec à 347 ms
                # de la fin de l'upload).
                chemin_md = resoudre_chemin_reunion(chemin_md)
                _ecrire_transcript_local(chemin_md, res)      # récupère la transcription en local
                _reinserer_bloc_invites(chemin_md)            # la réécriture a effacé le cartouche
        cr_markdown, _usage_cr = generer_cr(
            client, transcript, prompt, config.get("mistral_modele_cr"),
            sujet=sujet, participants=infos.participants, date=_date_lisible(infos, chemin_md))

    # Idem après la rédaction du CR, la plus longue étape (cas réel du 2026-08-26 16:26 :
    # lecture passée, écriture du CR.md dans un dossier déjà renommé).
    chemin_md = resoudre_chemin_reunion(chemin_md)
    chemin_cr = chemin_cr_mistral(chemin_md)
    chemin_cr.write_text(cr_markdown.strip() + "\n", encoding="utf-8")
    logger.info("CR Mistral généré (source=%s, %d invité(s)) : %s",
                source, len(infos.participants), chemin_cr)
    return chemin_cr
