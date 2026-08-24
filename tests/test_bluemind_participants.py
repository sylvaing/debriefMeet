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
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTexte existant\n", encoding="utf-8")
    bloc = construire_bloc("X", "d", _INVITES)
    inserer_dans_fichier(md, bloc)
    texte = md.read_text(encoding="utf-8")
    assert texte.startswith("# Réunion — 2026-07-08 14:00\n\n" + MARQUEUR_DEBUT)
    assert "Texte existant" in texte


def test_insertion_idempotente_deux_validations_un_seul_bloc(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Réunion\n\nContenu\n", encoding="utf-8")
    bloc = construire_bloc("X", "d", _INVITES)
    inserer_dans_fichier(md, bloc)
    inserer_dans_fichier(md, bloc)
    texte = md.read_text(encoding="utf-8")
    assert texte.count(MARQUEUR_DEBUT) == 1
    assert texte.count(MARQUEUR_FIN) == 1
    assert texte.count("Contenu") == 1


def test_revalidation_remplace_le_contenu(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Réunion\n\nContenu\n", encoding="utf-8")
    inserer_dans_fichier(md, construire_bloc("X", "d", _INVITES[:1]))
    inserer_dans_fichier(md, construire_bloc("X", "d", _INVITES))
    texte = md.read_text(encoding="utf-8")
    assert texte.count(MARQUEUR_DEBUT) == 1
    assert "Jean Dupont" in texte


def test_fichier_absent_ne_leve_pas(tmp_path):
    inserer_dans_fichier(tmp_path / "absent.md", construire_bloc("X", "d", _INVITES))  # no-op


def test_sans_h1_insere_en_tete(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("Contenu sans titre\n", encoding="utf-8")
    inserer_dans_fichier(md, construire_bloc("X", "d", _INVITES))
    texte = md.read_text(encoding="utf-8")
    assert texte.startswith(MARQUEUR_DEBUT)
    assert "Contenu sans titre" in texte


def test_inserer_pour_reunion_insere_dans_les_deux_fichiers(tmp_path):
    md = tmp_path / "transcription.md"
    loc = tmp_path / "locuteurs.md"
    md.write_text("# Réunion\n\nTranscription\n", encoding="utf-8")
    loc.write_text("# Locuteurs\n\nSPEAKER_00: bonjour\n", encoding="utf-8")
    inserer_pour_reunion(md, "Point projet X", "2026-07-08 14:00", _INVITES)
    assert MARQUEUR_DEBUT in md.read_text(encoding="utf-8")
    assert MARQUEUR_DEBUT in loc.read_text(encoding="utf-8")


def test_inserer_pour_reunion_sans_locuteurs_ne_le_cree_pas(tmp_path):
    md = tmp_path / "transcription.md"
    md.write_text("# Réunion\n\nTranscription\n", encoding="utf-8")
    inserer_pour_reunion(md, "X", "d", _INVITES)
    assert not (tmp_path / "locuteurs.md").exists()


# ── reinserer_depuis_sidecar — point d'entrée partagé (2026-08-24) ────────────

def _sidecar(md, *, coche=True, titre="point commerce Alix"):
    from debrief_meet.core.bluemind.association import Association, InviteAssocie, ecrire
    ecrire(md, Association(
        event_uid="e1", cal_uid="cal", titre=titre, debut="2026-08-24T10:00:00+02:00",
        invites=[InviteAssocie(nom="Alix Morel", email="alix.morel@exemple.fr",
                               part_status="Accepted", organisateur=False, coche=coche)],
    ))


def test_reinserer_depuis_sidecar_ecrit_le_cartouche(tmp_path):
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT, reinserer_depuis_sidecar

    md = tmp_path / "transcription.md"
    md.write_text("# point commerce Alix\n\n**Moi :** bonjour\n", encoding="utf-8")
    _sidecar(md)

    assert reinserer_depuis_sidecar(md) is True
    texte = md.read_text(encoding="utf-8")
    assert MARQUEUR_DEBUT in texte
    assert "Alix Morel" in texte


def test_reinserer_depuis_sidecar_sans_association(tmp_path):
    from debrief_meet.core.bluemind.participants import reinserer_depuis_sidecar

    md = tmp_path / "transcription.md"
    md.write_text("# Sans association\n", encoding="utf-8")

    assert reinserer_depuis_sidecar(md) is False
    assert md.read_text(encoding="utf-8") == "# Sans association\n"


def test_reinserer_depuis_sidecar_aucun_invite_coche(tmp_path):
    """Un cartouche sans aucun nom n'apprendrait rien : on n'écrit pas."""
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT, reinserer_depuis_sidecar

    md = tmp_path / "transcription.md"
    md.write_text("# X\n", encoding="utf-8")
    _sidecar(md, coche=False)

    assert reinserer_depuis_sidecar(md) is False
    assert MARQUEUR_DEBUT not in md.read_text(encoding="utf-8")


def test_reinserer_depuis_sidecar_cible_un_seul_fichier(tmp_path):
    """`cible` sert la diarization : le bloc va dans locuteurs.md, pas dans le .md."""
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT, reinserer_depuis_sidecar
    from debrief_meet.core.fichiers import chemin_locuteurs

    md = tmp_path / "transcription.md"
    md.write_text("# X\n", encoding="utf-8")
    loc = chemin_locuteurs(md)
    loc.write_text("# X\n\nSPEAKER_00: bonjour\n", encoding="utf-8")
    _sidecar(md)

    assert reinserer_depuis_sidecar(md, cible=loc) is True
    assert MARQUEUR_DEBUT in loc.read_text(encoding="utf-8")
    assert MARQUEUR_DEBUT not in md.read_text(encoding="utf-8")


def test_reinserer_depuis_sidecar_idempotent(tmp_path):
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT, reinserer_depuis_sidecar

    md = tmp_path / "transcription.md"
    md.write_text("# X\n\ncorps\n", encoding="utf-8")
    _sidecar(md)

    reinserer_depuis_sidecar(md)
    reinserer_depuis_sidecar(md)

    assert md.read_text(encoding="utf-8").count(MARQUEUR_DEBUT) == 1


def test_titre_courant_du_md_prime_sur_le_sidecar(tmp_path):
    """Un titre édité à la main depuis l'association doit gagner."""
    from debrief_meet.core.bluemind.participants import reinserer_depuis_sidecar

    md = tmp_path / "transcription.md"
    md.write_text("# Titre corrige a la main\n\ncorps\n", encoding="utf-8")
    _sidecar(md, titre="ancien titre calendrier")

    reinserer_depuis_sidecar(md)

    assert "« Titre corrige a la main »" in md.read_text(encoding="utf-8")


def test_debut_lisible_repli_sur_valeur_brute():
    from debrief_meet.core.bluemind.participants import debut_lisible

    assert debut_lisible("2026-08-24T10:00:00+02:00") == "2026-08-24 10:00"
    assert debut_lisible("pas une date") == "pas une date"
    assert debut_lisible(None) == ""
