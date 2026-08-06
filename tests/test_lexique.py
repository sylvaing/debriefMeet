"""Tests unitaires — lexique de corrections (core/lexique.py, docs/46)."""
from __future__ import annotations

from debrief_meet.core import lexique


# ── corrections_par_defaut() ─────────────────────────────────────────────────────

def test_corrections_par_defaut_lignes_completes():
    defauts = lexique.corrections_par_defaut()
    assert defauts, "tableau par défaut non vide (docs/46 §7)"
    for c in defauts:
        assert c["entendu"].strip() and c["ecrire"].strip()


def test_corrections_par_defaut_renvoie_une_copie_fraiche():
    a = lexique.corrections_par_defaut()
    a[0]["ecrire"] = "modifié"
    b = lexique.corrections_par_defaut()
    assert b[0]["ecrire"] != "modifié"           # pas de partage d'état


# ── bloc_instructions() ──────────────────────────────────────────────────────────

def test_bloc_rendu_variantes_multiples():
    bloc = lexique.bloc_instructions([])
    assert "- « barat », « bara » → Acme" in bloc


def test_bloc_contient_chapeau_et_garde_fou():
    bloc = lexique.bloc_instructions([{"entendu": "Mappy", "ecrire": "MAPI"}])
    assert bloc.startswith("Corrections de transcription :")
    assert "uniquement si une variante « entendu »" in bloc   # pas de correction hors transcription
    assert "n'introduis jamais" in bloc          # la liste n'est pas une liste de participants
    assert "« (à confirmer) »" in bloc           # garde-fou anti-invention (docs/46 §4)


def test_bloc_preserve_l_ordre_du_tableau():
    bloc = lexique.bloc_instructions([
        {"entendu": "afida", "ecrire": "Acme"},
        {"entendu": "Mappy", "ecrire": "MAPI"},
    ])
    assert bloc.index("Acme") < bloc.index("MAPI")


def test_bloc_ignore_les_lignes_incompletes():
    bloc = lexique.bloc_instructions([
        {"entendu": "Mappy", "ecrire": "MAPI"},
        {"entendu": "en cours de saisie", "ecrire": ""},
        {"entendu": "", "ecrire": "orphelin"},
        {"entendu": " , , ", "ecrire": "que-des-virgules"},
        {},
    ])
    assert "→ MAPI" in bloc
    assert "orphelin" not in bloc and "que-des-virgules" not in bloc
    assert bloc.count("\n- ") == 1               # une seule ligne exploitable


def test_bloc_none_si_rien_d_exploitable():
    assert lexique.bloc_instructions([]) is None
    assert lexique.bloc_instructions(None) is None
    assert lexique.bloc_instructions([{"entendu": "x", "ecrire": ""}]) is None


# ── completer_prompt() ───────────────────────────────────────────────────────────

def test_completer_prompt_sans_annonce_bloc_en_tete(config_tmp):
    # Prompt sans ligne d'annonce → bloc en TÊTE : jamais en fin de prompt, où il
    # serait au contact direct de la transcription concaténée derrière.
    out = lexique.completer_prompt("Fais un CR.", config_tmp)   # défauts : actif + tableau
    assert out.startswith("Corrections de transcription :")
    assert out.endswith("\n\nFais un CR.")
    assert "BlueMind" in out


def test_completer_prompt_insere_avant_l_annonce_de_transcription(config_tmp):
    # Injecté après « Voici la transcription : », le bloc serait lu comme faisant
    # partie de la transcription — ses noms propres deviennent des participants.
    prompt = "Fais un CR.\n\nVoici la transcription :"
    out = lexique.completer_prompt(prompt, config_tmp)
    assert out.startswith("Fais un CR.\n\nCorrections de transcription :")
    assert out.endswith("\n\nVoici la transcription :")


def test_completer_prompt_annonce_suivie_d_un_separateur(config_tmp):
    # CR simple : l'annonce est suivie de « --- » — le bloc reste avant l'annonce.
    prompt = "Fais un CR.\n\nVoici la transcription :\n---"
    out = lexique.completer_prompt(prompt, config_tmp)
    assert out.endswith("\n\nVoici la transcription :\n---")
    assert "Corrections de transcription :" in out


def test_completer_prompt_defauts_bloc_avant_l_annonce(config_tmp):
    # Les 3 prompts par défaut se terminent tous par la ligne d'annonce.
    from debrief_meet.core import prompts as prompts_mod
    for p in prompts_mod.prompts_par_defaut():
        out = lexique.completer_prompt(p["contenu"], config_tmp)
        assert out.rindex("Corrections de transcription :") \
            < out.rindex("Voici la transcription"), p["titre"]


def test_completer_prompt_inactif_identite(config_tmp):
    config_tmp.set("lexique_actif", False)
    prompt = "Fais un CR.   "                     # espaces conservés : identité stricte
    assert lexique.completer_prompt(prompt, config_tmp) is prompt


def test_completer_prompt_tableau_vide_identite(config_tmp):
    config_tmp.set("lexique_corrections", [])
    prompt = "Fais un CR."
    assert lexique.completer_prompt(prompt, config_tmp) is prompt


# ── termes_biais() ───────────────────────────────────────────────────────────────

def test_termes_biais_retire_les_parentheses():
    termes = lexique.termes_biais([
        {"entendu": "Maza", "ecrire": "ACME (société fictive)"},
        {"entendu": "Mappy", "ecrire": "MAPI"},
    ])
    assert termes == ["MASA", "MAPI"]


def test_termes_biais_filtre_les_lignes_incompletes():
    termes = lexique.termes_biais([
        {"entendu": "", "ecrire": "ignoré"},
        {"entendu": "Mappy", "ecrire": "MAPI"},
        {"entendu": "vide", "ecrire": "(que des parenthèses)"},
    ])
    assert termes == ["MAPI"]


def test_termes_biais_defaut_sans_espace_ni_virgule():
    """Voxtral (comma_separated) refuse espaces et virgules (code 3051) — les termes
    par défaut doivent être des jetons valides une fois les parenthèses retirées."""
    for terme in lexique.termes_biais(lexique.corrections_par_defaut()):
        assert " " not in terme and "," not in terme
