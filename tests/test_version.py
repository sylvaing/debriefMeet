from __future__ import annotations

import importlib
import sys
import types


def test_version_complete_repli_dev(monkeypatch):
    """Sans `_version.py` (exécution depuis les sources) : repli `<version>+dev`.

    `sys.modules[...] = None` force l'ImportError même si le fichier existe — cas
    de la VM de build, où `generer_version.py` produit `_version.py` AVANT pytest."""
    monkeypatch.setitem(sys.modules, "debrief_meet._version", None)
    import debrief_meet
    importlib.reload(debrief_meet)
    try:
        assert debrief_meet.VERSION_COMPLETE == debrief_meet.__version__ + "+dev"
    finally:
        monkeypatch.delitem(sys.modules, "debrief_meet._version", raising=False)
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


def test_version_complete_ignore_un_attribut_de_paquet_perime(monkeypatch):
    """Régression diagnostiquée sur la gate VM le 2026-07-30.

    `from debrief_meet import _version` + `getattr` se satisfait de l'attribut déjà posé
    sur le paquet et **court-circuite `sys.modules`** : la valeur d'un build précédent
    survivait alors à sa neutralisation, et ce module devenait intestable dès que
    `_version.py` existait sur disque (le cas sur la VM, où le build le génère avant
    pytest). La forme `from debrief_meet._version import X` passe forcément par
    `sys.modules` — c'est elle qu'il faut conserver."""
    faux = types.ModuleType("debrief_meet._version")
    faux.VERSION_COMPLETE = "0.0.0+perime"
    import debrief_meet
    monkeypatch.setattr(debrief_meet, "_version", faux, raising=False)
    monkeypatch.setitem(sys.modules, "debrief_meet._version", None)
    importlib.reload(debrief_meet)
    try:
        assert debrief_meet.VERSION_COMPLETE == debrief_meet.__version__ + "+dev"
    finally:
        monkeypatch.delitem(sys.modules, "debrief_meet._version", raising=False)
        importlib.reload(debrief_meet)
