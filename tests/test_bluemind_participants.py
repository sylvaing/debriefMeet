from __future__ import annotations

from debrief_meet.core.bluemind.participants import (
    MARQUEUR_DEBUT,
    MARQUEUR_FIN,
    construire_bloc,
    inserer_dans_fichier,
    inserer_pour_reunion,
)

_INVITES = [
    {"nom": "Sylvain Garcia", "email": "sylvain.garcia@bluemind.net", "organisateur": True, "part_status": None},
    {"nom": "Jean Dupont", "email": "jean.dupont@example.com", "organisateur": False, "part_status": "Accepted"},
    {"nom": "Marie Martin", "email": "marie.martin@example.com", "organisateur": False, "part_status": "Declined"},
    {"nom": "Paul Durand", "email": "paul.durand@example.com", "organisateur": False, "part_status": "NeedsAction"},
]


def test_construire_bloc_entete_participants_potentiels():
    bloc = construire_bloc("Point projet X", "2026-07-08 14:00", _INVITES)
    assert "participants potentiels" in bloc
    assert "ne vaut pas liste de présence" in bloc
    assert MARQUEUR_DEBUT in bloc and MARQUEUR_FIN in bloc


def test_construire_bloc_statuts_traduits():
    bloc = construire_bloc("X", "2026-07-08 14:00", _INVITES)
    assert "Sylvain Garcia <sylvain.garcia@bluemind.net> — organisateur" in bloc
    assert "Jean Dupont <jean.dupont@example.com> — accepté" in bloc
    assert "Marie Martin <marie.martin@example.com> — refusé" in bloc
    assert "Paul Durand <paul.durand@example.com> — sans réponse" in bloc


def test_organisateur_en_premier_si_fourni_en_premier():
    bloc = construire_bloc("X", "d", _INVITES)
    idx_organisateur = bloc.index("organisateur")
    idx_jean = bloc.index("Jean Dupont")
    assert idx_organisateur < idx_jean


def test_insertion_apres_h1(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTexte existant\n")
    bloc = construire_bloc("X", "d", _INVITES)
    inserer_dans_fichier(md, bloc)
    texte = md.read_text(encoding="utf-8")
    assert texte.startswith("# Réunion — 2026-07-08 14:00\n\n" + MARQUEUR_DEBUT)
    assert "Texte existant" in texte


def test_insertion_idempotente_deux_validations_un_seul_bloc(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Réunion\n\nContenu\n")
    bloc = construire_bloc("X", "d", _INVITES)
    inserer_dans_fichier(md, bloc)
    inserer_dans_fichier(md, bloc)
    texte = md.read_text(encoding="utf-8")
    assert texte.count(MARQUEUR_DEBUT) == 1
    assert texte.count(MARQUEUR_FIN) == 1
    assert texte.count("Contenu") == 1


def test_revalidation_remplace_le_contenu(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Réunion\n\nContenu\n")
    inserer_dans_fichier(md, construire_bloc("X", "d", _INVITES[:1]))
    inserer_dans_fichier(md, construire_bloc("X", "d", _INVITES))
    texte = md.read_text(encoding="utf-8")
    assert texte.count(MARQUEUR_DEBUT) == 1
    assert "Jean Dupont" in texte


def test_fichier_absent_ne_leve_pas(tmp_path):
    inserer_dans_fichier(tmp_path / "absent.md", construire_bloc("X", "d", _INVITES))  # no-op


def test_sans_h1_insere_en_tete(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("Contenu sans titre\n")
    inserer_dans_fichier(md, construire_bloc("X", "d", _INVITES))
    texte = md.read_text(encoding="utf-8")
    assert texte.startswith(MARQUEUR_DEBUT)
    assert "Contenu sans titre" in texte


def test_inserer_pour_reunion_insere_dans_les_deux_fichiers(tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    loc = tmp_path / "2026-07-08_14-00_locuteurs.md"
    md.write_text("# Réunion\n\nTranscription\n")
    loc.write_text("# Locuteurs\n\nSPEAKER_00: bonjour\n")
    inserer_pour_reunion(md, "Point projet X", "2026-07-08 14:00", _INVITES)
    assert MARQUEUR_DEBUT in md.read_text(encoding="utf-8")
    assert MARQUEUR_DEBUT in loc.read_text(encoding="utf-8")


def test_inserer_pour_reunion_sans_locuteurs_ne_le_cree_pas(tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion\n\nTranscription\n")
    inserer_pour_reunion(md, "X", "d", _INVITES)
    assert not (tmp_path / "2026-07-08_14-00_locuteurs.md").exists()
