from __future__ import annotations

import contextlib
import ctypes
import logging

import pytest
from PySide6.QtCore import QCoreApplication

from debrief_meet.platform.windows.raccourcis_win32 import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    MSG,
    WM_HOTKEY,
    RaccourcisGlobauxWindows,
    _caractere_de_base,
    _mods_qt_vers_win32,
    _vk_pour_caractere,
)


# ── Conversion QKeySequence → (mods, vk) — fonctions pures ──────────────────────

@pytest.mark.parametrize("sequence,attendu", [
    ("Ctrl+Alt+D", MOD_CONTROL | MOD_ALT | MOD_NOREPEAT),
    ("Shift+D", MOD_SHIFT | MOD_NOREPEAT),
    ("Meta+Alt+Ctrl+D", MOD_WIN | MOD_ALT | MOD_CONTROL | MOD_NOREPEAT),
])
def test_mods_qt_vers_win32(sequence, attendu):
    assert _mods_qt_vers_win32(sequence) == attendu


def test_caractere_de_base_extrait_la_derniere_touche():
    assert _caractere_de_base("Ctrl+Alt+D") == "D"
    assert _caractere_de_base("Ctrl+F1") == "F1"


def test_vk_pour_caractere_lettres_chiffres_et_f_touches():
    assert _vk_pour_caractere("d") == ord("D")
    assert _vk_pour_caractere("D") == ord("D")
    assert _vk_pour_caractere("5") == ord("5")
    assert _vk_pour_caractere("F1") == 0x70
    assert _vk_pour_caractere("f12") == 0x70 + 11


def test_vk_pour_caractere_non_convertible():
    assert _vk_pour_caractere("PrintScreen") is None
    assert _vk_pour_caractere("F13") is None


# ── user32 mocké ─────────────────────────────────────────────────────────────

class _FakeApiFunc:
    def __init__(self, impl):
        self._impl = impl
        self.argtypes = None
        self.restype = None
        self.appels: list[tuple] = []

    def __call__(self, *a):
        self.appels.append(a)
        return self._impl(*a)


class _FakeUser32:
    def __init__(self, resultats_register=None):
        self._resultats = list(resultats_register) if resultats_register is not None else None
        self.RegisterHotKey = _FakeApiFunc(self._register)
        self.UnregisterHotKey = _FakeApiFunc(lambda *a: 1)

    def _register(self, *a):
        if self._resultats is None:
            return 1
        return self._resultats.pop(0)


class _FakeKernel32:
    def __init__(self, erreur=1409):   # ERROR_HOTKEY_ALREADY_REGISTERED
        self.GetLastError = _FakeApiFunc(lambda: erreur)


class _FakeWindll:
    def __init__(self, user32, kernel32):
        self.user32 = user32
        self.kernel32 = kernel32


@contextlib.contextmanager
def _instance(qapp, monkeypatch, resultats_register=None, erreur=1409):
    fake_user32 = _FakeUser32(resultats_register)
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(fake_user32, _FakeKernel32(erreur)), raising=False)
    r = RaccourcisGlobauxWindows()
    try:
        yield r, fake_user32
    finally:
        QCoreApplication.instance().removeNativeEventFilter(r._filtre)


def test_enregistrer_reussi(qapp, monkeypatch):
    with _instance(qapp, monkeypatch, resultats_register=[1]) as (r, fake_user32):
        assert r.enregistrer("Ctrl+Alt+D", lambda: None) is True
        assert len(fake_user32.RegisterHotKey.appels) == 1


def test_enregistrer_echoue_combo_deja_pris(qapp, monkeypatch, caplog):
    with _instance(qapp, monkeypatch, resultats_register=[0], erreur=1409) as (r, _fake_user32):
        with caplog.at_level(logging.WARNING, logger="debrief_meet"):
            assert r.enregistrer("Ctrl+Alt+D", lambda: None) is False
        assert any("déjà pris" in rec.message for rec in caplog.records)


def test_enregistrer_combinaison_sans_touche_non_modificatrice(qapp, monkeypatch):
    with _instance(qapp, monkeypatch) as (r, fake_user32):
        assert r.enregistrer("Ctrl+Alt", lambda: None) is False
        assert fake_user32.RegisterHotKey.appels == []


def test_enregistrer_touche_non_convertible(qapp, monkeypatch):
    with _instance(qapp, monkeypatch) as (r, fake_user32):
        assert r.enregistrer("Ctrl+Alt+PrintScreen", lambda: None) is False
        assert fake_user32.RegisterHotKey.appels == []


def test_desactiver_tous_desenregistre_tout(qapp, monkeypatch):
    with _instance(qapp, monkeypatch, resultats_register=[1, 1]) as (r, fake_user32):
        r.enregistrer("Ctrl+Alt+D", lambda: None)
        r.enregistrer("Ctrl+Alt+R", lambda: None)
        r.desactiver_tous()
        assert len(fake_user32.UnregisterHotKey.appels) == 2
        assert r._callbacks == {}


# ── Filtre WM_HOTKEY ─────────────────────────────────────────────────────────

def test_filtre_wm_hotkey_invoque_le_callback(qapp, monkeypatch):
    with _instance(qapp, monkeypatch, resultats_register=[1]) as (r, _fake_user32):
        appels = []
        r.enregistrer("Ctrl+Alt+D", lambda: appels.append("d"))

        msg = MSG()
        msg.message = WM_HOTKEY
        msg.wParam = 1
        resultat = r._filtre.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))

        assert appels == ["d"]
        assert resultat == (False, 0)


def test_filtre_ignore_les_messages_non_hotkey(qapp, monkeypatch):
    with _instance(qapp, monkeypatch, resultats_register=[1]) as (r, _fake_user32):
        appels = []
        r.enregistrer("Ctrl+Alt+D", lambda: appels.append("d"))

        msg = MSG()
        msg.message = 0x0001   # WM_CREATE, sans rapport
        msg.wParam = 1
        r._filtre.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))

        assert appels == []


def test_filtre_ignore_les_evenements_non_windows(qapp, monkeypatch):
    with _instance(qapp, monkeypatch) as (r, _fake_user32):
        resultat = r._filtre.nativeEventFilter(b"autre_type", 0)
        assert resultat == (False, 0)
