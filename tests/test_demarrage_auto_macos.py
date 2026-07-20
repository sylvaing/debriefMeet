"""Tests — DemarrageAutoMacOS : contenu du LaunchAgent (dev vs app figée, docs/16 §5.4)."""
from __future__ import annotations

import sys
from pathlib import Path

from debrief_meet.core import ressources
from debrief_meet.platform.macos.demarrage_auto import DemarrageAutoMacOS


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
