"""Relais `python -c` en app figée (docs/16 §5.1).

Régression trouvée au 1er lancement réel de l'app packagée macOS : `multiprocessing`
(déclenché par mlx/torch, ex. `resource_tracker`) relance `sys.executable` avec
`-B -S -I -c "<code>"`, que notre binaire figé — pas un interpréteur générique —
ne sait pas interpréter sans ce relais."""
from __future__ import annotations

import sys

from debrief_meet.__main__ import _relais_interprete_figee


def test_absent_ne_fait_rien(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["debriefMeet", "--toggle"])
    assert _relais_interprete_figee() is False
    assert sys.argv == ["debriefMeet", "--toggle"]


def test_execute_le_code_apres_moins_c(tmp_path, monkeypatch):
    marker = tmp_path / "marker.txt"
    code = f"open({str(marker)!r}, 'w').write('ok')"
    monkeypatch.setattr(sys, "argv", ["debriefMeet", "-B", "-S", "-I", "-c", code])
    assert _relais_interprete_figee() is True
    assert marker.read_text(encoding="utf-8") == "ok"


def test_argv_apres_moins_c_est_preserve(tmp_path, monkeypatch):
    marker = tmp_path / "argv.txt"
    code = f"import sys; open({str(marker)!r}, 'w').write(repr(sys.argv))"
    monkeypatch.setattr(sys, "argv", ["debriefMeet", "-B", "-c", code, "extra"])
    _relais_interprete_figee()
    assert marker.read_text(encoding="utf-8") == "['-c', 'extra']"
