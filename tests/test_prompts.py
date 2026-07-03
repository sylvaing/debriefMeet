"""Tests unitaires — prompts de copie (core/prompts.py)."""
from __future__ import annotations

from debrief_meet.core import prompts


def test_prompts_par_defaut_contient_cr_simple():
    defauts = prompts.prompts_par_defaut()
    assert len(defauts) == 1
    assert defauts[0]["titre"] == "CR simple"
    assert "transcription" in defauts[0]["contenu"].lower()


def test_prompts_par_defaut_renvoie_une_copie_fraiche():
    a = prompts.prompts_par_defaut()
    a[0]["titre"] = "modifié"
    b = prompts.prompts_par_defaut()
    assert b[0]["titre"] == "CR simple"      # pas de partage d'état


def test_prefixer_ajoute_le_contenu_en_tete():
    out = prompts.prefixer("Bonjour à tous.", "Fais un CR.")
    assert out == "Fais un CR.\n\nBonjour à tous."


def test_prefixer_normalise_les_espaces_de_fin():
    out = prompts.prefixer("texte", "prompt   \n\n  ")
    assert out == "prompt\n\ntexte"


def test_contenu_actif_index_valide():
    ps = [{"titre": "A", "contenu": "alpha"}, {"titre": "B", "contenu": "beta"}]
    assert prompts.contenu_actif(ps, 1) == "beta"


def test_contenu_actif_aucun_actif():
    ps = [{"titre": "A", "contenu": "alpha"}]
    assert prompts.contenu_actif(ps, None) is None


def test_contenu_actif_index_hors_borne():
    ps = [{"titre": "A", "contenu": "alpha"}]
    assert prompts.contenu_actif(ps, 5) is None
    assert prompts.contenu_actif(ps, -1) is None


def test_contenu_actif_contenu_vide_ignore():
    ps = [{"titre": "Vide", "contenu": "   "}]
    assert prompts.contenu_actif(ps, 0) is None


def test_contenu_actif_liste_vide():
    assert prompts.contenu_actif([], 0) is None
    assert prompts.contenu_actif(None, 0) is None
