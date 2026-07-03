"""Instance unique et IPC via QLocalServer / QLocalSocket (cross-platform)."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_NOM_SERVEUR = "debriefMeet"
_TIMEOUT_MS = 500


class ServeurIPC(QObject):
    commande_recue = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._serveur = QLocalServer(self)
        self._serveur.newConnection.connect(self._on_connexion)

    def demarrer(self) -> bool:
        QLocalServer.removeServer(_NOM_SERVEUR)
        ok = self._serveur.listen(_NOM_SERVEUR)
        if ok:
            logger.debug("ServeurIPC: écoute sur %s", _NOM_SERVEUR)
        else:
            logger.error("ServeurIPC: impossible d'écouter (%s)", self._serveur.errorString())
        return ok

    def arreter(self) -> None:
        self._serveur.close()
        QLocalServer.removeServer(_NOM_SERVEUR)

    def _on_connexion(self) -> None:
        socket = self._serveur.nextPendingConnection()
        if socket:
            socket.readyRead.connect(lambda: self._lire(socket))

    def _lire(self, socket: QLocalSocket) -> None:
        data = bytes(socket.readAll()).decode("utf-8").strip()
        socket.close()
        if data:
            logger.debug("IPC commande reçue : %r", data)
            self.commande_recue.emit(data)


def envoyer_commande(commande: str) -> bool:
    """Envoie une commande à l'instance déjà en cours. Retourne True si réussi."""
    socket = QLocalSocket()
    socket.connectToServer(_NOM_SERVEUR)
    if not socket.waitForConnected(_TIMEOUT_MS):
        return False
    socket.write(commande.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(_TIMEOUT_MS)
    socket.disconnectFromServer()
    return True


def instance_en_cours() -> bool:
    """Retourne True si une instance répond déjà sur le socket."""
    socket = QLocalSocket()
    socket.connectToServer(_NOM_SERVEUR)
    ok = socket.waitForConnected(_TIMEOUT_MS)
    socket.disconnectFromServer()
    return ok
