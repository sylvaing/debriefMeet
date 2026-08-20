from __future__ import annotations

from datetime import datetime

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


def _bouton(dlg, label):
    """Bouton du pied portant ce libellé, ou None (les boutons secondaires ne sont pas
    exposés par une propriété dédiée)."""
    from PySide6.QtWidgets import QPushButton
    return next((b for b in dlg.findChildren(QPushButton) if b.text() == label), None)


def _md(tmp_path, nom="2026-07-08_14-00-00", texte="# Réunion — 2026-07-08 14:00\n\nTexte\n"):
    dossier = tmp_path / nom
    dossier.mkdir()
    md = dossier / "transcription.md"
    md.write_text(texte, encoding="utf-8")
    return md


def test_un_seul_evenement_va_direct_au_recap(qapp, tmp_path):
    md = _md(tmp_path)
    dlg = DialogAssociationBluemind(md, [_evt()])
    assert dlg._page_choix is None
    assert dlg._evenement_choisi is not None
    assert len(dlg._checks_invites) == 3  # organisateur + 2 invités


def test_plusieurs_evenements_affiche_le_choix(qapp, tmp_path):
    md = _md(tmp_path, nom="r", texte="# Réunion\n")
    e1, e2 = _evt(uid="e1"), _evt(uid="e2", titre="Autre réunion")
    dlg = DialogAssociationBluemind(md, [e1, e2])
    assert dlg._page_choix is not None
    assert dlg._evenement_choisi is None
    assert dlg.bouton_action().isEnabled() is False

    dlg._liste_choix.setCurrentRow(1)
    assert dlg._evenement_choisi is e2
    assert dlg.bouton_action().isEnabled() is True


def test_validation_ecrit_le_sidecar(qapp, tmp_path):
    md = _md(tmp_path, texte="# Réunion — 2026-07-08 14:00\n\nTranscription\n")
    dlg = DialogAssociationBluemind(md, [_evt()])
    dlg._valider()

    # Le dossier a été renommé (titre appliqué, docs/43 §6.1) — relire via la
    # propriété mise à jour du dialog, pas via `md` (chemin devenu périmé).
    asso = association.lire(dlg.chemin_md)
    assert asso is not None
    assert asso.event_uid == "evt-1"
    assert len(asso.invites) == 3
    assert all(i.coche for i in asso.invites)


def test_validation_insere_bloc_invites(qapp, tmp_path):
    md = _md(tmp_path, texte="# Réunion — 2026-07-08 14:00\n\nTranscription\n")
    dlg = DialogAssociationBluemind(md, [_evt()])
    dlg._valider()
    assert MARQUEUR_DEBUT in dlg.chemin_md.read_text(encoding="utf-8")


def test_decocher_un_invite_lexclut_du_bloc(qapp, tmp_path):
    md = _md(tmp_path, texte="# Réunion — 2026-07-08 14:00\n\nTranscription\n")
    dlg = DialogAssociationBluemind(md, [_evt()])
    for check, p in dlg._checks_invites:
        if p.get("email") == "marie.martin@example.com":
            check.setChecked(False)
    dlg._valider()
    texte = dlg.chemin_md.read_text(encoding="utf-8")
    assert "Jean Dupont" in texte
    assert "Marie Martin" not in texte
    asso = association.lire(dlg.chemin_md)
    marie = [i for i in asso.invites if i.email == "marie.martin@example.com"][0]
    assert marie.coche is False


def test_titre_par_defaut_propose_application_si_titre_vide(qapp, tmp_path):
    md = _md(tmp_path)  # titre par défaut = date
    dlg = DialogAssociationBluemind(md, [_evt(titre="Point projet X")])
    assert dlg._check_titre.isChecked() is True
    dlg._valider()
    assert "# Point projet X" in dlg.chemin_md.read_text(encoding="utf-8")
    assert dlg.chemin_md.parent.name == "2026-07-08_14-00-00_Point-projet-X"


def test_titre_custom_non_ecrase_si_decoche(qapp, tmp_path):
    md = _md(tmp_path, texte="# Mon titre perso\n\nTexte\n")
    dlg = DialogAssociationBluemind(md, [_evt(titre="Point projet X")])
    assert dlg._check_titre.isChecked() is False  # titre déjà custom -> pas coché par défaut
    dlg._valider()
    assert "# Mon titre perso" in dlg.chemin_md.read_text(encoding="utf-8")
    assert dlg.chemin_md == md   # pas de renommage (titre non appliqué)


# ── Variante « avant le CR » : 3ᵉ sortie « Sans association » (docs/42) ─────────

def test_sans_contexte_cr_pas_de_troisieme_bouton(qapp, tmp_path):
    """Non-régression des deux appelants historiques (menu ⋯ et colonne calendrier)."""
    dlg = DialogAssociationBluemind(_md(tmp_path), [_evt()])
    assert dlg.association_ignoree is False
    assert _bouton(dlg, "Sans association") is None


def test_contexte_cr_ajoute_sans_association(qapp, tmp_path):
    md = _md(tmp_path)
    dlg = DialogAssociationBluemind(md, [_evt()], contexte_cr=True)
    bouton = _bouton(dlg, "Sans association")
    assert bouton is not None
    bouton.click()
    assert dlg.association_ignoree is True
    assert dlg.result() == dlg.DialogCode.Accepted
    assert association.lire(md) is None          # accepté MAIS rien écrit


