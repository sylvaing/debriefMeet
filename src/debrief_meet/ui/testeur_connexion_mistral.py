"""Worker Qt pour le bouton « Tester la connexion » — section Remote IA (docs/42 §9.1).

Seul appel réseau autorisé à afficher une erreur directement (l'utilisateur vient de
cliquer un bouton dédié) — tourne quand même dans un QThread : même un test de
connexion ne doit jamais geler l'UI.

Les deux issues sont journalisées, comme pour le jumeau BlueMind : le verdict ne vivait
que dans le label des Préférences, effacé à la fermeture de la fenêtre, donc invisible à
un diagnostic. Le nombre de modèles servis vient en prime du corps déjà reçu — c'est
exactement la mesure qui a démêlé docs/42 §10.7 (toute la famille `mistral-*` en 429 à
plafond nul, alors que la clé, elle, était bonne). La clé API n'est jamais journalisée :
elle ne voyage qu'en en-tête `Authorization`, et les messages d'erreur de `ClientMistral`
ne reprennent que des corps de réponse serveur."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from debrief_meet.core.mistral.client import ClientMistral, ErreurMistral

logger = logging.getLogger(__name__)


def _nombre_de_modeles(reponse) -> int | None:
    """Best-effort — le compte n'est qu'une indication de log, jamais une décision :
    une forme de réponse inattendue ne doit surtout pas changer un test réussi en échec."""
    try:
        donnees = reponse.json().get("data")
    except Exception:  # noqa: BLE001 — corps non-JSON ou inattendu
        return None
    return len(donnees) if isinstance(donnees, list) else None


class TesteurConnexionMistral(QObject):
    reussi = Signal(str)   # message de confirmation
    echec = Signal(str)    # message d'erreur

    def __init__(self, url: str, cle_api: str) -> None:
        super().__init__()
        self._url = url
        self._cle_api = cle_api

    def _echouer(self, message: str) -> None:
        # WARNING : un test explicitement demandé par l'utilisateur et qui échoue est
        # toujours une anomalie à remonter, jamais du bruit de fond.
        logger.warning("Test de connexion Mistral échoué (%s) : %s", self._url, message)
        self.echec.emit(message)

    @Slot()
    def executer(self) -> None:
        try:
            with ClientMistral(self._url, self._cle_api) as client:
                reponse = client.get("v1/models")
                modeles = _nombre_de_modeles(reponse)
        except ErreurMistral as exc:
            self._echouer(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self._echouer(str(exc))
            return
        logger.info("Test de connexion Mistral réussi (%s) — %s modèle(s) servi(s)",
                    self._url, modeles if modeles is not None else "?")
        self.reussi.emit("Connexion réussie.")
