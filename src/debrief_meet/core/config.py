from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

import platformdirs

from debrief_meet import APP_NAME
from debrief_meet.core import lexique as _lexique
from debrief_meet.core import prompts as _prompts

logger = logging.getLogger(__name__)

VERSION_COURANTE = 6

# `sys.platform` est un test stdlib, autorisé dans `core/` (la règle d'or interdit les
# *modules* OS-spécifiques, pas la détection d'OS) — docs/31 §3.1.
_WINDOWS = sys.platform == "win32"
# Linux : même situation que Windows — l'utilisateur cible est un collègue en
# production sur une machine à laquelle le développeur n'a pas accès, les logs sont
# le seul canal de debug (docs/49 L5). macOS reste off par défaut (dev local).
_LOGS_PAR_DEFAUT = _WINDOWS or sys.platform.startswith("linux")

#: Modèles de rédaction du CR proposés à l'utilisateur, du plus capable au plus léger.
#: **Mesuré le 2026-09-08** sur `/v1/chat/completions` avec notre clé : toute la famille
#: `mistral-*` / `magistral-*` répond **429 avec `x-ratelimit-limit-req-minute: 0`** —
#: l'allocation n'est pas épuisée, elle est NULLE, donc attendre ne peut jamais aboutir
#: (`mistral-large` répond 403 `tier_not_allowed` depuis fin août 2026, `magistral-medium`
#: est un simple alias de `mistral-medium`). Seuls les `ministral-*` sont servis :
#: 30 req/min et 937 k tokens/min pour le 14b, 188/625 k pour le 8b, 750/1,3 M pour le 3b.
#: Contexte identique à `mistral-medium` (256 k tokens) — la longueur des réunions n'est
#: donc pas en cause dans ce choix. Ne proposer que du servi : un modèle mort dans le
#: sélecteur envoie l'utilisateur droit sur 2 min d'attente puis « Quota dépassé »
#: (terrain du 2026-09-08, docs/42 §10.7).
MODELES_CR = ("ministral-14b-latest", "ministral-8b-latest", "ministral-3b-latest")
#: Le plus capable des modèles réellement servis.
MODELE_CR_DEFAUT = MODELES_CR[0]

