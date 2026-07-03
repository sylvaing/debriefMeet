from __future__ import annotations

import sys
import types

import pytest

from debrief_meet.platform.windows.demarrage_auto import DemarrageAutoWindows


class _FakeCle:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_winreg(store: dict) -> types.ModuleType:
    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = object()
    fake.REG_SZ = 1
    fake.KEY_SET_VALUE = 2

    def _open_key(hkey, sous_cle, reserved=0, access=None):
        return _FakeCle()

    def _query_value_ex(cle, nom):
        if nom not in store:
            raise FileNotFoundError(nom)
        return store[nom]

    def _set_value_ex(cle, nom, reserved, type_, valeur):
        store[nom] = (valeur, type_)

    def _delete_value(cle, nom):
        if nom not in store:
            raise FileNotFoundError(nom)
        del store[nom]

    fake.OpenKey = _open_key
    fake.QueryValueEx = _query_value_ex
    fake.SetValueEx = _set_value_ex
    fake.DeleteValue = _delete_value
    return fake


@pytest.fixture
def winreg_store(monkeypatch):
    store: dict = {}
    monkeypatch.setitem(sys.modules, "winreg", _fake_winreg(store))
    return store


def test_est_active_absente_par_defaut(winreg_store):
    assert DemarrageAutoWindows().est_active() is False


def test_activer_hors_bundle_ne_fait_rien(winreg_store, monkeypatch, caplog):
    import logging
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        DemarrageAutoWindows().activer()
    assert not winreg_store
    assert any("hors bundle" in r.message for r in caplog.records)


def test_cycle_activer_est_active_desactiver(winreg_store, monkeypatch, tmp_path):
    faux_executable = tmp_path / "debriefMeet.exe"
    faux_executable.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(faux_executable))

    adaptateur = DemarrageAutoWindows()
    assert adaptateur.est_active() is False

    adaptateur.activer()
    assert adaptateur.est_active() is True

    adaptateur.desactiver()
    assert adaptateur.est_active() is False


def test_valeur_orpheline_est_inactive(winreg_store, monkeypatch, tmp_path):
    """L'exécutable référencé a été déplacé/supprimé depuis → considéré inactif."""
    faux_executable = tmp_path / "debriefMeet.exe"
    faux_executable.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(faux_executable))

    adaptateur = DemarrageAutoWindows()
    adaptateur.activer()
    assert adaptateur.est_active() is True

    faux_executable.unlink()
    assert adaptateur.est_active() is False


def test_desactiver_sans_valeur_ne_leve_pas(winreg_store):
    DemarrageAutoWindows().desactiver()
