from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QDialogButtonBox

from debrief_meet.core.bluemind import association
from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT
from debrief_meet.core.bluemind.store import Evenement
from debrief_meet.ui.bluemind_association import DialogAssociationBluemind


def _evt(uid="evt-1", titre="Point projet X", debut=None, invites=None, organisateur=None):
    debut = debut or datetime(2026, 7, 8, 14, 0)
    return Evenement(
        uid=uid, cal_uid="calendar:Default:u1",
        debut_ms=int(debut.timestamp() * 1000), fin_ms=int(debut.timestamp() * 1000) + 3600_000,
        journee_entiere=False, titre=titre, lieu="",
        organisateur=organisateur if organisateur is not None else
            {"nom": "Sylvain Garcia", "email": "sylvain.garcia@bluemind.net", "part_status": None},
        invites=invites if invites is not None else [
            {"nom": "Jean Dupont", "email": "jean.dupont@example.com", "part_status": "Accepted"},
            {"nom": "Marie Martin", "email": "marie.martin@example.com", "part_status": "Declined"},
        ],
    )


def test_un_seul_evenement_va_direct_au_recap(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTexte\n")
    dlg = DialogAssociationBluemind(md, [_evt()])
    assert dlg._page_choix is None
    assert dlg._evenement_choisi is not None
    assert len(dlg._checks_invites) == 3  # organisateur + 2 invités


def test_plusieurs_evenements_affiche_le_choix(qapp, tmp_path):
    md = tmp_path / "r.md"
    md.write_text("# Réunion\n")
    e1, e2 = _evt(uid="e1"), _evt(uid="e2", titre="Autre réunion")
    dlg = DialogAssociationBluemind(md, [e1, e2])
    assert dlg._page_choix is not None
    assert dlg._evenement_choisi is None
    assert dlg._boutons.button(QDialogButtonBox.StandardButton.Ok).isEnabled() is False

    dlg._liste_choix.setCurrentRow(1)
    assert dlg._evenement_choisi is e2
    assert dlg._boutons.button(QDialogButtonBox.StandardButton.Ok).isEnabled() is True


def test_validation_ecrit_le_sidecar(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTranscription\n")
    dlg = DialogAssociationBluemind(md, [_evt()])
    dlg._valider()

    asso = association.lire(md)
    assert asso is not None
    assert asso.event_uid == "evt-1"
    assert len(asso.invites) == 3
    assert all(i.coche for i in asso.invites)


def test_validation_insere_bloc_invites(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTranscription\n")
    dlg = DialogAssociationBluemind(md, [_evt()])
    dlg._valider()
    assert MARQUEUR_DEBUT in md.read_text(encoding="utf-8")


def test_decocher_un_invite_lexclut_du_bloc(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTranscription\n")
    dlg = DialogAssociationBluemind(md, [_evt()])
    for check, p in dlg._checks_invites:
        if p.get("email") == "marie.martin@example.com":
            check.setChecked(False)
    dlg._valider()
    texte = md.read_text(encoding="utf-8")
    assert "Jean Dupont" in texte
    assert "Marie Martin" not in texte
    asso = association.lire(md)
    marie = [i for i in asso.invites if i.email == "marie.martin@example.com"][0]
    assert marie.coche is False


def test_titre_par_defaut_propose_application_si_titre_vide(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTexte\n")  # titre par défaut = date
    dlg = DialogAssociationBluemind(md, [_evt(titre="Point projet X")])
    assert dlg._check_titre.isChecked() is True
    dlg._valider()
    assert "# Point projet X" in md.read_text(encoding="utf-8")


def test_titre_custom_non_ecrase_si_decoche(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Mon titre perso\n\nTexte\n")
    dlg = DialogAssociationBluemind(md, [_evt(titre="Point projet X")])
    assert dlg._check_titre.isChecked() is False  # titre déjà custom -> pas coché par défaut
    dlg._valider()
    assert "# Mon titre perso" in md.read_text(encoding="utf-8")
