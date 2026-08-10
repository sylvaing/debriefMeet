"""Tests du dialog de détail de l'événement BlueMind associé (lecture seule) —
ouvert par l'icône calendrier verte de l'Historique."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel

from debrief_meet.core.bluemind.association import Association, InviteAssocie
from debrief_meet.ui.bluemind_details import DialogDetailsBluemind
from debrief_meet.ui.theme import C


def _association(invites=None):
    return Association(
        event_uid="evt-1", cal_uid="calendar:Default:u1", titre="Point projet X",
        debut="2026-07-08T14:00:00+02:00",
        invites=invites if invites is not None else [
            InviteAssocie(nom="Sylvain Garcia", email="sylvain.garcia@bluemind.net",
                          part_status=None, organisateur=True, coche=True),
            InviteAssocie(nom="Jean Dupont", email="jean.dupont@example.com",
                          part_status="Accepted", organisateur=False, coche=True),
            InviteAssocie(nom="Marie Martin", email="marie.martin@example.com",
                          part_status="Declined", organisateur=False, coche=False),
        ],
    )


def _labels(dlg):
    return [lab.text() for lab in dlg.findChildren(QLabel)]


def _label(dlg, fragment):
    return next((lab for lab in dlg.findChildren(QLabel) if fragment in lab.text()), None)


def test_affiche_titre_et_date(qapp):
    dlg = DialogDetailsBluemind(_association())
    textes = _labels(dlg)
    assert any("Point projet X" in t for t in textes)
    assert any("08/07/2026 à 14:00" in t for t in textes)


def test_date_illisible_affichee_brute(qapp):
    asso = _association()
    asso.debut = "pas-une-date"
    dlg = DialogDetailsBluemind(asso)
    assert any("pas-une-date" in t for t in _labels(dlg))


def test_participants_avec_statut(qapp):
    dlg = DialogDetailsBluemind(_association())
    textes = _labels(dlg)
    assert any("Sylvain Garcia <sylvain.garcia@bluemind.net> — organisateur" in t for t in textes)
    assert any("Jean Dupont <jean.dupont@example.com> — accepté" in t for t in textes)


def test_participant_non_coche_grise_et_marque(qapp):
    """Un invité décoché à l'association (F1) apparaît en grisé + « non retenu »
    — les retenus restent en encre normale."""
    dlg = DialogDetailsBluemind(_association())
    retenu = _label(dlg, "Jean Dupont")
    ecarte = _label(dlg, "Marie Martin")
    assert "non retenu" not in retenu.text()
    assert "non retenu" in ecarte.text()
    assert C.INK900 in retenu.styleSheet()
    assert C.INK400 in ecarte.styleSheet()


def test_sans_invites_message_dedie(qapp):
    dlg = DialogDetailsBluemind(_association(invites=[]))
    assert any("Aucun participant" in t for t in _labels(dlg))


def test_lecture_seule_bouton_fermer(qapp):
    dlg = DialogDetailsBluemind(_association())
    assert dlg.bouton_action().text() == "Fermer"
    assert dlg.bouton_annuler().isHidden()
