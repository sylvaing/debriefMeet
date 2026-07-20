"""Tests de debrief_meet.core.ressources — résolution dev vs bundle figé."""
from __future__ import annotations

import sys
from pathlib import Path

from debrief_meet.core import ressources


def test_est_figee_false_en_dev():
    # En dev, sys.frozen est absent.
    assert ressources.est_figee() is False


def test_chemin_ressource_pointe_la_racine_du_depot_en_dev():
    # En dev, la racine = dépôt. Sur Mac on sonde le helper Swift (l'invariant qui
    # compte pour la capture SCK) ; ailleurs (VM Windows : helpers/ non synchronisé)
    # on sonde pyproject.toml, présent sur toute copie de travail.
    if sys.platform == "darwin":
        sonde = ressources.chemin_ressource("helpers", "macos", "sck-audio", "SCKAudioCapture.swift")
    else:
        sonde = ressources.chemin_ressource("pyproject.toml")
    assert sonde.exists(), f"Sonde racine introuvable : {sonde}"


def test_chemin_ressource_utilise_meipass_si_figee(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    p = ressources.chemin_ressource("helpers", "x")
    assert p == Path(tmp_path) / "helpers" / "x"
    assert ressources.est_figee() is True


def test_chemin_ressource_repli_dossier_binaire_si_meipass_absent(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    p = ressources.chemin_ressource("z")
    assert p == Path(sys.executable).parent / "z"
