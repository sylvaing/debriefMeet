"""Tests unitaires — lister_enregistrements + FenetreHistorique (logique)."""
from __future__ import annotations

from pathlib import Path

import pytest

from debrief_meet.core.fichiers import lister_enregistrements


def test_dossier_absent_retourne_liste_vide(tmp_path):
    assert lister_enregistrements(tmp_path / "absent") == []


def test_dossier_vide_retourne_liste_vide(tmp_path):
    assert lister_enregistrements(tmp_path) == []


def test_liste_fichiers_md(tmp_path):
    (tmp_path / "2026-05-01.md").write_text("a")
    (tmp_path / "2026-05-03.md").write_text("b")
    (tmp_path / "2026-05-02.md").write_text("c")
    (tmp_path / "note.txt").write_text("ignoré")
    result = lister_enregistrements(tmp_path)
    noms = [f.name for f in result]
    assert "note.txt" not in noms
    assert noms == ["2026-05-03.md", "2026-05-02.md", "2026-05-01.md"]


def test_tri_decroissant(tmp_path):
    noms = ["2026-01-01.md", "2026-06-15.md", "2025-12-31.md"]
    for n in noms:
        (tmp_path / n).write_text("")
    result = lister_enregistrements(tmp_path)
    assert [f.name for f in result] == sorted(noms, reverse=True)


def test_supprimer_fichier(tmp_path):
    f = tmp_path / "2026-05-01.md"
    f.write_text("contenu")
    assert f.exists()
    f.unlink()
    assert not f.exists()
    assert lister_enregistrements(tmp_path) == []
