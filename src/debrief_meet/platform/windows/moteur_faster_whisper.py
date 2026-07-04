"""Moteur de transcription Windows — faster-whisper (CTranslate2) en sous-processus.

Miroir structurel de `macos/moteur_mlx.py` + `_mlx_worker.py` (docs/34 §1) : pool de
workers sous-processus, protocole pickle sur stdin/stdout, chargement paresseux,
registre de tous les workers créés + kill forcé dans `terminer()`. Les invariants
docs/26 (worker sorti du pool pendant une transcription gelée → kill via le
registre) s'appliquent à l'identique — c'est la raison du choix subprocess
(docs/30 §4.4) : in-process, une transcription gelée serait intuable (GIL) et le
crash à l'arrêt (docs/24) reviendrait.

Différences vs MLX :
- pool de 1 worker (pas 2) : un modèle CT2 par process = ~1-3 Go de RAM, les
  machines cibles ont 16 Go et l'app doit rester discrète.
- `download_root` forcé vers `platformdirs.user_data_dir(APP_NAME)/modeles`, jamais
  le cache HF global — condition de la désinstallation complète sûre (docs/32 §4).
- `device="cpu", compute_type="int8"` (v1, décision D2 — cf. `selection_backend.py`).
"""
from __future__ import annotations

import logging
import os
import pickle
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, TYPE_CHECKING

import platformdirs

from debrief_meet import APP_NAME
from debrief_meet.core.modeles import resoudre_faster_whisper
from debrief_meet.platform.interfaces import MoteurTranscription, ResultatTranscription, Segment

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# Un seul worker : un process CT2 int8 pèse ~1-3 Go de RAM (constante de module pour
# pouvoir l'ajuster si le rapport spike docs/18 change la donne).
_TAILLE_POOL = 1

_COMPUTE_TYPE = "int8"


def dossier_modeles() -> Path:
    """`download_root` forcé (docs/34 §1.3) — jamais le cache HF global.

    `appauthor=False` : sans lui, platformdirs double le dossier sur Windows
    (`%LOCALAPPDATA%\\debriefMeet\\debriefMeet`) — il traite `appname` comme
    « author » par défaut quand aucun n'est fourni (docs/32 §4)."""
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)) / "modeles"


