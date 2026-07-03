"""Mutex Win32 nommé — instance unique + `AppMutex` Inno Setup (docs/34 §6).

Double rôle : (a) éviter deux instances (deux captures micro concurrentes) — même si
`ipc.py` (QLocalServer, cross-platform) couvre déjà ce cas côté app ; (b) permettre à
l'installeur Inno Setup de détecter l'app en cours d'exécution via `AppMutex` et
proposer de la fermer avant une mise à jour (docs/32 §3.3) — le nom doit être
strictement identique des deux côtés.
"""
from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)

NOM_MUTEX = "debriefMeet-instance"
_ERROR_ALREADY_EXISTS = 183

# Référence gardée toute la vie du process : l'OS libère le mutex à la mort du
# process, y compris SIGKILL (E-3, docs/33 §2.3) — rien à nettoyer explicitement.
_handle_mutex = None


def acquerir_instance_unique() -> bool:
    """True si cette instance a acquis le mutex (aucune autre instance active)."""
    global _handle_mutex

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.GetLastError.restype = ctypes.c_uint32

    handle = kernel32.CreateMutexW(None, 0, NOM_MUTEX)
    erreur = kernel32.GetLastError()

    if not handle:
        logger.warning("CreateMutexW a échoué (GetLastError=%s) — pas de blocage", erreur)
        return True

    _handle_mutex = handle
    if erreur == _ERROR_ALREADY_EXISTS:
        logger.info("Instance debriefMeet déjà active")
        return False
    return True
