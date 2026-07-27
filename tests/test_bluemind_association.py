from __future__ import annotations

from debrief_meet.core.bluemind.association import (
    Association,
    InviteAssocie,
    associer_evenement,
    chemin_sidecar,
    construire_invites_depuis_evenement,
    ecrire,
    enregistrer_mapping,
    existe,
    lire,
)
from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT
from debrief_meet.core.bluemind.store import Evenement


def _asso(**kw):
    return Association(
        event_uid=kw.pop("event_uid", "evt-1"),
        cal_uid=kw.pop("cal_uid", "cal:Default:u1"),
        titre=kw.pop("titre", "Point projet X"),
        debut=kw.pop("debut", "2026-07-08T14:00:00+02:00"),
        invites=kw.pop("invites", [
            InviteAssocie(nom="Sylvain Garcia", email="sylvain@ex.com", part_status=None,
                          organisateur=True, coche=True),
            InviteAssocie(nom="Jean Dupont", email="jean@ex.com", part_status="Accepted",
                          organisateur=False, coche=True),
        ]),
    )


def test_chemin_sidecar():
    from pathlib import Path
    md = Path("/x/2026-07-08_14-00-00/transcription.md")
    assert chemin_sidecar(md) == Path("/x/2026-07-08_14-00-00/bluemind.json")


def test_ecrire_puis_lire(tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion\n", encoding="utf-8")
    ecrire(md, _asso())
    relu = lire(md)
    assert relu is not None
    assert relu.event_uid == "evt-1"
    assert relu.titre == "Point projet X"
    assert len(relu.invites) == 2
    assert relu.invites[1].email == "jean@ex.com"


def test_existe(tmp_path):
    md = tmp_path / "r.md"
    assert existe(md) is False
    ecrire(md, _asso())
    assert existe(md) is True


def test_lire_absent_retourne_none(tmp_path):
    assert lire(tmp_path / "r.md") is None


def test_lire_json_corrompu_retourne_none(tmp_path):
    md = tmp_path / "r.md"
    chemin_sidecar(md).write_text("{ pas du json valide", encoding="utf-8")
    assert lire(md) is None


def test_reecrire_remplace(tmp_path):
    md = tmp_path / "r.md"
    ecrire(md, _asso(titre="V1"))
    ecrire(md, _asso(titre="V2"))
    assert lire(md).titre == "V2"


def test_enregistrer_mapping(tmp_path):
    md = tmp_path / "r.md"
    ecrire(md, _asso())
    enregistrer_mapping(md, {"SPEAKER_00": "Jean Dupont"})
    relu = lire(md)
    assert relu.mapping == {"SPEAKER_00": "Jean Dupont"}
    # Le reste du sidecar (invités, titre) doit rester intact.
    assert relu.titre == "Point projet X"
    assert len(relu.invites) == 2


def test_enregistrer_mapping_sans_sidecar_no_op(tmp_path):
    md = tmp_path / "r.md"
    enregistrer_mapping(md, {"SPEAKER_00": "X"})
    assert lire(md) is None


def _evt():
    return Evenement(
        uid="evt-1", cal_uid="cal:Default:u1", debut_ms=1_752_000_000_000, fin_ms=1_752_003_600_000,
        journee_entiere=False, titre="Point projet X", lieu="",
        organisateur={"nom": "Sylvain Garcia", "email": "sylvain@ex.com"},
        invites=[{"nom": "Jean Dupont", "email": "jean@ex.com", "part_status": "Accepted"}],
    )


def test_construire_invites_depuis_evenement_organisateur_en_tete():
    invites = construire_invites_depuis_evenement(_evt())
    assert invites[0].organisateur is True
    assert invites[0].nom == "Sylvain Garcia"
    assert invites[1].email == "jean@ex.com"
    assert all(i.coche for i in invites)


def test_associer_evenement_ecrit_sidecar_et_bloc(tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n\nTexte\n", encoding="utf-8")
    asso = associer_evenement(md, _evt())
    assert asso.event_uid == "evt-1"
    relu = lire(md)
    assert relu is not None and len(relu.invites) == 2
    assert MARQUEUR_DEBUT in md.read_text(encoding="utf-8")
    assert "# Point projet X" in md.read_text(encoding="utf-8")  # titre appliqué