def _coeurs_physiques_bornes(maximum: int = 8) -> int:
    """Meilleure estimation des cœurs physiques sans dépendance supplémentaire
    (`psutil` n'est pas une dépendance de l'extra windows) : diviser les threads
    logiques par 2 est une approximation raisonnable sur les CPU grand public avec
    hyperthreading. Sous-estime légèrement sur les CPU hybrides Intel (i5-1235U),
    sans conséquence pratique pour dimensionner un pool de threads CT2."""
    logiques = os.cpu_count() or 4
    return max(1, min(maximum, logiques // 2 or 1))


def _commande_worker() -> list[str]:
    """Commande de lancement d'un worker faster-whisper.

    En dev : ``python -m debrief_meet.platform.windows._fw_worker``.
    En app figée (PyInstaller) : ``-m`` n'existe pas → le binaire relance
    lui-même avec ``--fw-worker`` (routé tôt dans __main__.main())."""
    from debrief_meet.core.ressources import est_figee

    if est_figee():
        return [sys.executable, "--fw-worker"]
    return [sys.executable, "-m", "debrief_meet.platform.windows._fw_worker"]


class _WorkerSubprocess:
    """Un sous-processus faster-whisper. Communication stdin/stdout (pickle
    length-prefixed) sérialisée par `self._lock` — même motif que MLX."""

    _TIMEOUT_DEMARRAGE = 60.0

    def __init__(self, repo: str) -> None:
        self._repo = repo
        self._proc: subprocess.Popen | None = None
        self._pret = threading.Event()
        self._lock = threading.Lock()

    def demarrer(self) -> None:
        """Démarre le sous-processus et attend READY (bloquant)."""
        env = {
            **os.environ,
            "FW_WORKER_REPO": self._repo,
            "FW_WORKER_DOWNLOAD_ROOT": str(dossier_modeles()),
            "FW_WORKER_COMPUTE_TYPE": _COMPUTE_TYPE,
            "FW_WORKER_CPU_THREADS": str(_coeurs_physiques_bornes()),
        }
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
            name=f"fw-stderr-{id(self)}",
        ).start()
        if not self._pret.wait(timeout=self._TIMEOUT_DEMARRAGE):
            raise RuntimeError("Worker faster-whisper n'a pas démarré dans les délais")

    def transcrire(self, audio_bytes: bytes, repo: str, langue: str | None) -> dict:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                logger.warning("Worker faster-whisper mort — redémarrage")
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
                    raise RuntimeError("Sous-processus faster-whisper crashé (pipe fermé)")
                length = int.from_bytes(header, "big")
                return pickle.loads(self._proc.stdout.read(length))
            except (BrokenPipeError, OSError) as exc:
                self._proc = None
                raise RuntimeError(f"Sous-processus faster-whisper mort : {exc}") from exc

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
            except Exception as exc:
                logger.debug("Worker faster-whisper : kill de secours sans effet (%s)", exc)
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
        except Exception as exc:
            logger.debug("Worker faster-whisper : kill déjà sans effet (process mort ?) (%s)", exc)
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
                logger.debug("[fw-worker] %s", texte)


class MoteurFasterWhisper(MoteurTranscription):
    """Moteur de transcription Windows v1 — faster-whisper CPU int8, pool de 1
    sous-processus isolé (E-4, docs/33 §2.4) : crash natif = process tué, pas l'app."""

    def __init__(self) -> None:
        self._nom_charge: str | None = None
        self._pool: queue.Queue[_WorkerSubprocess] = queue.Queue()
        self._n_workers = 0
        self._n_workers_lock = threading.Lock()
        self._workers: list[_WorkerSubprocess] = []   # TOUS les workers créés (pool + sortis)

    # ── Interface publique ────────────────────────────────────────────────────

    @property
    def acceleration(self) -> str:
        return "CPU"

    def charger_modele(self, nom: str) -> None:
        self._nom_charge = nom
        repo = resoudre_faster_whisper(nom)
        for _ in range(_TAILLE_POOL):
            threading.Thread(
                target=self._creer_worker,
                args=(repo,),
                daemon=True,
                name="fw-worker-init",
            ).start()

    # N'override JAMAIS `transcrire()` (E-5, docs/33 §2.5) : la normalisation +
    # porte anti-silence sont héritées de `MoteurTranscription.transcrire()`.
    def _transcrire_pret(self, audio: "np.ndarray", langue: str | None) -> ResultatTranscription:
        repo = resoudre_faster_whisper(self._nom_charge or "large-v3-turbo")

        with self._n_workers_lock:
            if self._n_workers == 0:
                self._n_workers = 1
                threading.Thread(
                    target=self._creer_worker, args=(repo,), daemon=True
                ).start()

        try:
            worker = self._pool.get(timeout=90)
        except queue.Empty:
            raise RuntimeError("Aucun worker faster-whisper disponible (timeout 90 s)")

        duree_audio_s = len(audio) / 16_000
        debut = time.monotonic()
        try:
            response = worker.transcrire(audio.tobytes(), repo, langue)
        finally:
            self._pool.put(worker)
        duree_transcription_s = time.monotonic() - debut

        if not response.get("ok"):
            raise RuntimeError(response.get("erreur", "Erreur faster-whisper inconnue"))

        segments = [
            Segment(s["start"], s["end"], s["text"])
            for s in response.get("segments", [])
        ]
        # Sonde hallucinations (E-1, docs/22/31 §3.7.2) : jamais le texte lui-même,
        # seulement sa longueur — un RMS très bas + un texte long est la signature à
        # surveiller dans un zip diagnostic sans reproduction locale.
        rtf = duree_transcription_s / duree_audio_s if duree_audio_s > 0 else 0.0
        logger.debug(
            "Tranche transcrite : audio=%.2fs transcription=%.2fs rtf=%.2f segments=%d longueur_texte=%d",
            duree_audio_s, duree_transcription_s, rtf, len(segments), len(response["texte"]),
        )
        return ResultatTranscription(
            texte=response["texte"],
            langue_detectee=response.get("langue"),
            segments=segments,
        )

    def est_telecharge(self, nom: str) -> bool:
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(
                resoudre_faster_whisper(nom), cache_dir=str(dossier_modeles()), local_files_only=True
            )
            return True
        except Exception:
            return False

    def telecharger_modele(self, nom: str, progression: Callable[[float], None] | None = None) -> None:
        from huggingface_hub import snapshot_download
        snapshot_download(resoudre_faster_whisper(nom), cache_dir=str(dossier_modeles()))
        if progression:
            progression(1.0)

    def terminer(self) -> None:
        """Arrêt propre de tous les workers — sémantique identique à MoteurMLX
        post-docs/26 : pool vidé avec timeout, puis kill inconditionnel de tout
        worker du registre encore vivant (transcription gelée, read() bloqué)."""
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
        with self._n_workers_lock:
            restants = list(self._workers)
            self._workers.clear()
        for w in restants:
            w.tuer()
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
            logger.info("Worker faster-whisper prêt (pool=%d)", self._pool.qsize())
        except Exception:
            logger.exception("Échec démarrage worker faster-whisper")
            with self._n_workers_lock:
                self._n_workers -= 1
