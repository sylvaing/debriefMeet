"""Raccourcis clavier globaux macOS — Carbon/HIToolbox en ctypes pur (docs/28).

Choix : `RegisterEventHotKey` plutôt que `CGEventTap`/`NSEvent.addGlobalMonitor` — pas
de permission TCC (Accessibilité) requise, ce qui préserve la stabilité des permissions
sur laquelle repose le packaging (docs/16).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
from typing import Callable

from debrief_meet.platform.interfaces import RaccourcisGlobaux

logger = logging.getLogger(__name__)

# ── Constantes Carbon ────────────────────────────────────────────────────────

cmdKey = 0x0100
shiftKey = 0x0200
optionKey = 0x0800
controlKey = 0x1000

kEventClassKeyboard = 0x6B657962   # 'keyb'
kEventHotKeyPressed = 5
kEventParamDirectObject = 0x2D2D2D2D   # '----'
typeEventHotKeyID = 0x686B6964   # 'hkid'
_SIGNATURE = 0x64627266   # 'dbrf'

kUCKeyActionDisplay = 3
kUCKeyTranslateNoDeadKeysBit = 1 << 0

noErr = 0

_MODIFICATEURS = {"Ctrl", "Meta", "Alt", "Shift"}

# Table de repli (piège §2.2 docs/28) — keycodes physiques Apple (kVK_ANSI_*), positions
# QWERTY. D, R, J sont aux mêmes positions physiques en AZERTY et QWERTY.
_KEYCODES_REPLI = {
    "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E, "f": 0x03, "g": 0x05,
    "h": 0x04, "i": 0x22, "j": 0x26, "k": 0x28, "l": 0x25, "m": 0x2E, "n": 0x2D,
    "o": 0x1F, "p": 0x23, "q": 0x0C, "r": 0x0F, "s": 0x01, "t": 0x11, "u": 0x20,
    "v": 0x09, "w": 0x0D, "x": 0x07, "y": 0x10, "z": 0x06,
    "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
    "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
}


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


def _mods_qt_vers_carbon(sequence: str) -> int:
    """Convertit les modificateurs d'une QKeySequence portable en masque Carbon.

    Piège §2.1 docs/28 : Qt échange Ctrl et Cmd sur macOS. Dans le format
    portable, Qt-Ctrl (`ControlModifier`) correspond à la touche ⌘ (cmdKey) et
    Qt-Meta (`MetaModifier`) correspond à la touche ⌃ (controlKey)."""
    mods = 0
    for token in sequence.split("+"):
        if token == "Ctrl":
            mods |= cmdKey
        elif token == "Meta":
            mods |= controlKey
        elif token == "Alt":
            mods |= optionKey
        elif token == "Shift":
            mods |= shiftKey
    return mods


def _caractere_de_base(sequence: str) -> str | None:
    """Composant non-modificateur d'une QKeySequence portable, en minuscule."""
    for token in sequence.split("+"):
        if token and token not in _MODIFICATEURS:
            return token.lower()
    return None


def _keycode_pour_caractere(caractere: str) -> int | None:
    """Résout le keycode physique correspondant à `caractere` selon le layout clavier
    courant (piège §2.2 docs/28 : AZERTY ≠ QWERTY). Retombe sur `_KEYCODES_REPLI` si la
    résolution Carbon échoue."""
    try:
        keycode = _keycode_via_tis(caractere)
        if keycode is not None:
            return keycode
    except Exception:
        logger.exception("Résolution clavier Carbon en échec pour %r — repli sur la table fixe", caractere)
    logger.warning("Repli table fixe pour le caractère %r (résolution layout indisponible)", caractere)
    return _KEYCODES_REPLI.get(caractere)


def _keycode_via_tis(caractere: str) -> int | None:
    carbon = _charger_carbon()
    if carbon is None:
        return None
    cf = _charger_core_foundation()
    if cf is None:
        return None

    source = carbon.TISCopyCurrentKeyboardLayoutInputSource()
    if not source:
        return None
    try:
        cle = ctypes.c_void_p.in_dll(carbon, "kTISPropertyUnicodeKeyLayoutData")
        donnees = carbon.TISGetInputSourceProperty(ctypes.c_void_p(source), cle)
        if not donnees:
            return None

        layout_ptr = cf.CFDataGetBytePtr(ctypes.c_void_p(donnees))
        if not layout_ptr:
            return None

        kbd_type = carbon.LMGetKbdType()

        buffer = (ctypes.c_uint16 * 8)()
        longueur = ctypes.c_uint32(0)
        dead_key_state = ctypes.c_uint32(0)

        for keycode in range(128):
            dead_key_state.value = 0
            statut = carbon.UCKeyTranslate(
                ctypes.c_void_p(layout_ptr),
                ctypes.c_uint16(keycode),
                ctypes.c_uint16(kUCKeyActionDisplay),
                ctypes.c_uint32(0),
                ctypes.c_uint32(kbd_type),
                ctypes.c_uint32(kUCKeyTranslateNoDeadKeysBit),
                ctypes.byref(dead_key_state),
                ctypes.c_uint32(len(buffer)),
                ctypes.byref(longueur),
                buffer,
            )
            if statut != noErr or longueur.value == 0:
                continue
            produit = bytes(buffer)[: longueur.value * 2].decode("utf-16-le", errors="ignore")
            if produit.lower() == caractere:
                return keycode
        return None
    finally:
        cf.CFRelease(ctypes.c_void_p(source))


