from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

import platformdirs

from debrief_meet import APP_NAME
from debrief_meet.core import prompts as _prompts

logger = logging.getLogger(__name__)

VERSION_COURANTE = 1

# `sys.platform` est un test stdlib, autorisé dans `core/` (la règle d'or interdit les
# *modules* OS-spécifiques, pas la détection d'OS) — docs/31 §3.1.
_WINDOWS = sys.platform == "win32"

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
    "demarrage_auto": False,
    # Windows : logs DEBUG activés par défaut (décision D5) — seul canal de debug tant
    # qu'aucune machine Windows de dev n'est disponible. macOS/Linux inchangés.
    "logs_actifs": _WINDOWS,
    "logs_debug": _WINDOWS,
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
    "mistral_modele_cr": "mistral-small-latest",
    "mistral_duree_max_min": 180,
    "mistral_confidentialite_acceptee": False,
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
            self._migrer(sur_disque)
            for cle, valeur in sur_disque.items():
                if cle in _DEFAUTS:
                    self._donnees[cle] = valeur
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

    def _migrer(self, donnees: dict[str, Any]) -> None:
        version = donnees.get("version", 0)
        if version < VERSION_COURANTE:
            logger.info("Migration config v%d → v%d", version, VERSION_COURANTE)
            donnees["version"] = VERSION_COURANTE
