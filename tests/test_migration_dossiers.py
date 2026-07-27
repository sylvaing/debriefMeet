from __future__ import annotations

import json
from pathlib import Path

from debrief_meet.core.migration_dossiers import migrer_reunions_vers_dossiers


def test_migration_nominale_deplace_les_satellites(tmp_path):
    (tmp_path / "2026-07-02_15-01.md").write_text("# Réunion — 2026-07-02 15:01\n\ncorps",
                                                    encoding="utf-8")
    (tmp_path / "2026-07-02_15-01_moi.opus").write_bytes(b"\x00")
    (tmp_path / "2026-07-02_15-01_systeme.wav").write_bytes(b"\x00")
    (tmp_path / "2026-07-02_15-01_locuteurs.md").write_text("locuteurs", encoding="utf-8")
    (tmp_path / "2026-07-02_15-01_CR.md").write_text("# CR", encoding="utf-8")

    n = migrer_reunions_vers_dossiers(tmp_path)

    assert n == 1
    dossier = tmp_path / "2026-07-02_15-01"
    assert (dossier / "transcription.md").exists()
    assert (dossier / "moi.opus").exists()
    assert (dossier / "systeme.wav").exists()
    assert (dossier / "locuteurs.md").exists()
    assert (dossier / "CR.md").exists()
    assert not (tmp_path / "2026-07-02_15-01.md").exists()


def test_migration_avec_titre_bluemind_ajoute_un_slug(tmp_path):
    (tmp_path / "2026-07-02_15-01.md").write_text("# Réunion — 2026-07-02 15:01\n\ncorps",
                                                    encoding="utf-8")
    sidecar = tmp_path / "2026-07-02_15-01.bluemind.json"
    sidecar.write_text(json.dumps({
        "version": 1, "event_uid": "e1", "cal_uid": "c1",
        "titre": "Point commerce Bastien", "debut": "2026-07-02T15:01:00", "invites": [],
    }), encoding="utf-8")

    migrer_reunions_vers_dossiers(tmp_path)

    dossier = tmp_path / "2026-07-02_15-01_Point-commerce-Bastien"
    assert dossier.exists()
    assert (dossier / "transcription.md").exists()
    assert (dossier / "bluemind.json").exists()


def test_migration_avec_h1_custom_ajoute_un_slug(tmp_path):
    (tmp_path / "2026-07-02_15-01.md").write_text("# Budget Q3\n\ncorps", encoding="utf-8")

    migrer_reunions_vers_dossiers(tmp_path)

    assert (tmp_path / "2026-07-02_15-01_Budget-Q3").exists()


def test_migration_titre_bluemind_priorite_sur_h1(tmp_path):
    (tmp_path / "2026-07-02_15-01.md").write_text("# Un autre titre\n\ncorps", encoding="utf-8")
    sidecar = tmp_path / "2026-07-02_15-01.bluemind.json"
    sidecar.write_text(json.dumps({
        "version": 1, "event_uid": "e1", "cal_uid": "c1",
        "titre": "Titre BlueMind", "debut": "2026-07-02T15:01:00", "invites": [],
    }), encoding="utf-8")

    migrer_reunions_vers_dossiers(tmp_path)

    assert (tmp_path / "2026-07-02_15-01_Titre-BlueMind").exists()


def test_migration_sans_titre_reste_horodatage_seul(tmp_path):
    (tmp_path / "2026-07-02_15-01.md").write_text("# Réunion — 2026-07-02 15:01\n\ncorps",
                                                    encoding="utf-8")
    migrer_reunions_vers_dossiers(tmp_path)
    assert (tmp_path / "2026-07-02_15-01").exists()


