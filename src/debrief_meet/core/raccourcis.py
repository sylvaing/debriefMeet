"""Application des raccourcis clavier globaux depuis la config (docs/28)."""
from __future__ import annotations

import logging

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats
from debrief_meet.platform.interfaces import RaccourcisGlobaux

logger = logging.getLogger(__name__)

# (clé config, valeur par défaut, nom de l'action pour messages)
ACTIONS = (
    ("raccourci_dictee", "Meta+Alt+Ctrl+D", "Dictée"),
    ("raccourci_reunion", "Meta+Alt+Ctrl+R", "Réunion"),
    ("raccourci_journal", "Meta+Alt+Ctrl+J", "Journal"),
)


def appliquer_raccourcis(raccourcis: RaccourcisGlobaux, config: Config, machine: MachineEtats) -> list[str]:
    """(Ré)enregistre les 3 raccourcis depuis la config. Retourne la liste des
    combinaisons en échec (déjà prises / invalides) — vide si tout est passé.
    Une combinaison vide en config ("") = raccourci désactivé, pas une erreur."""
    raccourcis.desactiver_tous()

    callbacks = {
        "raccourci_dictee": machine.toggle_dictee,
        "raccourci_reunion": machine.toggle_reunion,
        "raccourci_journal": machine.toggle_journal,
    }

    echecs: list[str] = []
    for cle, _defaut, nom in ACTIONS:
        combinaison = config.get(cle)
        if not combinaison:
            continue
        if not raccourcis.enregistrer(combinaison, callbacks[cle]):
            logger.warning("Raccourci %s (%s) : échec d'enregistrement", nom, combinaison)
            echecs.append(combinaison)

    return echecs
