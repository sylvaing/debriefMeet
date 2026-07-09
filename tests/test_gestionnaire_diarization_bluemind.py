from __future__ import annotations

from debrief_meet.core.bluemind.association import Association, InviteAssocie, ecrire
from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT
from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization


def _config(tmp_path):
    from debrief_meet.core.config import Config
    return Config(chemin=tmp_path / "config.json")


def test_insere_bloc_dans_locuteurs_si_associe(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    loc = tmp_path / "2026-07-08_14-00_locuteurs.md"
    md.write_text("# Point projet X\n\nTranscription\n")
    loc.write_text("# Point projet X\n\nSPEAKER_00: bonjour\n")
    ecrire(md, Association(
        event_uid="e1", cal_uid="cal", titre="Point projet X", debut="2026-07-08T14:00:00+02:00",
        invites=[InviteAssocie(nom="Jean Dupont", email="jean@ex.com", part_status="Accepted",
                                organisateur=False, coche=True)],
    ))

    gest = GestionnaireDiarization(None, _config(tmp_path))
    gest._inserer_bloc_invites_si_associe(md, loc)

    texte = loc.read_text(encoding="utf-8")
    assert MARQUEUR_DEBUT in texte
    assert "Jean Dupont" in texte


def test_no_op_sans_association(qapp, tmp_path):
    loc = tmp_path / "2026-07-08_14-00_locuteurs.md"
    loc.write_text("# X\n\nSPEAKER_00: bonjour\n")
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# X\n")

    gest = GestionnaireDiarization(None, _config(tmp_path))
    gest._inserer_bloc_invites_si_associe(md, loc)
    assert MARQUEUR_DEBUT not in loc.read_text(encoding="utf-8")


def test_sur_terminee_appelle_le_hook_seulement_pour_diarization(qapp, tmp_path):
    md = tmp_path / "2026-07-08_14-00.md"
    loc = tmp_path / "2026-07-08_14-00_locuteurs.md"
    md.write_text("# X\n")
    loc.write_text("# X\n\nSPEAKER_00: bonjour\n")
    ecrire(md, Association(
        event_uid="e1", cal_uid="cal", titre="X", debut="2026-07-08T14:00:00+02:00",
        invites=[InviteAssocie(nom="Jean", email="jean@ex.com", part_status=None,
                                organisateur=False, coche=True)],
    ))

    gest = GestionnaireDiarization(None, _config(tmp_path))
    gest._job_en_cours = md
    gest._type_job = "transcription"
    gest._sur_terminee(loc)
    assert MARQUEUR_DEBUT not in loc.read_text(encoding="utf-8")

    gest._job_en_cours = md
    gest._type_job = "diarization"
    gest._sur_terminee(loc)
    assert MARQUEUR_DEBUT in loc.read_text(encoding="utf-8")
