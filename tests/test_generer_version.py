"""docs/32 §6 : `generer_version.py` testé unitairement (format, fichiers émis).

Le script vit hors de `src/` (packaging/windows/) — chargé par chemin de fichier
plutôt qu'importé comme un module du paquet."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "packaging" / "windows" / "generer_version.py"
)


def _charger_module():
    spec = importlib.util.spec_from_file_location("generer_version_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module_isole(tmp_path, monkeypatch):
    mod = _charger_module()
    init_py = tmp_path / "__init__.py"
    init_py.write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    monkeypatch.setattr(mod, "INIT_PY", init_py)
    monkeypatch.setattr(mod, "VERSION_PY", tmp_path / "_version.py")
    monkeypatch.setattr(mod, "VERSION_ISS", tmp_path / "version.iss")
    return mod


def _build_info(tmp_path, date="20260703", hash_git="a1b2c3d") -> Path:
    chemin = tmp_path / "BUILD_INFO"
    chemin.write_text(f"{date}\n{hash_git}\n", encoding="utf-8")
    return chemin


def test_format_version_complete(module_isole, tmp_path):
    resultat = module_isole.generer(_build_info(tmp_path))
    assert resultat == "0.2.0+20260703.a1b2c3d"


def test_ecrit_version_py(module_isole, tmp_path):
    module_isole.generer(_build_info(tmp_path))
    contenu = module_isole.VERSION_PY.read_text(encoding="utf-8")
    assert contenu == 'VERSION_COMPLETE = "0.2.0+20260703.a1b2c3d"\n'


def test_ecrit_version_iss(module_isole, tmp_path):
    module_isole.generer(_build_info(tmp_path))
    contenu = module_isole.VERSION_ISS.read_text(encoding="utf-8")
    assert '#define MonAppVersion "0.2.0+20260703.a1b2c3d"' in contenu
    assert '#define MonAppVersionNum "0.2.0.0"' in contenu


def test_build_info_absent_leve(module_isole, tmp_path):
    with pytest.raises(SystemExit):
        module_isole.generer(tmp_path / "BUILD_INFO_INEXISTANT")


def test_build_info_incomplet_leve(module_isole, tmp_path):
    chemin = tmp_path / "BUILD_INFO"
    chemin.write_text("juste-une-ligne\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        module_isole.generer(chemin)


def test_version_manquante_leve(tmp_path, monkeypatch):
    mod = _charger_module()
    init_py = tmp_path / "__init__.py"
    init_py.write_text("APP_NAME = 'debriefMeet'\n", encoding="utf-8")
    monkeypatch.setattr(mod, "INIT_PY", init_py)
    with pytest.raises(SystemExit):
        mod.lire_version()


def test_version_numerique_complete_avec_des_zeros():
    mod = _charger_module()
    assert mod.version_numerique("0.2.0") == "0.2.0.0"
    assert mod.version_numerique("1.0") == "1.0.0.0"
    assert mod.version_numerique("1.2.3.4") == "1.2.3.4"
