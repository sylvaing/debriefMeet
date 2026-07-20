from __future__ import annotations

from debrief_meet.core.bluemind import association
from debrief_meet.core.bluemind.association import Association, InviteAssocie, ecrire
from debrief_meet.ui.bluemind_mapping import DialogMappingLocuteurs

_LOCUTEURS_MD = """# Réunion — locuteurs

---

**Moi** [00:05] Bonjour à tous, on commence la réunion projet, je vais détailler l'ordre du jour au complet.

**Présent 1** [00:12] Merci.
"""


def _fichiers(tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    loc = tmp_path / "2026-07-08_14-00_locuteurs.md"
    md.write_text("# Réunion\n", encoding="utf-8")
    loc.write_text(_LOCUTEURS_MD, encoding="utf-8")
    return md, loc


def test_sans_sidecar_saisie_libre_seule(qapp, tmp_path):
    md, loc = _fichiers(tmp_path)
    dlg = DialogMappingLocuteurs(md, loc)
    assert len(dlg._combos) == 2
    for combo in dlg._combos.values():
        assert combo.isEditable()


def test_avec_sidecar_suggestions_preremplies(qapp, tmp_path):
    md, loc = _fichiers(tmp_path)
    ecrire(md, Association(
        event_uid="e1", cal_uid="cal", titre="Point projet X", debut="2026-07-08T14:00:00",
        invites=[
            InviteAssocie(nom="Sylvain Garcia", email="s@ex.com", part_status=None,
                          organisateur=True, coche=True),
            InviteAssocie(nom="Jean Dupont", email="jean@ex.com", part_status="Accepted",
                          organisateur=False, coche=True),
        ],
    ))
    dlg = DialogMappingLocuteurs(md, loc, email_moi="s@ex.com")
    assert dlg._combos["Moi"].currentText() == "Sylvain Garcia"
    assert dlg._combos["Présent 1"].currentText() == "Jean Dupont"


def test_validation_renomme_et_sauve_mapping(qapp, tmp_path):
    md, loc = _fichiers(tmp_path)
    ecrire(md, Association(event_uid="e1", cal_uid="cal", titre="X", debut="d", invites=[]))
    dlg = DialogMappingLocuteurs(md, loc, email_moi="s@ex.com")
    dlg._combos["Moi"].setCurrentText("Sylvain Garcia")
    dlg._combos["Présent 1"].setCurrentText("Jean Dupont")
    dlg._valider()

    texte = loc.read_text(encoding="utf-8")
    assert "**Sylvain Garcia**" in texte
    assert "**Jean Dupont**" in texte

    asso = association.lire(md)
    assert asso.mapping == {"Moi": "Sylvain Garcia", "Présent 1": "Jean Dupont"}


def test_champ_vide_exclu_du_mapping(qapp, tmp_path):
    md, loc = _fichiers(tmp_path)
    ecrire(md, Association(event_uid="e1", cal_uid="cal", titre="X", debut="d", invites=[]))
    dlg = DialogMappingLocuteurs(md, loc, email_moi="s@ex.com")
    dlg._combos["Moi"].setCurrentText("Sylvain Garcia")
    dlg._combos["Présent 1"].setCurrentText("")
    dlg._valider()
    asso = association.lire(md)
    assert asso.mapping == {"Moi": "Sylvain Garcia"}
    assert "Présent 1" in loc.read_text(encoding="utf-8")  # non renommé


def test_aucun_locuteur_detecte(qapp, tmp_path):
    md = tmp_path / "r.md"
    loc = tmp_path / "r_locuteurs.md"
    md.write_text("# X\n", encoding="utf-8")
    loc.write_text("# X\n\nPas de tour de parole détectable.\n", encoding="utf-8")
    dlg = DialogMappingLocuteurs(md, loc)
    assert dlg._combos == {}