def test_sans_association_actif_meme_sur_la_page_de_choix(qapp, tmp_path):
    """Avec plusieurs correspondances, « Associer » est désactivé faute de choix : ne pas
    choisir doit rester possible sans renoncer au CR."""
    md = _md(tmp_path, nom="r", texte="# Réunion\n")
    dlg = DialogAssociationBluemind(md, [_evt(uid="e1"), _evt(uid="e2")], contexte_cr=True)
    assert dlg.bouton_action().isEnabled() is False
    assert _bouton(dlg, "Sans association").isEnabled() is True


def test_contexte_cr_valide_normalement(qapp, tmp_path):
    """« Associer » garde exactement le même effet dans la variante CR."""
    md = _md(tmp_path)
    dlg = DialogAssociationBluemind(md, [_evt()], contexte_cr=True)
    dlg._valider()
    assert dlg.association_ignoree is False
    assert association.lire(dlg.chemin_md) is not None


# ── Seuil de pré-cochage + bascule « tout cocher / décocher » (docs/50) ─────────

def _invites(n: int, statut: str = "NeedsAction"):
    return [{"nom": f"Invité {i}", "email": f"invite{i}@example.com", "part_status": statut}
            for i in range(n)]


def _coches(dlg):
    return {p.get("email"): check.isChecked() for check, p in dlg._checks_invites}


def test_jusqu_au_seuil_tout_est_coche(qapp, tmp_path):
    """Cas nominal (réunion d'équipe) : comportement historique inchangé. Le décompte
    inclut l'organisateur — c'est le nombre de personnes affichées dans la liste."""
    dlg = DialogAssociationBluemind(_md(tmp_path), [_evt(invites=_invites(7))])
    assert len(dlg._checks_invites) == 8
    assert all(_coches(dlg).values())


def test_au_dela_du_seuil_seuls_organisateur_et_acceptes(qapp, tmp_path):
    """9 personnes : les « sans réponse » ne partent plus par défaut dans le CR — c'est
    ce qui faisait inventer des participants au modèle (docs/50 §3.5)."""
    invites = _invites(6) + [
        {"nom": "Oui", "email": "oui@example.com", "part_status": "Accepted"},
        {"nom": "Non", "email": "non@example.com", "part_status": "Declined"},
    ]
    dlg = DialogAssociationBluemind(_md(tmp_path), [_evt(invites=invites)])
    coches = _coches(dlg)
    assert len(coches) == 9
    assert coches["sylvain.garcia@bluemind.net"] is True     # organisateur
    assert coches["oui@example.com"] is True                 # accepté
    assert coches["non@example.com"] is False
    assert coches["invite0@example.com"] is False            # sans réponse


def test_mapping_des_statuts_fige(qapp, tmp_path):
    """La valeur brute du serveur qui vaut « présent » est figée ici : seul `Accepted`
    pré-coche. Un renommage côté BlueMind doit casser ce test, pas le CR."""
    invites = _invites(5) + [
        {"nom": "A", "email": "accepted@example.com", "part_status": "Accepted"},
        {"nom": "T", "email": "tentative@example.com", "part_status": "Tentative"},
        {"nom": "D", "email": "declined@example.com", "part_status": "Declined"},
        {"nom": "N", "email": "none@example.com", "part_status": None},
    ]
    coches = _coches(DialogAssociationBluemind(_md(tmp_path), [_evt(invites=invites)]))
    assert coches["accepted@example.com"] is True
    assert coches["tentative@example.com"] is False
    assert coches["declined@example.com"] is False
    assert coches["none@example.com"] is False


def test_bascule_tout_decocher_puis_tout_cocher(qapp, tmp_path):
    dlg = DialogAssociationBluemind(_md(tmp_path), [_evt()])   # 3 personnes, tout coché
    assert dlg._libelle_participants.text() == "PARTICIPANTS (3/3)"
    assert dlg._bouton_tout.text() == "Tout décocher"

    dlg._bouton_tout.click()
    assert not any(_coches(dlg).values())
    assert dlg._libelle_participants.text() == "PARTICIPANTS (0/3)"
    assert dlg._bouton_tout.text() == "Tout cocher"

    dlg._bouton_tout.click()
    assert all(_coches(dlg).values())
    assert dlg._libelle_participants.text() == "PARTICIPANTS (3/3)"


def test_compteur_suit_une_case_decochee_a_la_main(qapp, tmp_path):
    dlg = DialogAssociationBluemind(_md(tmp_path), [_evt()])
    dlg._checks_invites[1][0].setChecked(False)
    assert dlg._libelle_participants.text() == "PARTICIPANTS (2/3)"
    assert dlg._bouton_tout.text() == "Tout cocher"


def test_changer_d_evenement_ne_laisse_pas_d_entete_orpheline(qapp, tmp_path):
    """Le récapitulatif est reconstruit à chaque choix : sans vidage récursif du layout,
    le libellé et la bascule (dans un sous-layout) resteraient affichés en double."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QPushButton

    md = _md(tmp_path, nom="r", texte="# Réunion\n")
    dlg = DialogAssociationBluemind(md, [_evt(uid="e1"), _evt(uid="e2", titre="Autre")])
    dlg._liste_choix.setCurrentRow(0)
    dlg._liste_choix.setCurrentRow(1)
    # `processEvents()` ne traite PAS les DeferredDelete : sans cet envoi explicite, les
    # widgets détruits par `deleteLater` resteraient trouvables ici (l'app, elle, revient
    # à sa boucle principale et les purge).
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    bascules = [b for b in dlg._page_recap.findChildren(QPushButton)
                if b.text() in ("Tout cocher", "Tout décocher")]
    assert len(bascules) == 1
