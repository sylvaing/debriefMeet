"""Worker Qt pour le bouton « Tester la connexion » des Préférences (docs/40 §4).

Seul appel réseau autorisé à afficher une erreur directement (§1.1) — tourne quand
même dans un QThread : même un test de connexion ne doit jamais geler l'UI."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from debrief_meet.core.bluemind.client import ClientBlueMind, ErreurBlueMind
from debrief_meet.core.bluemind.identite import resoudre_identite


class TesteurConnexionBlueMind(QObject):
    reussi = Signal(str, str)   # nom_affiche, email
    echec = Signal(str)         # message d'erreur

    def __init__(self, url: str, token: str, email: str, verifier_tls: bool) -> None:
        super().__init__()
        self._url = url
        self._token = token
        self._email = email
        self._verifier_tls = verifier_tls

    @Slot()
    def executer(self) -> None:
        try:
            with ClientBlueMind(self._url, self._token, self._verifier_tls) as client:
                identite = resoudre_identite(client, self._email)
            self.reussi.emit(identite.nom_affiche, identite.email)
        except ErreurBlueMind as exc:
            self.echec.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self.echec.emit(str(exc))
