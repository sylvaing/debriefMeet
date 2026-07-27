"""Tests unitaires — découpage (REPLI seulement, §10). Pas de dépendance à ffmpeg :
`subprocess.run` est mocké, il ne fait qu'imiter la création des segments attendus."""
from __future__ import annotations

import pytest

from debrief_meet.core.fichiers import ErreurFfmpegIntrouvable
from debrief_meet.core.mistral import decoupage


def _faux_subprocess_run(dossier_sortie, suffixe, n_segments):
    """Fabrique un faux `subprocess.run` qui crée `n_segments` fichiers factices."""
    def _run(cmd, **kwargs):
        for i in range(n_segments):
            (dossier_sortie / f"seg_{i:03d}{suffixe}").write_bytes(b"x")
        return None
    return _run


def test_decouper_leve_si_ffmpeg_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(decoupage, "chemin_ffmpeg", lambda: None)
    source = tmp_path / "reunion_moi.opus"
    source.write_bytes(b"audio")
    with pytest.raises(ErreurFfmpegIntrouvable):
        decoupage.decouper_piste(source, tmp_path / "out")


def test_decouper_appelle_ffmpeg_avec_les_bons_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(decoupage, "chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")
    source = tmp_path / "reunion_moi.opus"
    source.write_bytes(b"audio")
    dossier_sortie = tmp_path / "out"

    appels = []

    def _run(cmd, **kwargs):
        appels.append(cmd)
        (dossier_sortie / "seg_000.opus").write_bytes(b"x")
        (dossier_sortie / "seg_001.opus").write_bytes(b"x")

    monkeypatch.setattr(decoupage.subprocess, "run", _run)

    segments = decoupage.decouper_piste(source, dossier_sortie, limite_s=840)

    assert len(segments) == 2
    assert segments == sorted(segments)  # ordre chronologique
    cmd = appels[0]
    assert "/usr/bin/ffmpeg" in cmd
    assert "-segment_time" in cmd and "840" in cmd
    assert "-c" in cmd and "copy" in cmd          # pas de ré-encodage
    assert "-reset_timestamps" in cmd and "1" in cmd


def test_decouper_retourne_segments_tries(tmp_path, monkeypatch):
    monkeypatch.setattr(decoupage, "chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")
    source = tmp_path / "reunion_systeme.opus"
    source.write_bytes(b"audio")
    dossier_sortie = tmp_path / "out"
    monkeypatch.setattr(
        decoupage.subprocess, "run", _faux_subprocess_run(dossier_sortie, ".opus", 3))

    segments = decoupage.decouper_piste(source, dossier_sortie)

    assert [s.name for s in segments] == ["seg_000.opus", "seg_001.opus", "seg_002.opus"]


def test_limite_par_defaut_est_14_minutes():
    assert decoupage.LIMITE_SEGMENT_S == 14 * 60
