"""Tests — DemarrageAutoMacOS : contenu du LaunchAgent (dev vs app figée, docs/16 §5.4)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from debrief_meet.core import ressources
from debrief_meet.platform.macos.demarrage_auto import DemarrageAutoMacOS

# Adaptateur macOS : les assertions comparent des chemins POSIX au contenu du plist, ce
# qui échoue sur Windows (antislashes) alors que rien de macOS n'y est livré. Constaté
# sur la gate VM le 2026-07-30 — antérieur à docs/44, simplement jamais exercé depuis.
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="LaunchAgent macOS uniquement")


def test_active_desactive(tmp_path):
    plist = tmp_path / "com.sylvaingarcia.debriefmeet.plist"
    d = DemarrageAutoMacOS(plist_path=plist)
    assert d.est_active() is False
    d.activer()
    assert d.est_active() is True
    d.desactiver()
    assert d.est_active() is False


def test_activer_dev_utilise_sys_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(ressources, "est_figee", lambda: False)
    plist = tmp_path / "x.plist"
    DemarrageAutoMacOS(plist_path=plist).activer()
    contenu = plist.read_text(encoding="utf-8")
    assert Path(sys.argv[0]).resolve().as_posix() in contenu


def test_activer_figee_utilise_sys_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(ressources, "est_figee", lambda: True)
    plist = tmp_path / "x.plist"
    DemarrageAutoMacOS(plist_path=plist).activer()
    contenu = plist.read_text(encoding="utf-8")
    assert Path(sys.executable).resolve().as_posix() in contenu
