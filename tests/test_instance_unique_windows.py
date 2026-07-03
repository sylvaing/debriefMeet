from __future__ import annotations

import ctypes

import pytest

import debrief_meet.platform.windows.instance_unique as instance_unique_module
from debrief_meet.platform.windows.instance_unique import acquerir_instance_unique


class _FakeApiFunc:
    def __init__(self, impl):
        self._impl = impl
        self.argtypes = None
        self.restype = None

    def __call__(self, *a, **kw):
        return self._impl(*a, **kw)


class _FakeKernel32:
    def __init__(self, handle, erreur):
        self.CreateMutexW = _FakeApiFunc(lambda *a: handle)
        self.GetLastError = _FakeApiFunc(lambda: erreur)


class _FakeWindll:
    def __init__(self, handle, erreur):
        self.kernel32 = _FakeKernel32(handle, erreur)


@pytest.fixture(autouse=True)
def _reset_handle(monkeypatch):
    monkeypatch.setattr(instance_unique_module, "_handle_mutex", None)


def test_acquis_quand_aucune_instance_active(monkeypatch):
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(handle=1234, erreur=0), raising=False)
    assert acquerir_instance_unique() is True


def test_refuse_quand_une_instance_est_deja_active(monkeypatch):
    monkeypatch.setattr(
        ctypes, "windll", _FakeWindll(handle=1234, erreur=instance_unique_module._ERROR_ALREADY_EXISTS),
        raising=False,
    )
    assert acquerir_instance_unique() is False


def test_echec_api_ne_bloque_pas_le_demarrage(monkeypatch, caplog):
    import logging
    monkeypatch.setattr(ctypes, "windll", _FakeWindll(handle=0, erreur=5), raising=False)
    with caplog.at_level(logging.WARNING, logger="debrief_meet"):
        assert acquerir_instance_unique() is True
    assert any("CreateMutexW a échoué" in r.message for r in caplog.records)
