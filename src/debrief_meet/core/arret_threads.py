"""Arrêt robuste des QThread — traite le timeout de wait() au lieu de l'ignorer.

Stratégie en 3 temps (docs/26) :
1. quit() + wait(timeout)                          → cas nominal
2. si échec et `debloquer` fourni : l'appeler      → tue ce qui bloque le thread
   (ex. MoteurTranscription.terminer) puis re-wait
3. si toujours vivant : dé-parenter le thread et le fuir volontairement
   (référence module) — un leak à l'exit vaut mieux qu'un SIGABRT.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QThread

logger = logging.getLogger(__name__)

# Threads abandonnés (étape 3) — la référence les garde vivants côté Python pour que
# Shiboken ne détruise jamais un QThread qui tourne encore. Jamais purgé : par
# construction on n'arrive ici qu'à l'arrêt de l'app ou sur un worker gelé.
_threads_fuites: list[tuple] = []

# QThread SANS parent Qt, vivants tant qu'ils tournent (protégés via proteger_thread).
_threads_vivants: list[tuple] = []


def arreter_thread(
    thread: QThread | None,
    timeout_ms: int,
    debloquer: Callable[[], None] | None = None,
    timeout_deblocage_ms: int = 5_000,
    garder: tuple = (),
) -> bool:
    """Arrête `thread` proprement ; True si le thread est fini au retour.

    `garder` : objets à maintenir vivants avec le thread s'il est fui (typiquement
    le worker qui a été moveToThread() — sinon son wrapper Python peut être GC'd
    et son C++ détruit pendant que le thread l'exécute → SIGSEGV).
    """
    if thread is None or not thread.isRunning():
        return True
    thread.quit()
    if thread.wait(timeout_ms):
        return True
    if debloquer is not None:
        logger.warning("Thread toujours vivant après %d ms — déblocage forcé", timeout_ms)
        try:
            debloquer()
        except Exception:
            logger.exception("Échec du déblocage forcé")
        if thread.wait(timeout_deblocage_ms):
            return True
    logger.error(
        "Thread impossible à arrêter — fuite volontaire (leak > SIGABRT, docs/26)")
    thread.setParent(None)
    _threads_fuites.append((thread, garder))
    return False


def proteger_thread(thread: QThread, *garder: object) -> None:
    """Enregistre (thread, worker…) dans un registre module tant que le thread
    tourne — pour les QThread SANS parent Qt : le registre remplace le parent
    comme garantie de survie des wrappers Python. Auto-retiré sur `finished`."""
    entree = (thread, garder)
    _threads_vivants.append(entree)
    thread.finished.connect(lambda: _retirer(entree))


def _retirer(entree: tuple) -> None:
    try:
        _threads_vivants.remove(entree)
    except ValueError:
        pass
