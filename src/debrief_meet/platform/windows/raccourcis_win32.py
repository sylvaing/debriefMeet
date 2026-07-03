"""Raccourcis clavier globaux Windows — `RegisterHotKey` (user32) en ctypes pur
(docs/34 §5, réimplémentation Windows de docs/28).

`WM_HOTKEY` arrive dans la boucle de messages du thread appelant — sous Qt, on
l'intercepte avec un `QAbstractNativeEventFilter` posé sur le thread principal (le
callback est donc invoqué directement, conformément au contrat de l'interface,
`interfaces.py:157`). Piège ctypes (docs/28 §2.1, s'applique pareil à user32) :
déclarer soigneusement `argtypes`/`restype` de chaque fonction native.
"""
from __future__ import annotations

import ctypes
import logging
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

from debrief_meet.platform.interfaces import RaccourcisGlobaux

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000   # évite les répétitions en maintien de la touche

_VK_F1 = 0x70

_MODIFICATEURS = {"Ctrl", "Meta", "Alt", "Shift"}


class MSG(ctypes.Structure):
    """Structure Win32 `MSG` — layout minimal suffisant pour lire `message`/`wParam`."""
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint32),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


def _mods_qt_vers_win32(sequence: str) -> int:
    """Convertit les modificateurs d'une QKeySequence portable en masque Win32.

    Contrairement à macOS, Qt-Ctrl/Qt-Meta correspondent ici directement à
    MOD_CONTROL/MOD_WIN (pas d'échange — spécifique au piège Carbon docs/28 §2.1)."""
    mods = MOD_NOREPEAT
    for token in sequence.split("+"):
        if token == "Ctrl":
            mods |= MOD_CONTROL
        elif token == "Alt":
            mods |= MOD_ALT
        elif token == "Shift":
            mods |= MOD_SHIFT
        elif token == "Meta":
            mods |= MOD_WIN
    return mods


def _caractere_de_base(sequence: str) -> str | None:
    """Composant non-modificateur d'une QKeySequence portable."""
    for token in sequence.split("+"):
        if token and token not in _MODIFICATEURS:
            return token
    return None


def _vk_pour_caractere(caractere: str) -> int | None:
    """VK Win32 pour une touche non-modificateur : lettres/chiffres → code ASCII
    majuscule (identique au VK Win32) ; F1-F12 → VK_F1 + n. `None` si non convertible."""
    if len(caractere) == 1 and caractere.isalnum():
        return ord(caractere.upper())
    if len(caractere) >= 2 and caractere[0] in "fF" and caractere[1:].isdigit():
        n = int(caractere[1:])
        if 1 <= n <= 12:
            return _VK_F1 + (n - 1)
    return None


class _FiltreHotKey(QAbstractNativeEventFilter):
    def __init__(self, sur_hotkey: Callable[[int], None]) -> None:
        super().__init__()
        self._sur_hotkey = sur_hotkey

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) != b"windows_generic_MSG":
            return False, 0
        msg = ctypes.cast(int(message), ctypes.POINTER(MSG)).contents
        if msg.message == WM_HOTKEY:
            self._sur_hotkey(msg.wParam)
        return False, 0


class RaccourcisGlobauxWindows(RaccourcisGlobaux):
    def __init__(self) -> None:
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._prochain_id = 1
        # Référence Python explicitement conservée (piège ctypes/GC docs/28) + posé une
        # seule fois pour la vie de l'objet : `desactiver_tous()` ne le retire pas, il
        # est appelé à chaque changement de raccourcis dans les Préférences (pas
        # seulement à la fermeture) — le retirer casserait la réception après un
        # premier réenregistrement.
        self._filtre = _FiltreHotKey(self._sur_hotkey)
        app = QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filtre)

    def _sur_hotkey(self, hotkey_id: int) -> None:
        callback = self._callbacks.get(hotkey_id)
        if callback is not None:
            try:
                callback()
            except Exception:
                logger.exception("Erreur dans le handler de raccourci global")

    def enregistrer(self, combinaison: str, callback: Callable[[], None]) -> bool:
        mods = _mods_qt_vers_win32(combinaison)
        caractere = _caractere_de_base(combinaison)
        if caractere is None:
            logger.warning("Combinaison de raccourci invalide : %r", combinaison)
            return False

        vk = _vk_pour_caractere(caractere)
        if vk is None:
            logger.warning("Impossible de résoudre un VK pour %r (combinaison %r)",
                          caractere, combinaison)
            return False

        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.RegisterHotKey.restype = ctypes.c_int

        hotkey_id = self._prochain_id
        self._prochain_id += 1

        ok = user32.RegisterHotKey(None, hotkey_id, mods, vk)
        if not ok:
            erreur = ctypes.windll.kernel32.GetLastError()
            logger.warning("Raccourci %r déjà pris ou refusé (GetLastError=%s)", combinaison, erreur)
            return False

        self._callbacks[hotkey_id] = callback
        return True

    def desactiver_tous(self) -> None:
        user32 = ctypes.windll.user32
        user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.UnregisterHotKey.restype = ctypes.c_int
        for hotkey_id in self._callbacks:
            user32.UnregisterHotKey(None, hotkey_id)
        self._callbacks.clear()
