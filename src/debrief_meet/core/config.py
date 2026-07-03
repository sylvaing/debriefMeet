from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import platformdirs

from debrief_meet import APP_NAME
from debrief_meet.core import prompts as _prompts

logger = logging.getLogger(__name__)

VERSION_COURANTE = 1

_DEFAUTS: dict[str, Any] = {
    "version": VERSION_COURANTE,
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
    "logs_actifs": False,
    "logs_debug": False,
    "notifications": True,
    "raccourci_dictee": "Meta+Alt+Ctrl+D",
    "raccourci_reunion": "Meta+Alt+Ctrl+R",
    "raccourci_journal": "Meta+Alt+Ctrl+J",
}


def _chemin_config() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME)) / "config.json"


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

    def set(self, cle: str, valeur: Any) -> None:
        if cle not in _DEFAUTS:
            raise KeyError(f"Clé de configuration inconnue : {cle!r}")
        self._donnees[cle] = valeur

    def _migrer(self, donnees: dict[str, Any]) -> None:
        version = donnees.get("version", 0)
        if version < VERSION_COURANTE:
            logger.info("Migration config v%d → v%d", version, VERSION_COURANTE)
            donnees["version"] = VERSION_COURANTE
