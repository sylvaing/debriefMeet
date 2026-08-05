"""Tests unitaires — prompts de copie (core/prompts.py)."""
from __future__ import annotations

from debrief_meet.core import prompts


def test_prompts_par_defaut_contient_cr_simple():
    defauts = prompts.prompts_par_defaut()
    assert len(defauts) == 3
    assert [p["titre"] for p in defauts] == ["CR simple", "CR Pipedrive", "CR full .md"]
    for prompt in defauts:
        assert "transcription" in prompt["contenu"].lower()


def test_cr_pipedrive_et_full_md_ne_different_que_par_la_sortie():
    pipedrive, full_md = prompts.CR_PIPEDRIVE_CONTENU, prompts.CR_FULL_MD_CONTENU
    assert "note Pipedrive" in pipedrive and "<b>" in pipedrive
    assert "fichier markdown" in full_md and "<b>" not in full_md.split("5. Format de sortie")[1]
    # corps commun identique (tout ce qui précède la section 5)
    assert pipedrive.split("\n\n5. Format de sortie")[0].split("\n\n", 1)[1] \
        == full_md.split("\n\n5. Format de sortie")[0].split("\n\n", 1)[1]


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
