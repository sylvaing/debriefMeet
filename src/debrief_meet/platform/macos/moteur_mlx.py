from __future__ import annotations

import logging
import os
import pickle
import queue
import subprocess
import sys
import threading
from typing import Callable, TYPE_CHECKING

from debrief_meet.core.modeles import resoudre_mlx
from debrief_meet.platform.interfaces import MoteurTranscription, ResultatTranscription, Segment

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# Nombre de workers simultanés — 2 permet de transcrire micro + système en parallèle.
_TAILLE_POOL = 2


def _commande_worker() -> list[str]:
    """Commande de lancement d'un worker MLX.

    En dev : ``python -m debrief_meet.platform.macos._mlx_worker``.
    En app figée (PyInstaller) : ``-m`` n'existe pas → le binaire .app se
    relance lui-même avec ``--mlx-worker`` (routé tôt dans __main__.main()).
    """
    from debrief_meet.core.ressources import est_figee

    if est_figee():
        return [sys.executable, "--mlx-worker"]
    return [sys.executable, "-m", "debrief_meet.platform.macos._mlx_worker"]


class _WorkerSubprocess:
    """Un sous-processus mlx_whisper avec son propre contexte Metal.

    La communication stdin/stdout (pickle length-prefixed) est sérialisée par
    self._lock pour que plusieurs threads puissent partager le même worker
    sans interleave. En pratique, chaque worker est utilisé par un seul thread
    à la fois (pool d'objets dans MoteurMLX).
    """

    _TIMEOUT_DEMARRAGE = 60.0

    def __init__(self, repo: str) -> None:
        self._repo = repo
        self._proc: subprocess.Popen | None = None
        self._pret = threading.Event()
        self._lock = threading.Lock()

    def demarrer(self) -> None:
        """Démarre le sous-processus et attend READY (bloquant)."""
        env = {**os.environ, "MLX_WORKER_REPO": self._repo}
        self._pret.clear()
        self._proc = subprocess.Popen(
            _commande_worker(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        threading.Thread(
            target=self._lire_stderr,
            daemon=True,
            name=f"mlx-stderr-{id(self)}",
        ).start()
        if not self._pret.wait(timeout=self._TIMEOUT_DEMARRAGE):
            raise RuntimeError("Worker MLX n'a pas démarré dans les délais")

    def transcrire(self, audio_bytes: bytes, repo: str, langue: str | None) -> dict:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                logger.warning("Worker MLX mort — redémarrage")
                self.demarrer()

            request_bytes = pickle.dumps({
                "audio_bytes": audio_bytes,
                "repo": repo,
                "langue": langue,
            })
            try:
                self._proc.stdin.write(len(request_bytes).to_bytes(4, "big") + request_bytes)
                self._proc.stdin.flush()
                header = self._proc.stdout.read(4)
                if not header:
                    raise RuntimeError("Sous-processus MLX crashé (pipe fermé)")
                length = int.from_bytes(header, "big")
                return pickle.loads(self._proc.stdout.read(length))
            except (BrokenPipeError, OSError) as exc:
                self._proc = None
                raise RuntimeError(f"Sous-processus MLX mort : {exc}") from exc

    def terminer(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            quit_bytes = pickle.dumps({"quit": True})
            self._proc.stdin.write(len(quit_bytes).to_bytes(4, "big") + quit_bytes)
            self._proc.stdin.flush()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
                self._proc.wait()
            except Exception:
                pass
        self._proc = None

    def tuer(self) -> None:
        """Kill immédiat, sans handshake stdin. Idempotent. Ferme le pipe → tout
        thread bloqué dans stdout.read() est libéré (lit b"" → RuntimeError)."""
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait()
        except Exception:
            pass
        self._proc = None

    def _lire_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for ligne_bytes in proc.stderr:
            texte = ligne_bytes.decode(errors="replace").strip()
            if texte == "READY":
                self._pret.set()
            elif texte:
                logger.debug("[mlx-worker] %s", texte)


class MoteurMLX(MoteurTranscription):
    """Moteur de transcription MLX — pool de sous-processus isolés.

    Chaque sous-processus a son propre contexte Metal, ce qui :
    - isole les crashes Bus error: 10 (SIGBUS) — le process meurt, pas l'app
    - permet la transcription micro + système en parallèle (_TAILLE_POOL = 2)

    Le modèle est préchargé dans chaque worker dès charger_modele(), de sorte
    qu'il est prêt bien avant la première réunion.
    """

    def __init__(self) -> None:
        self._nom_charge: str | None = None
        self._pool: queue.Queue[_WorkerSubprocess] = queue.Queue()
        self._n_workers = 0
        self._n_workers_lock = threading.Lock()
        self._workers: list[_WorkerSubprocess] = []   # TOUS les workers créés (pool + sortis)

    # ── Interface publique ────────────────────────────────────────────────────

    @property
    def acceleration(self) -> str:
        return "Metal"

    def charger_modele(self, nom: str) -> None:
        self._nom_charge = nom
        repo = resoudre_mlx(nom)
        for _ in range(_TAILLE_POOL):
            threading.Thread(
                target=self._creer_worker,
                args=(repo,),
                daemon=True,
                name="mlx-worker-init",
            ).start()

    def _transcrire_pret(self, audio: "np.ndarray", langue: str | None) -> ResultatTranscription:
        repo = resoudre_mlx(self._nom_charge or "large-v3")

        # Si aucun worker n'a encore été créé (pas de charger_modele()), en créer un
        with self._n_workers_lock:
            if self._n_workers == 0:
                self._n_workers = 1
                threading.Thread(
                    target=self._creer_worker, args=(repo,), daemon=True
                ).start()

        try:
            worker = self._pool.get(timeout=90)
        except queue.Empty:
            raise RuntimeError("Aucun worker MLX disponible (timeout 90 s)")

        try:
            response = worker.transcrire(audio.tobytes(), repo, langue)
        finally:
            self._pool.put(worker)

        if not response.get("ok"):
            raise RuntimeError(response.get("erreur", "Erreur MLX inconnue"))

        segments = [
            Segment(s["start"], s["end"], s["text"])
            for s in response.get("segments", [])
        ]
        return ResultatTranscription(
            texte=response["texte"],
            langue_detectee=response.get("langue"),
            segments=segments,
        )

    def est_telecharge(self, nom: str) -> bool:
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(resoudre_mlx(nom), local_files_only=True)
            return True
        except Exception:
            return False

    def telecharger_modele(self, nom: str, progression: Callable[[float], None] | None = None) -> None:
        from huggingface_hub import snapshot_download
        snapshot_download(resoudre_mlx(nom))
        if progression:
            progression(1.0)

    def terminer(self) -> None:
        """Arrêt propre de tous les workers.

        Bloque jusqu'à ce que les workers en cours de transcription aient terminé
        (ou jusqu'au timeout), évitant un crash Metal si on détruit le pool
        pendant qu'un sous-processus utilise le GPU.
        """
        with self._n_workers_lock:
            n = self._n_workers
        workers = []
        for _ in range(n):
            try:
                workers.append(self._pool.get(timeout=15))
            except queue.Empty:
                break
        for w in workers:
            w.terminer()
        # Balayage final : tue tout worker du registre jamais rendu au pool (gelé en
        # pleine transcription, ex. read() bloqué) — tuer() est idempotent, pas besoin
        # de distinguer ceux déjà arrêtés poliment ci-dessus (docs/26).
        with self._n_workers_lock:
            restants = list(self._workers)
            self._workers.clear()
        for w in restants:
            w.tuer()
        # État remis à zéro → un charger_modele() ultérieur (ex. recharger à chaud)
        # repart d'un pool propre au lieu de cumuler avec d'anciens workers.
        with self._n_workers_lock:
            self._n_workers = 0

    # ── Privé ─────────────────────────────────────────────────────────────────

    def _creer_worker(self, repo: str) -> None:
        with self._n_workers_lock:
            self._n_workers += 1
        try:
            w = _WorkerSubprocess(repo)
            w.demarrer()
            with self._n_workers_lock:
                self._workers.append(w)
            self._pool.put(w)
            logger.info("Worker MLX prêt (pool=%d)", self._pool.qsize())
        except Exception:
            logger.exception("Échec démarrage worker MLX")
            with self._n_workers_lock:
                self._n_workers -= 1
