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