def test_migration_collision_legacy_meme_minute(tmp_path):
    (tmp_path / "2026-07-06_09-56.md").write_text("# Réunion — 2026-07-06 09:56\n\na",
                                                    encoding="utf-8")
    (tmp_path / "2026-07-06_09-56-2.md").write_text("# Réunion — 2026-07-06 09:56\n\nb",
                                                     encoding="utf-8")

    n = migrer_reunions_vers_dossiers(tmp_path)

    assert n == 2
    assert (tmp_path / "2026-07-06_09-56" / "transcription.md").read_text(encoding="utf-8").endswith("a")
    assert (tmp_path / "2026-07-06_09-56-2" / "transcription.md").read_text(encoding="utf-8").endswith("b")


def test_migration_idempotente_second_appel_zero(tmp_path):
    (tmp_path / "2026-07-02_15-01.md").write_text("brut", encoding="utf-8")
    n1 = migrer_reunions_vers_dossiers(tmp_path)
    n2 = migrer_reunions_vers_dossiers(tmp_path)
    assert n1 == 1
    assert n2 == 0


def test_migration_ignore_ds_store(tmp_path):
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    n = migrer_reunions_vers_dossiers(tmp_path)
    assert n == 0
    assert (tmp_path / ".DS_Store").exists()


def test_migration_ignore_fichier_non_reunion(tmp_path):
    (tmp_path / "notes.md").write_text("pas une réunion", encoding="utf-8")
    n = migrer_reunions_vers_dossiers(tmp_path)
    assert n == 0
    assert (tmp_path / "notes.md").exists()


def test_migration_ignore_journal(tmp_path):
    (tmp_path / "2026-07-02.md").write_text("journal", encoding="utf-8")
    n = migrer_reunions_vers_dossiers(tmp_path)
    assert n == 0
    assert (tmp_path / "2026-07-02.md").exists()


def test_migration_ignore_dossier_deja_migre(tmp_path):
    """Idempotence : un `.md` déjà dans un sous-dossier n'est jamais retraité (on ne
    parcourt que la racine)."""
    dossier = tmp_path / "2026-07-02_15-01"
    dossier.mkdir()
    (dossier / "transcription.md").write_text("déjà migré", encoding="utf-8")
    n = migrer_reunions_vers_dossiers(tmp_path)
    assert n == 0


def test_migration_dossier_reunions_absent(tmp_path):
    assert migrer_reunions_vers_dossiers(tmp_path / "absent") == 0


def test_migration_ne_leve_jamais_sur_erreur_d_un_item(tmp_path, monkeypatch):
    (tmp_path / "2026-07-02_15-01.md").write_text("a", encoding="utf-8")
    (tmp_path / "2026-07-02_15-02.md").write_text("b", encoding="utf-8")

    import debrief_meet.core.migration_dossiers as mod
    original = mod._migrer_une
    appels = []

    def _faux_migrer_une(dossier_reunions, md):
        appels.append(md.name)
        if md.name == "2026-07-02_15-01.md":
            raise RuntimeError("boom")
        return original(dossier_reunions, md)

    monkeypatch.setattr(mod, "_migrer_une", _faux_migrer_une)
    n = mod.migrer_reunions_vers_dossiers(tmp_path)

    assert n == 1                                     # la 2ᵉ réunion migrée malgré l'échec de la 1ʳᵉ
    assert len(appels) == 2
    assert (tmp_path / "2026-07-02_15-02").exists()


def test_migration_multiple_collision_suffixe_incremente(tmp_path, monkeypatch):
    """Cas rare (migration interrompue en plein milieu) : le dossier cible existe
    déjà → suffixe -2, -3…"""
    (tmp_path / "2026-07-02_15-01").mkdir()             # cible déjà prise
    (tmp_path / "2026-07-02_15-01_moi.opus").write_bytes(b"\x00")
    (tmp_path / "2026-07-02_15-01.md").write_text("x", encoding="utf-8")

    migrer_reunions_vers_dossiers(tmp_path)

    assert (tmp_path / "2026-07-02_15-01-2" / "transcription.md").exists()
    assert (tmp_path / "2026-07-02_15-01-2" / "moi.opus").exists()
