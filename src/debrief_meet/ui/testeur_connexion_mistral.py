"""Worker Qt pour le bouton « Tester la connexion » — section Remote IA (docs/42 §9.1).

Seul appel réseau autorisé à afficher une erreur directement (l'utilisateur vient de
cliquer un bouton dédié) — tourne quand même dans un QThread : même un test de
connexion ne doit jamais geler l'UI."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from debrief_meet.core.mistral.client import ClientMistral, ErreurMistral


class TesteurConnexionMistral(QObject):
    reussi = Signal(str)   # message de confirmation
    echec = Signal(str)    # message d'erreur

    def __init__(self, url: str, cle_api: str) -> None:
        super().__init__()
        self._url = url
        self._cle_api = cle_api

    @Slot()
    def executer(self) -> None:
        try:
            with ClientMistral(self._url, self._cle_api) as client:
                client.get("v1/models")
            self.reussi.emit("Connexion réussie.")
        except ErreurMistral as exc:
            self.echec.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self.echec.emit(str(exc))