_carbon_cache: ctypes.CDLL | None = None
_cf_cache: ctypes.CDLL | None = None


def _charger_carbon() -> ctypes.CDLL | None:
    global _carbon_cache
    if _carbon_cache is not None:
        return _carbon_cache
    chemin = ctypes.util.find_library("Carbon")
    if chemin is None:
        return None
    carbon = ctypes.CDLL(chemin)
    carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = ctypes.c_void_p
    carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
    carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.LMGetKbdType.restype = ctypes.c_uint8
    carbon.UCKeyTranslate.restype = ctypes.c_int32
    _carbon_cache = carbon
    return _carbon_cache


def _charger_core_foundation() -> ctypes.CDLL | None:
    global _cf_cache
    if _cf_cache is not None:
        return _cf_cache
    chemin = ctypes.util.find_library("CoreFoundation")
    if chemin is None:
        return None
    cf = ctypes.CDLL(chemin)
    cf.CFDataGetBytePtr.restype = ctypes.c_void_p
    cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    _cf_cache = cf
    return _cf_cache


_HotKeyHandlerType = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class RaccourcisGlobauxMacOS(RaccourcisGlobaux):
    def __init__(self) -> None:
        self._carbon = _charger_carbon()
        if self._carbon is None:
            raise RuntimeError("Carbon.framework introuvable")

        self._callbacks: dict[int, Callable[[], None]] = {}
        self._refs: dict[int, ctypes.c_void_p] = {}
        self._prochain_id = 1

        # Références Python conservées explicitement — sans elles le GC libère le
        # CFUNCTYPE/la structure et Carbon appelle un pointeur mort → crash (piège
        # ctypes docs/28).
        self._handler = _HotKeyHandlerType(self._sur_evenement)
        self._spec = EventTypeSpec(kEventClassKeyboard, kEventHotKeyPressed)

        self._carbon.InstallEventHandler(
            ctypes.c_void_p(self._carbon.GetApplicationEventTarget()),
            self._handler,
            1,
            ctypes.byref(self._spec),
            None,
            None,
        )

    def _sur_evenement(self, _next_handler, event, _user_data) -> int:
        try:
            hkid = EventHotKeyID()
            self._carbon.GetEventParameter(
                ctypes.c_void_p(event),
                ctypes.c_uint32(kEventParamDirectObject),
                ctypes.c_uint32(typeEventHotKeyID),
                None,
                ctypes.sizeof(EventHotKeyID),
                None,
                ctypes.byref(hkid),
            )
            callback = self._callbacks.get(hkid.id)
            if callback is not None:
                callback()
        except Exception:
            logger.exception("Erreur dans le handler de raccourci global")
        return noErr

    def enregistrer(self, combinaison: str, callback: Callable[[], None]) -> bool:
        mods = _mods_qt_vers_carbon(combinaison)
        caractere = _caractere_de_base(combinaison)
        if caractere is None:
            logger.warning("Combinaison de raccourci invalide : %r", combinaison)
            return False

        keycode = _keycode_pour_caractere(caractere)
        if keycode is None:
            logger.warning("Impossible de résoudre un keycode pour %r (combinaison %r)",
                          caractere, combinaison)
            return False

        hotkey_id = self._prochain_id
        self._prochain_id += 1

        hkid = EventHotKeyID(_SIGNATURE, hotkey_id)
        ref = ctypes.c_void_p()
        statut = self._carbon.RegisterEventHotKey(
            ctypes.c_uint32(keycode),
            ctypes.c_uint32(mods),
            hkid,
            ctypes.c_void_p(self._carbon.GetApplicationEventTarget()),
            ctypes.c_uint32(0),
            ctypes.byref(ref),
        )
        if statut != noErr:
            logger.warning("Raccourci %r déjà pris ou refusé (statut Carbon %d)", combinaison, statut)
            return False

        self._callbacks[hotkey_id] = callback
        self._refs[hotkey_id] = ref
        return True

    def desactiver_tous(self) -> None:
        for ref in self._refs.values():
            self._carbon.UnregisterEventHotKey(ref)
        self._refs.clear()
        self._callbacks.clear()
