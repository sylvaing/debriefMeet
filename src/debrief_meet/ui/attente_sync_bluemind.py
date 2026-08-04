"""Attente **bornée** d'une synchro BlueMind, avec retour visuel.

Cas d'usage : une action de l'utilisateur a besoin d'une réplique de calendrier à jour
avant de décider (proposition d'association juste avant un CR Mistral, docs/42) — à la
différence des autres déclencheurs de sync (ouverture de fenêtre, timer, passage en mode
Réunion) qui sont tous « au fil de l'eau » et n'attendent rien.

Décalque le motif de `ui/chargeur_modele.py` (QProgressDialog indéterminé + QEventLoop
imbriquée), appliqué ici à un worker qu'on ne possède pas : on n'attend pas un QThread
mais les signaux `terminee`/`echouee` de `SynchroCalendrier`, avec une garde de temps
puisqu'une resync complète (fenêtre 90 j / 30 j) peut durer.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget

if TYPE_CHECKING:
    from debrief_meet.core.bluemind.sync import SynchroCalendrier

logger = logging.getLogger(__name__)

TIMEOUT_DEFAUT_MS = 15_000


def attendre_sync(
    synchro: "SynchroCalendrier | None", parent: QWidget | None = None,
    timeout_ms: int = TIMEOUT_DEFAUT_MS, message: str = "Recherche d'un événement de calendrier…",
) -> bool:
    """Déclenche une synchro BlueMind (ou rejoint celle qui tourne déjà) et attend sa fin.

    Retourne True si une synchro a effectivement été attendue — False si l'interco n'est
    pas configurée ou si rien n'a pu démarrer. **Ne lève jamais et n'affiche aucune
    erreur** : une sync en échec (réseau, serveur) sort simplement de l'attente, et
    l'appelant enchaîne sur la réplique telle qu'elle est (docs/40 §1.1 — l'interco reste
    invisible en cas de panne).
    """
    if synchro is None or not synchro.configuree():
        return False

    loop = QEventLoop()
    # Connexions posées AVANT le déclenchement : `terminee`/`echouee` sont réémis par
    # `SynchroCalendrier` depuis le thread GUI (slots à connexion auto → queued), donc
    # jamais avant `loop.exec()`, mais l'ordre reste la garantie la plus simple à relire.
    synchro.terminee.connect(loop.quit)
    synchro.echouee.connect(loop.quit)
    try:
        if not synchro.synchroniser_si_necessaire() and not synchro.en_cours():
            # Ni démarrée ni déjà en cours = configuration invalide (cf. sync.py) : rien
            # à attendre, l'appelant travaillera sur la réplique existante.
            return False

        dlg = QProgressDialog(message, None, 0, 0, parent)  # barre indéterminée, pas d'Annuler
        dlg.setWindowTitle("debriefMeet — calendrier")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)  # empêche un 2ᵉ déclenchement
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        # Garde de temps : on ne bloque jamais l'utilisateur indéfiniment sur une resync.
        QTimer.singleShot(timeout_ms, loop.quit)
        dlg.show()
        loop.exec()                                        # UI réactive pendant l'attente
        dlg.close()
        if synchro.en_cours():
            logger.info("Sync BlueMind toujours en cours après %d ms — on continue sans elle",
                        timeout_ms)
        return True
    finally:
        synchro.terminee.disconnect(loop.quit)
        synchro.echouee.disconnect(loop.quit)