_DEFAUTS: dict[str, Any] = {
    "version": VERSION_COURANTE,
    # Mode de transcription (docs/45) : "distant" (Opus + Mistral/Voxtral, défaut) ou
    # "local" (Whisper embarqué + Dictée/Journal + diarization). Lu une fois au
    # démarrage par core/mode_transcription.initialiser() — changer de mode propose
    # un redémarrage.
    "mode_transcription": "distant",
    # L'écran de bienvenue (choix du mode au premier lancement) a-t-il été montré ?
    # Absent des config.json antérieurs à docs/45 → les installations existantes le
    # voient une fois après la mise à jour : personne ne perd la transcription locale
    # sans un choix explicite.
    "accueil_fait": False,
    "modele": "large-v3-turbo",
    "langue": None,
    "micro_index": None,
    "dossier_reunions": str(Path.home() / "Documents" / "debriefMeet" / "reunions"),
    "dossier_journal": str(Path.home() / "Documents" / "debriefMeet" / "journal"),
    "intervalle_reunion": 30,
    "transcription_live": True,
    "aec_actif": True,
    "retention_audio": True,
    "prompts": _prompts.prompts_par_defaut(),
    "prompt_actif": _prompts.PROMPT_ACTIF_DEFAUT,
    # Lexique de corrections (docs/46) — correspondances « entendu → à écrire »
    # injectées à la fin des prompts (CR Mistral + copie avec prompt) et dans le
    # `context_bias` Voxtral. Global : indépendant du prompt choisi.
    "lexique_corrections": _lexique.corrections_par_defaut(),
    "lexique_actif": True,
    "demarrage_auto": False,
    # Windows (docs/30 D5) et Linux (docs/49 L5) : logs DEBUG activés par défaut —
    # seul canal de debug tant qu'aucune machine de dev de cet OS n'est disponible.
    # macOS inchangé (logs off par défaut).
    "logs_actifs": _LOGS_PAR_DEFAUT,
    "logs_debug": _LOGS_PAR_DEFAUT,
    "notifications": True,
    # Défauts Windows Ctrl+Alt+D/R/J (décision D3) — Meta = touche Windows, réservée par
    # l'OS pour beaucoup de combos, on ne la met pas dans les défauts Windows.
    "raccourci_dictee": "Ctrl+Alt+D" if _WINDOWS else "Meta+Alt+Ctrl+D",
    "raccourci_reunion": "Ctrl+Alt+R" if _WINDOWS else "Meta+Alt+Ctrl+R",
    "raccourci_journal": "Ctrl+Alt+J" if _WINDOWS else "Meta+Alt+Ctrl+J",
    # Sélection du backend de transcription Windows (docs/34 §1.4) — "auto" en v1
    # retombe toujours sur faster-whisper CPU ; valeurs futures : "openvino"/"directml"/
    # "vulkan" une fois le rapport spike docs/18 disponible.
    "backend": "auto",
    # Interco BlueMind (docs/40) — "bluemind_url" vide = interco désactivée (invisible).
    "bluemind_url": "",
    "bluemind_token": "",
    "bluemind_email": "",
    "bluemind_verifier_tls": True,
    "bluemind_sync_minutes": 15,
    "bluemind_fenetre_passe_jours": 90,
    "bluemind_fenetre_futur_jours": 30,
    "bluemind_notif_reunions": True,
    "bluemind_notif_avance_min": 5,
    "bluemind_notif_inclure_solo": False,
    "bluemind_notif_inclure_refuses": False,
    "bluemind_notif_inclure_journee": False,
    # Interco Mistral (docs/42) — "mistral_cle_api" vide = fonctionnalité invisible
    # (aucun bouton, aucune requête). Section Préférences « Remote IA ».
    "mistral_cle_api": "",
    "mistral_base_url": "https://api.mistral.ai",
    # "auto" : réutilise le transcript local s'il existe, repli Voxtral sinon (défaut,
    # décision adaptative §1) ; "voxtral" : force la re-transcription cloud.
    "mistral_source_transcription": "auto",
    "mistral_modele_transcription": "voxtral-mini-latest",
    "mistral_modele_cr": MODELE_CR_DEFAUT,
    "mistral_duree_max_min": 180,
    "mistral_confidentialite_acceptee": False,
    # Mise à jour automatique (docs/53) — vérification du manifeste signé de la
    # Release GitHub 30 s après le lancement puis toutes les 24 h. Clés nouvelles :
    # pas de migration (une config antérieure reçoit les défauts).
    "maj_verifier_auto": True,
    "maj_derniere_verification": "",   # ISO 8601 UTC, "" = jamais
    "maj_version_disponible": "",      # "" = à jour ; sinon le badge est posé dès le lancement, même hors ligne
    "maj_notes_url": "",
}


def _chemin_config() -> Path:
    # appauthor=False : sans lui, platformdirs double le dossier sur Windows
    # (`%LOCALAPPDATA%\debriefMeet\debriefMeet`) — il traite `appname` comme
    # « author » par défaut. Sans effet sur macOS/Linux (docs/32 §4).
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.json"


