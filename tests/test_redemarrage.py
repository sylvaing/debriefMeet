"""Relance après changement de mode (docs/45) — drapeau + commande, sans spawn réel."""
from __future__ import annotations

import sys

from debrief_meet.core import redemarrage


def test_drapeau_initialement_baisse(monkeypatch):
    monkeypatch.setattr(redemarrage, "_demande", False)
    assert not redemarrage.est_demande()
    redemarrage.demander()
    assert redemarrage.est_demande()


def test_commande_depuis_les_sources(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert redemarrage._commande() == [sys.executable, "-m", "debrief_meet"]


def test_commande_en_app_figee(monkeypatch):
    """PyInstaller : `sys.executable` EST l'app — pas de `-m` (le relais `-c` de
    `_relais_interprete_figee` n'est pas concerné, on ne passe aucun argument)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert redemarrage._commande() == [sys.executable]


def test_relancer_spawn_detache_avec_delai(monkeypatch):
    """Le fils doit attendre la mort du père (mutex Windows, socket IPC) : délai
    obligatoire, et détachement de la session pour survivre à notre sortie."""
    appels = []
    monkeypatch.setattr(redemarrage.subprocess, "Popen",
                        lambda *a, **k: appels.append((a, k)))
    redemarrage.relancer()
    assert len(appels) == 1
    args, kwargs = appels[0]
    if sys.platform == "win32":
        assert "ping -n 3" in args[0] and "start" in args[0]
        assert kwargs["creationflags"]
    else:
        assert args[0][:2] == ["/bin/sh", "-c"]
        assert args[0][2].startswith("sleep 1; exec ")
        assert kwargs["start_new_session"] is True


def test_relancer_ne_leve_jamais(monkeypatch, caplog):
    """Au pire l'utilisateur relance à la main — jamais un crash à la fermeture."""
    import logging

    def _echec(*a, **k):
        raise OSError("spawn refusé")
    monkeypatch.setattr(redemarrage.subprocess, "Popen", _echec)
    with caplog.at_level(logging.ERROR, logger="debrief_meet.core.redemarrage"):
        redemarrage.relancer()      # ne doit pas lever
    assert "Relance impossible" in caplog.text
