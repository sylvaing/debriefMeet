"""Garde-fou tag ↔ `__version__` (packaging/verifier_tag_version.py, docs/53 §6).

Terrain du 2026-10-23 : la `v0.4.0-rc1` avait été construite avec `__version__ = "0.4.0"`
(le garde-fou acceptait `v<version>-rcN` pour n'importe quelle version) ; elle se
présentait donc comme la finale et la mise à jour automatique ne lui proposait jamais
la vraie `v0.4.0`. Les tests figent la correspondance ET son effet sur la comparaison
de versions de l'app — c'est cet effet qui justifie la règle.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "verifier_tag_version.py"


def _module():
    spec = importlib.util.spec_from_file_location("verifier_tag_version_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("version, tag", [
    ("0.4.0", "v0.4.0"),
    ("0.4.1rc1", "v0.4.1-rc1"),
    ("1.10.0rc12", "v1.10.0-rc12"),
])
def test_tag_attendu(version, tag):
    assert _module().tag_attendu(version) == tag


@pytest.mark.parametrize("version", ["0.4", "0.4.1-rc1", "0.4.1.dev0", "0.4.1a1", "v0.4.1", ""])
def test_formes_non_traduites_refusees(version):
    """Chaque forme admise a sa traduction Inno/Info.plist/Debian : rien d'autre ne passe."""
    with pytest.raises(ValueError):
        _module().tag_attendu(version)


def test_le_cas_du_terrain_est_refuse():
    """`v0.4.0-rc1` sur un code en `0.4.0` : exactement ce qui a été publié le 2026-10-23."""
    assert _module().main(["0.4.0", "v0.4.0-rc1"]) == 1


def test_une_finale_sur_un_code_rc_est_refusee():
    """Oublier de retirer `rc1` avant la finale publierait une « finale » plus ancienne
    que sa propre rc."""
    assert _module().main(["0.4.1rc1", "v0.4.1"]) == 1


def test_cli_conforme_et_non_conforme():
    ok = subprocess.run([sys.executable, str(SCRIPT), "0.4.1rc1", "v0.4.1-rc1"],
                        capture_output=True, text=True)
    ko = subprocess.run([sys.executable, str(SCRIPT), "0.4.1", "v0.4.1-rc1"],
                        capture_output=True, text=True)
    assert ok.returncode == 0
    assert ko.returncode == 1 and "::error::" in ko.stdout and "attendu : v0.4.1" in ko.stdout


def test_effet_une_rc_conforme_est_remplacee_par_sa_finale():
    """Ce que la règle achète : le poste en rc voit la finale comme plus récente…"""
    from debrief_meet.core.mise_a_jour import est_plus_recente

    assert est_plus_recente("0.4.1", "0.4.1rc1") is True
    # … alors qu'une rc numérotée comme la finale (l'ancien garde-fou) ne l'est jamais.
    assert est_plus_recente("0.4.0", "0.4.0") is False
