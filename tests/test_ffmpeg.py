"""Tests unitaires — lanceur ffmpeg commun (`core/ffmpeg.py`).

Ce module n'existe que pour une raison : rendre le PROCHAIN diagnostic terrain
possible. Trois pannes réelles ont été instruites à l'aveugle parce que le stderr de
ffmpeg n'arrivait jamais jusqu'au log — seuls le code de sortie et la commande y
figuraient, et les codes de ffmpeg sont des `AVERROR` négatifs repliés sur un octet,
illisibles tels quels (8 = « Unrecognized option » le 2026-09-02, 244 = ENOMEM le
2026-09-07). Les tests portent donc sur ce qui atterrit dans le message.
"""
from __future__ import annotations

import subprocess

import pytest

from debrief_meet.core import ffmpeg

#: Relevé RÉEL du 2026-09-07 (expression `aselect` trop imbriquée) : une première
#: ligne de plusieurs kilo-octets, puis le verdict sur les dernières.
STDERR_TERRAIN = (
    b"[Parsed_aselect_0 @ 0x7030046c0] Error while parsing expression '"
    + b"between(t,0.000,1.000)+" * 200
    + b"'\n"
    b"[AVFilterGraph @ 0x703001e00] Error initializing filters\n"
    b"Error opening output file /tmp/systeme_compacte.wav.\n"
    b"Error opening output files: Cannot allocate memory\n"
)


def _echec(code: int, stderr: bytes | None):
    def _run(cmd, **kwargs):
        raise subprocess.CalledProcessError(code, cmd, stderr=stderr)
    return _run


def test_succes_ne_leve_pas(monkeypatch):
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: None)
    ffmpeg.executer("/usr/bin/ffmpeg", "-version")


def test_aucun_argument_implicite(monkeypatch):
    """La commande du message doit être rejouable telle quelle par un humain."""
    vues: list[list[str]] = []
    monkeypatch.setattr("subprocess.run", lambda cmd, **kw: vues.append(cmd))
    ffmpeg.executer("/usr/bin/ffmpeg", "-y", "-i", "a.opus", "b.wav")
    assert vues == [["/usr/bin/ffmpeg", "-y", "-i", "a.opus", "b.wav"]]


def test_echec_porte_le_code_et_le_verdict_de_ffmpeg(monkeypatch):
    monkeypatch.setattr("subprocess.run", _echec(244, STDERR_TERRAIN))

    with pytest.raises(ffmpeg.ErreurFfmpeg) as excinfo:
        ffmpeg.executer("/usr/bin/ffmpeg", "-i", "a.opus", "b.wav")

    message = str(excinfo.value)
    assert "244" in message
    # Les DERNIÈRES lignes : c'est là que ffmpeg dit ce qu'il reproche.
    assert "Cannot allocate memory" in message
    assert "Error initializing filters" in message


def test_message_borne_malgre_un_stderr_de_plusieurs_kilo_octets(monkeypatch):
    """ffmpeg réémet l'expression fautive en entier : 4 ko ici, pour 3 lignes utiles.

    Le log de l'app est rotatif (cf. les diagnostics terrain) — un message non borné
    chasserait le contexte qui l'entoure."""
    monkeypatch.setattr("subprocess.run", _echec(244, STDERR_TERRAIN))

    with pytest.raises(ffmpeg.ErreurFfmpeg) as excinfo:
        ffmpeg.executer("/usr/bin/ffmpeg", "-af", "aselect='" + "x" * 5000 + "'")

    assert len(str(excinfo.value)) < 2_000
    assert "car.)" in str(excinfo.value), "la troncature doit s'annoncer"


def test_commande_conservee_dans_le_message(monkeypatch):
    """Sans la commande, on sait ce que ffmpeg refuse mais pas sur quoi."""
    monkeypatch.setattr("subprocess.run", _echec(8, b"Unrecognized option 'segment_time'\n"))

    with pytest.raises(ffmpeg.ErreurFfmpeg) as excinfo:
        ffmpeg.executer("/opt/vendor/ffmpeg", "-f", "segment", "-i", "moi.opus")

    message = str(excinfo.value)
    assert "/opt/vendor/ffmpeg" in message and "-f segment" in message
    assert "Unrecognized option" in message


@pytest.mark.parametrize("vide", [b"", None, b"   \n\n"])
def test_stderr_vide_reste_journalisable(monkeypatch, vide):
    monkeypatch.setattr("subprocess.run", _echec(1, vide))

    with pytest.raises(ffmpeg.ErreurFfmpeg) as excinfo:
        ffmpeg.executer("/usr/bin/ffmpeg", "-i", "a.opus")

    assert "aucune sortie d'erreur" in str(excinfo.value)


def test_stderr_texte_accepte_comme_octets(monkeypatch):
    """`capture_output` rend des octets, mais un appelant en mode texte est possible."""
    monkeypatch.setattr("subprocess.run", _echec(1, "Invalid data found\n"))

    with pytest.raises(ffmpeg.ErreurFfmpeg) as excinfo:
        ffmpeg.executer("/usr/bin/ffmpeg", "-i", "a.opus")

    assert "Invalid data found" in str(excinfo.value)


def test_octets_non_utf8_ne_font_pas_perdre_le_message(monkeypatch):
    monkeypatch.setattr("subprocess.run", _echec(1, b"\xff\xfe Conversion failed!\n"))

    with pytest.raises(ffmpeg.ErreurFfmpeg) as excinfo:
        ffmpeg.executer("/usr/bin/ffmpeg", "-i", "a.opus")

    assert "Conversion failed!" in str(excinfo.value)


# ── Les trois appelants réels remontent bien ce message ─────────────────────────
#
# Le lanceur seul ne prouve rien : c'est chaque site d'appel qui journalisait `exc`
# sans stderr. Un site oublié redeviendrait muet sans qu'aucun test ne bronche.

def test_compaction_des_silences_remonte_le_stderr(tmp_path, monkeypatch):
    from debrief_meet.core.mistral import silences

    monkeypatch.setattr(silences, "chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("subprocess.run", _echec(244, STDERR_TERRAIN))
    source = tmp_path / "systeme.opus"
    source.write_bytes(b"audio")
    plan = silences.PlanCompaction(plages=((1.0, 2.0),), duree_totale_s=100.0)

    with pytest.raises(ffmpeg.ErreurFfmpeg, match="Cannot allocate memory"):
        silences.compacter_piste(source, tmp_path, plan)


def test_decoupage_remonte_le_stderr(tmp_path, monkeypatch):
    """Repli découpage : sorti en 8 le 2026-09-02, message perdu (docs/42 §10.4)."""
    from debrief_meet.core.mistral import decoupage

    monkeypatch.setattr(decoupage, "chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("subprocess.run", _echec(8, b"Unrecognized option 'segment_time'\n"))
    source = tmp_path / "moi.opus"
    source.write_bytes(b"audio")

    with pytest.raises(ffmpeg.ErreurFfmpeg, match="Unrecognized option"):
        decoupage.decouper_piste(source, tmp_path / "out")


def test_decodage_audio_remonte_le_stderr(tmp_path, monkeypatch):
    from debrief_meet.core import audio, fichiers

    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr("subprocess.run", _echec(1, b"moi.opus: Invalid data found\n"))
    source = tmp_path / "moi.opus"
    source.write_bytes(b"audio")

    with pytest.raises(ffmpeg.ErreurFfmpeg, match="Invalid data found"):
        audio.decoder_audio_16k(source)
