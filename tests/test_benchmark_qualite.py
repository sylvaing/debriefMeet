from __future__ import annotations

import pytest

from benchmark import qualite


def test_normaliser_accents_ponctuation_casse():
    assert qualite.normaliser("Élève, ça va ?!") == ["eleve", "ca", "va"]
    assert qualite.normaliser("") == []
    assert qualite.normaliser("   ") == []


def test_wer_identique_est_zero():
    assert qualite.wer("le chat dort", "le chat dort") == 0.0
    # insensible à la casse et la ponctuation
    assert qualite.wer("Le chat dort.", "le chat dort") == 0.0


def test_wer_une_substitution_sur_trois():
    assert qualite.wer("le chat dort", "le chien dort") == pytest.approx(1 / 3)


def test_wer_insertion_et_suppression():
    assert qualite.wer("le chat", "le gros chat") == pytest.approx(1 / 2)  # 1 insertion / 2 mots
    assert qualite.wer("le gros chat", "le chat") == pytest.approx(1 / 3)  # 1 suppression / 3 mots


def test_wer_bords():
    assert qualite.wer("", "") == 0.0
    assert qualite.wer("", "quelque chose") == 1.0
    assert qualite.wer("quelque chose", "") == 1.0


def test_metriques_structure():
    m = qualite.metriques("le chat dort", "le chien dort")
    assert m["n_mots_reference"] == 3
    assert m["n_mots_hypothese"] == 3
    assert 0 < m["wer"] <= 1