class Config:
    def __init__(self, chemin: Path | None = None) -> None:
        self._chemin = chemin or _chemin_config()
        # deepcopy : certains défauts sont mutables (ex. `prompts`) → éviter le partage
        # d'état entre instances de Config.
        self._donnees: dict[str, Any] = copy.deepcopy(_DEFAUTS)

    def charger(self) -> None:
        if not self._chemin.exists():
            return
        try:
            with self._chemin.open(encoding="utf-8") as f:
                sur_disque = json.load(f)
            migre = self._migrer(sur_disque)
            for cle, valeur in sur_disque.items():
                if cle in _DEFAUTS:
                    self._donnees[cle] = valeur
            if migre:
                self.sauvegarder()
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Config illisible (%s) — valeurs par défaut utilisées", exc)

    def sauvegarder(self) -> None:
        self._chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._chemin.open("w", encoding="utf-8") as f:
            json.dump(self._donnees, f, ensure_ascii=False, indent=2)

    def get(self, cle: str) -> Any:
        return self._donnees.get(cle, _DEFAUTS.get(cle))

    def donnees(self) -> dict[str, Any]:
        """Copie intégrale de la config — utilisé par l'export diagnostic (docs/31 §3.6)."""
        return copy.deepcopy(self._donnees)

    def set(self, cle: str, valeur: Any) -> None:
        if cle not in _DEFAUTS:
            raise KeyError(f"Clé de configuration inconnue : {cle!r}")
        self._donnees[cle] = valeur

    def _migrer(self, donnees: dict[str, Any]) -> bool:
        """Migre `donnees` (le contenu du fichier) en place. Renvoie True si une
        migration a eu lieu — la config est alors resauvegardée après la fusion."""
        version = donnees.get("version", 0)
        if version >= VERSION_COURANTE:
            return False
        logger.info("Migration config v%d → v%d", version, VERSION_COURANTE)
        if version < 2:
            self._migrer_v2_prompts(donnees)
        if version < 3:
            self._migrer_v3_modele_cr(donnees)
        if version < 4:
            self._migrer_v4_retrait_prompt_pipedrive(donnees)
        if version < 5:
            self._migrer_v5_modele_cr_medium(donnees)
        if version < 6:
            self._migrer_v6_modele_cr_ministral(donnees)
        donnees["version"] = VERSION_COURANTE
        return True

    @staticmethod
    def _migrer_v2_prompts(donnees: dict[str, Any]) -> None:
        """v2 : rafraîchit les prompts par défaut sans toucher aux prompts édités.

        - « CR simple » : contenu mis à jour uniquement s'il est resté identique à
          l'ancien défaut (CR_SIMPLE_CONTENU_V1) — un prompt retouché est laissé tel quel.
        - « CR Pipedrive » et « CR full .md » : ajoutés en fin de liste s'ils n'existent
          pas déjà (comparaison par titre). `prompt_actif` reste valide : on n'insère
          qu'en fin.

        NB : depuis v4, « CR Pipedrive » est ajouté ici puis retiré juste après, dans
        la même passe, pour une config encore en v0/v1. C'est volontairement laissé
        tel quel — une migration passée est un enregistrement de ce qui a été fait
        sur les postes déjà migrés ; la réécrire fausserait ce qu'elle a signifié.
        """
        prompts = donnees.get("prompts")
        if not isinstance(prompts, list):
            return
        for p in prompts:
            if (isinstance(p, dict) and p.get("titre") == _prompts.CR_SIMPLE_TITRE
                    and p.get("contenu") == _prompts.CR_SIMPLE_CONTENU_V1):
                p["contenu"] = _prompts.CR_SIMPLE_CONTENU
        titres = {p.get("titre") for p in prompts if isinstance(p, dict)}
        for titre, contenu in ((_prompts.CR_PIPEDRIVE_TITRE, _prompts.CR_PIPEDRIVE_CONTENU_V2),
                               (_prompts.CR_FULL_MD_TITRE, _prompts.CR_FULL_MD_CONTENU)):
            if titre not in titres:
                prompts.append({"titre": titre, "contenu": contenu})

    @staticmethod
    def _migrer_v4_retrait_prompt_pipedrive(donnees: dict[str, Any]) -> None:
        """v4 : retire le prompt « CR Pipedrive », rendu inutile par la copie mise en
        forme (docs/51) — le « CR full .md » est converti en HTML au moment du copier.

        Deux précautions :

        - **Seul un prompt resté au défaut est retiré** (contenu identique à
          `CR_PIPEDRIVE_CONTENU_V2`). Un prompt que l'utilisateur a retouché lui
          appartient : on le laisse, comme le fait déjà la migration v2 pour le CR
          simple.
        - **`prompt_actif` est un index, pas un nom** : retirer un élément décale
          tout ce qui suit. C'est précisément pour éviter ça que la v2 n'ajoutait
          qu'en fin de liste. On recale donc l'index — ramené sur le CR simple s'il
          désignait le prompt retiré.
        """
        prompts = donnees.get("prompts")
        if not isinstance(prompts, list):
            return
        cible = next(
            (i for i, p in enumerate(prompts)
             if isinstance(p, dict) and p.get("titre") == _prompts.CR_PIPEDRIVE_TITRE
             and p.get("contenu") == _prompts.CR_PIPEDRIVE_CONTENU_V2),
            None)
        if cible is None:
            return
        del prompts[cible]
        actif = donnees.get("prompt_actif")
        if isinstance(actif, int):
            if actif == cible:
                donnees["prompt_actif"] = _prompts.PROMPT_ACTIF_DEFAUT
            elif actif > cible:
                donnees["prompt_actif"] = actif - 1

    @staticmethod
    def _migrer_v3_modele_cr(donnees: dict[str, Any]) -> None:
        """v3 : le modèle de CR par défaut passe à mistral-large-latest (cf. le
        commentaire de `_DEFAUTS`). Seule l'ancienne valeur par défaut est migrée —
        un autre choix explicite est conservé."""
        if donnees.get("mistral_modele_cr") == "mistral-small-latest":
            donnees["mistral_modele_cr"] = "mistral-large-latest"

    @staticmethod
    def _migrer_v5_modele_cr_medium(donnees: dict[str, Any]) -> None:
        """v5 : mistral-large → mistral-medium. Contrairement aux migrations v2/v4,
        on migre AUSSI un choix explicite : mistral-large répond 403
        `tier_not_allowed` sur notre tier depuis fin août 2026 (constaté le
        2026-08-31), et le modèle est retiré du sélecteur — conserver la valeur
        figerait un échec que l'UI ne permet plus de corriger vers autre chose."""
        if donnees.get("mistral_modele_cr") in ("mistral-large-latest", "mistral-large-2512"):
            donnees["mistral_modele_cr"] = "mistral-medium-latest"

    @staticmethod
    def _migrer_v6_modele_cr_ministral(donnees: dict[str, Any]) -> None:
        """v6 : tout modèle qui n'est plus servi → `MODELE_CR_DEFAUT` (ministral-14b).

        Deuxième vague du resserrement de tier après la v5, et bien plus large :
        `mistral-medium` ET `mistral-small` — les deux SEULS choix qu'offrait alors le
        sélecteur — répondent 429 avec une limite de **0 requête/minute** (mesuré le
        2026-09-08 ; cf. `MODELES_CR`). Contrairement à la v5, la valeur fautive ne
        peut donc pas être énumérée : on migre **tout ce qui n'est pas dans
        `MODELES_CR`**, y compris un choix explicite. Laisser une valeur morte
        figerait un échec que le sélecteur ne permet plus de corriger, et le message
        rendu à l'utilisateur (« Quota dépassé ») l'enverrait attendre un déblocage
        qui ne viendra pas.

        Corollaire assumé : un abonnement supérieur, où `mistral-medium` redeviendrait
        servi, est migré lui aussi. Le remède est alors d'ajouter le modèle à
        `MODELES_CR` — pas de laisser chaque poste porter une valeur que rien ne
        vérifie."""
        if donnees.get("mistral_modele_cr") not in MODELES_CR:
            donnees["mistral_modele_cr"] = MODELE_CR_DEFAUT
