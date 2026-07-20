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


# ── chemin_ffmpeg — embarqué d'abord, PATH en repli (docs/41) ──────────────────

def test_chemin_ffmpeg_priorite_embarque(monkeypatch, tmp_path):
    dossier = tmp_path / "ffmpeg"
    dossier.mkdir()
    nom = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    binaire = dossier / nom
    binaire.write_bytes(b"")
    monkeypatch.setattr(ressources, "_racine_ressources", lambda: tmp_path)

    assert ressources.chemin_ffmpeg() == str(binaire)


def test_chemin_ffmpeg_repli_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ressources, "_racine_ressources", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda nom: "/usr/fake/ffmpeg")

    assert ressources.chemin_ffmpeg() == "/usr/fake/ffmpeg"


def test_chemin_ffmpeg_absent_partout(monkeypatch, tmp_path):
    monkeypatch.setattr(ressources, "_racine_ressources", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda nom: None)

    assert ressources.chemin_ffmpeg() is None
