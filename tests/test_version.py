from __future__ import annotations

import importlib
import sys
import types


def test_version_complete_repli_dev(monkeypatch):
    """Sans `_version.py` (exécution depuis les sources) : repli `<version>+dev`."""
    monkeypatch.delitem(sys.modules, "debrief_meet._version", raising=False)
    import debrief_meet
    importlib.reload(debrief_meet)
    try:
        assert debrief_meet.VERSION_COMPLETE == debrief_meet.__version__ + "+dev"
    finally:
        importlib.reload(debrief_meet)


def test_version_complete_lit_le_fichier_genere(monkeypatch):
    """`_version.py` présent (généré par le build, docs/32) : sa valeur est reprise telle
    quelle, sans reconstruction — c'est elle qui porte le hash git."""
    faux_module = types.ModuleType("debrief_meet._version")
    faux_module.VERSION_COMPLETE = "0.2.0+20260703.a1b2c3d"
    monkeypatch.setitem(sys.modules, "debrief_meet._version", faux_module)
    import debrief_meet
    importlib.reload(debrief_meet)
    try:
        assert debrief_meet.VERSION_COMPLETE == "0.2.0+20260703.a1b2c3d"
    finally:
        monkeypatch.delitem(sys.modules, "debrief_meet._version", raising=False)
        importlib.reload(debrief_meet)
