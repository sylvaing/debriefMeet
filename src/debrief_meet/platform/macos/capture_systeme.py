from __future__ import annotations

import os
import subprocess
import threading

from debrief_meet.core.ressources import chemin_ressource
from debrief_meet.platform.interfaces import CaptureAudioSysteme

# Même chemin relatif en dev (racine du dépôt) et en bundle (sous _MEIPASS).
BINAIRE = chemin_ressource("helpers", "macos", "sck-audio", "SCKAudioCapture")


class CaptureAudioSCK(CaptureAudioSysteme):
    """Capture audio système via SCKAudioCapture (ScreenCaptureKit).

    Le processus helper est démarré à la demande (premier appel à demarrer())
    et arrêté à chaque fin de réunion (arreter()). Cela évite l'indicateur de
    capture d'écran permanent entre les réunions.
    """

    def __init__(self) -> None:
        self._buffer: list = []
        self._verrou = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._sr = 48_000
        self._ch = 2
        self._pret = threading.Event()

    @property
    def taux_echantillonnage(self) -> int:
        return self._sr

    def disponible(self) -> bool:
        """Retourne True si le binaire SCK existe — le processus sera lancé à demarrer()."""
        return BINAIRE.exists() and os.access(BINAIRE, os.X_OK)

    def demarrer(self) -> None:
        # Démarrage paresseux : premier appel lance le processus et attend SCK.
        if self._proc is None or self._proc.poll() is not None:
            self._pret.clear()
            self._demarrer_processus()
            # Attendre que SCK soit prêt (FORMAT reçu). Timeout 5 s = permission refusée.
            self._pret.wait(timeout=5.0)
        with self._verrou:
            self._buffer.clear()
        self._envoyer_commande("START")

    def arreter(self) -> None:
        """Arrête la réunion et tue le processus SCK (supprime l'indicateur de capture)."""
        self._envoyer_commande("QUIT")
        self._attendre_ou_escalader()

    def recuperer_echantillons(self):
        import numpy as np

        with self._verrou:
            if not self._buffer:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._buffer)
            self._buffer.clear()
        return audio.reshape(-1, self._ch)

    def terminer(self) -> None:
        """Arrêt propre du processus SCK (à appeler à la fermeture de l'app)."""
        self._envoyer_commande("QUIT")
        self._attendre_ou_escalader()

    # ── Privé ────────────────────────────────────────────────────────────────

    def _attendre_ou_escalader(self) -> None:
        """Attend la sortie du helper après QUIT, en escaladant SIGTERM puis
        SIGKILL seulement si le process ne répond pas — laisse une chance à
        stream.stopCapture() de s'exécuter côté Swift (géré sur SIGTERM)."""
        if self._proc is None:
            return
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None

    def _demarrer_processus(self) -> None:
        self._proc = subprocess.Popen(
            [str(BINAIRE)],
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        threading.Thread(target=self._lire_stderr, daemon=True).start()
        threading.Thread(target=self._lire_pcm, daemon=True).start()

    def _envoyer_commande(self, cmd: str) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                assert self._proc.stdin is not None
                self._proc.stdin.write(f"{cmd}\n".encode())
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def _lire_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for ligne in proc.stderr:
            texte = ligne.decode(errors="replace").strip()
            if texte.startswith("FORMAT:"):
                parties = texte.split(":")
                if len(parties) >= 3:
                    try:
                        self._sr = int(parties[1])
                        self._ch = int(parties[2])
                        self._pret.set()
                    except ValueError:
                        pass

    def _lire_pcm(self) -> None:
        import numpy as np

        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            chunk = np.frombuffer(data, dtype=np.float32)
            with self._verrou:
                self._buffer.append(chunk)
