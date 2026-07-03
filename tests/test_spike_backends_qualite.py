"""Tests de fumée — qualite.py du spike backends Windows."""
from __future__ import annotations

import pytest

from spike.backends_windows import qualite


def test_normaliser():
    assert qualite.normaliser("Élève, ça va ?!") == ["eleve", "ca", "va"]
    assert qualite.normaliser("") == []
    assert qualite.normaliser("   ") == []


def test_wer_identique():
    assert qualite.wer("le chat dort", "le chat dort") == 0.0
    assert qualite.wer("Le Chat Dort.", "le chat dort") == 0.0


def test_wer_substitution():
    assert qualite.wer("le chat dort", "le chien dort") == pytest.approx(1 / 3)


def test_wer_bords():
    assert qualite.wer("", "") == 0.0
    assert qualite.wer("", "quelque chose") == 1.0
    assert qualite.wer("quelque chose", "") == 1.0


def test_ratio_repetition_normal():
    texte = "Bonjour je suis content de vous voir aujourd'hui"
    ratio = qualite.calculer_ratio_repetition(texte)
    assert ratio < qualite.SEUIL_REPETITION


def test_ratio_repetition_hallucination():
    phrase = "je vous remercie de votre attention "
    texte = phrase * 30  # hallucination en boucle
    ratio = qualite.calculer_ratio_repetition(texte)
    # Avec la métrique 1 - diversité, la répétition donne un ratio élevé (proche de 1)
    assert ratio > qualite.SEUIL_REPETITION


def test_detecter_hallucination_boucle():
    phrase = "merci de votre confiance "
    assert qualite.detecter_hallucination(phrase * 20) is True


def test_detecter_hallucination_texte_normal():
    texte = ("Le président a annoncé de nouvelles mesures économiques lors de sa conférence "
             "de presse. Il a souligné l'importance de la coopération internationale. "
             "Les marchés ont réagi positivement à cette annonce inattendue.")
    assert qualite.detecter_hallucination(texte) is False


def test_appliquer_wer_relatif_reference_large():
    resultats = [
        {"backend": "test", "modele": "small", "_texte": "le chat"},
        {"backend": "test", "modele": "large-v3", "_texte": "le chat dort"},
    ]
    qualite.appliquer_wer_relatif(resultats)
    # large-v3 est référence → wer=0 pour lui-même
    r_lv3 = next(r for r in resultats if r["modele"] == "large-v3")
    r_sm = next(r for r in resultats if r["modele"] == "small")
    assert r_lv3["wer"] == 0.0
    assert r_sm["wer"] > 0.0
    assert r_sm["wer_reference"] == "large-v3"
    # la clé interne est supprimée
    assert "_texte" not in r_lv3
    assert "_texte" not in r_sm


def test_appliquer_wer_relatif_sans_texte():
    resultats = [
        {"backend": "test", "modele": "small", "statut": "erreur", "erreur": "OOM"},
    ]
    qualite.appliquer_wer_relatif(resultats)  # ne doit pas lever
    assert "wer" not in resultats[0]
