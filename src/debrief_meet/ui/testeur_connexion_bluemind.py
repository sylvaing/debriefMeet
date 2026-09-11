"""Worker Qt pour le bouton « Tester la connexion » des Préférences (docs/40 §4).

Seul appel réseau autorisé à afficher une erreur directement (§1.1) — tourne quand
même dans un QThread : même un test de connexion ne doit jamais geler l'UI.

Les deux issues sont journalisées. C'est le seul geste par lequel l'utilisateur
*interroge* l'interco, donc le seul dont un diagnostic devrait pouvoir lire le verdict ;
or son résultat ne vivait que dans le label des Préférences, effacé à la fermeture de la
fenêtre. Cas réel du 2026-09-11 : un poste dont l'URL était saisie sans `/api` n'en
gardait aucune trace, et rien ne disait si le bouton avait seulement été cliqué.
L'URL est journalisée telle qu'elle a été saisie — c'est précisément le champ qui était
faux, et l'export de diagnostic la transmet déjà en clair (seul le token est caviardé,
et il ne voyage qu'en en-tête, jamais dans un message d'erreur du client)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from debrief_meet.core.bluemind.client import ClientBlueMind, ErreurBlueMind
from debrief_meet.core.bluemind.identite import resoudre_identite

logger = logging.getLogger(__name__)


class TesteurConnexionBlueMind(QObject):
    reussi = Signal(str, str)   # nom_affiche, email
    echec = Signal(str)         # message d'erreur

    def __init__(self, url: str, token: str, email: str, verifier_tls: bool) -> None:
        super().__init__()
        self._url = url
        self._token = token
        self._email = email
        self._verifier_tls = verifier_tls

    def _echouer(self, message: str) -> None:
        # WARNING : un test explicitement demandé par l'utilisateur et qui échoue est
        # toujours une anomalie à remonter, jamais du bruit de fond.
        logger.warning("Test de connexion BlueMind échoué (%s) : %s", self._url, message)
        self.echec.emit(message)

    @Slot()
    def executer(self) -> None:
        try:
            with ClientBlueMind(self._url, self._token, self._verifier_tls) as client:
                identite = resoudre_identite(client, self._email)
        except ErreurBlueMind as exc:
            self._echouer(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self._echouer(str(exc))
            return
        logger.info("Test de connexion BlueMind réussi (%s) : %s <%s>",
                    self._url, identite.nom_affiche, identite.email)
        self.reussi.emit(identite.nom_affiche, identite.email)
