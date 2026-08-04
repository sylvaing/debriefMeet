"""Relance de l'application après un changement de mode de transcription (docs/45).

Le mode est figé au démarrage (`core/mode_transcription`) : en changer dans les
Préférences demande un redémarrage. Le dialogue pose un drapeau via ``demander()`` ;
``__main__`` appelle ``relancer()`` **après** le retour de ``app.exec()`` — jamais
avant : le mutex Windows (`instance_unique.py`) et le QLocalServer IPC vivent
jusqu'à la mort du process, un fils lancé trop tôt se verrait « déjà en cours »
et sortirait aussitôt. D'où aussi le délai d'une seconde côté fils, et pas
d'``os.execv`` (descripteurs du QLocalServer et mutex hérités).

`sys.platform` est un test stdlib, autorisé dans `core/` (la règle d'or interdit
les *modules* OS-spécifiques, pas la détection d'OS) — même statut que config.py.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import sys

logger = logging.getLogger(__name__)

_demande = False


def demander() -> None:
    """Marque qu'une relance devra suivre la fermeture en cours."""
    global _demande
    _demande = True


def est_demande() -> bool:
    return _demande


def _commande() -> list[str]:
    """Binaire figé (PyInstaller) : `sys.executable` EST l'app ; depuis les
    sources : relancer le module (`python -m debrief_meet`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "debrief_meet"]


def relancer() -> None:
    """Lance un relanceur détaché, avec délai, qui survivra à notre sortie.

    À n'appeler qu'une fois `app.exec()` rendu (aboutToQuit exécutés, threads
    joints) — le process meurt juste après, libérant mutex et socket IPC avant
    que le fils ne démarre vraiment.
    """
    commande = _commande()
    try:
        if sys.platform == "win32":
            # `start` détache dans une nouvelle console ; `ping` ≈ sleep 2 s
            # (pas de `timeout` : il refuse de tourner sans stdin console).
            exe = subprocess.list2cmdline(commande)
            subprocess.Popen(
                f'ping -n 3 127.0.0.1 >nul & start "" {exe}',
                shell=True,
                creationflags=(subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP),
            )
        else:
            exe = " ".join(shlex.quote(c) for c in commande)
            subprocess.Popen(
                ["/bin/sh", "-c", f"sleep 1; exec {exe}"],
                start_new_session=True,
            )
        logger.info("Relance programmée : %s", commande)
    except OSError as exc:
        # Jamais bloquant : au pire l'utilisateur relance à la main.
        logger.error("Relance impossible (%s) — relancer manuellement", exc)
