"""Application des raccourcis clavier globaux depuis la config (docs/28)."""
from __future__ import annotations

import logging
import sys

from debrief_meet.core import mode_transcription
from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats
from debrief_meet.platform.interfaces import RaccourcisGlobaux

logger = logging.getLogger(__name__)

# `sys.platform` est un test stdlib, autorisé dans `core/` (docs/31 §3.1) — cf.
# config.py. Mêmes défauts que `config._DEFAUTS` (décision D3 : pas de Meta/touche
# Windows dans les défauts Windows, réservée par l'OS pour beaucoup de combos).
_WINDOWS = sys.platform == "win32"

# (clé config, valeur par défaut, nom de l'action pour messages)
ACTIONS = (
    ("raccourci_dictee", "Ctrl+Alt+D" if _WINDOWS else "Meta+Alt+Ctrl+D", "Dictée"),
    ("raccourci_reunion", "Ctrl+Alt+R" if _WINDOWS else "Meta+Alt+Ctrl+R", "Réunion"),
    ("raccourci_journal", "Ctrl+Alt+J" if _WINDOWS else "Meta+Alt+Ctrl+J", "Journal"),
)

# Libellé natif d'un modificateur seul (portable → affiché), pour les messages qui
# énumèrent les modificateurs acceptés plutôt qu'une combinaison complète (cf.
# `libelle_modificateurs`). Ne jamais coder en dur les glyphes macOS ailleurs.
_GLYPHES_MAC = {"Ctrl": "⌃", "Alt": "⌥", "Meta": "⌘", "Shift": "⇧"}
_LIBELLES_AUTRES = {"Ctrl": "Ctrl", "Alt": "Alt", "Meta": "Win", "Shift": "Maj"}


def actions() -> tuple[tuple[str, str, str], ...]:
    """`ACTIONS` filtrées par le mode — Dictée/Journal absentes en distant (docs/45).

    Point d'étranglement **unique** : alimente à la fois l'enregistrement des raccourcis
    auprès de l'OS (ci-dessous) et les éditeurs de Préférences › Raccourcis. Ne rien
    enregistrer pour Dictée/Journal garantit aussi que l'OS ne délivrera jamais ces
    combinaisons — donc aucun basculement vers un mode sans orchestrateur à l'écoute.
    """
    if mode_transcription.avec_dictee_journal():
        return ACTIONS
    return tuple(a for a in ACTIONS if a[0] == "raccourci_reunion")


def libelle_modificateur(nom_portable: str) -> str:
    """Libellé natif d'un modificateur (« Ctrl »/« Alt »/« Meta »/« Shift »)."""
    table = _GLYPHES_MAC if sys.platform == "darwin" else _LIBELLES_AUTRES
    return table.get(nom_portable, nom_portable)


def libelle_modificateurs(noms_portables: tuple[str, ...]) -> str:
    """Énumération de modificateurs pour un message (« ⌘/⌃/⌥ » sur macOS,
    « Win/Ctrl/Alt » ailleurs)."""
    return "/".join(libelle_modificateur(n) for n in noms_portables)


def appliquer_raccourcis(raccourcis: RaccourcisGlobaux, config: Config, machine: MachineEtats) -> list[str]:
    """(Ré)enregistre les raccourcis de l'édition depuis la config. Retourne la liste
    des combinaisons en échec (déjà prises / invalides) — vide si tout est passé.
    Une combinaison vide en config ("") = raccourci désactivé, pas une erreur."""
    raccourcis.desactiver_tous()

    callbacks = {
        "raccourci_dictee": machine.toggle_dictee,
        "raccourci_reunion": machine.toggle_reunion,
        "raccourci_journal": machine.toggle_journal,
    }

    echecs: list[str] = []
    for cle, _defaut, nom in actions():
        combinaison = config.get(cle)
        if not combinaison:
            continue
        if not raccourcis.enregistrer(combinaison, callbacks[cle]):
            logger.warning("Raccourci %s (%s) : échec d'enregistrement", nom, combinaison)
            echecs.append(combinaison)

    return echecs
