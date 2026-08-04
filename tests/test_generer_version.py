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
    """Égalité exacte (et pas `in`) : `debriefMeet.spec` regexe ce fichier pour en
    lire l'édition — connaître son contenu au caractère près a de la valeur."""
    module_isole.generer(_build_info(tmp_path))
    contenu = module_isole.VERSION_PY.read_text(encoding="utf-8")
    assert contenu == (
        'VERSION_COMPLETE = "0.2.0+20260703.a1b2c3d"\n'
        'EDITION_COMPILEE = "complete"\n'
    )


def test_ecrit_version_iss(module_isole, tmp_path):
    module_isole.generer(_build_info(tmp_path))
    contenu = module_isole.VERSION_ISS.read_text(encoding="utf-8")
    assert '#define MonAppVersion "0.2.0+20260703.a1b2c3d"' in contenu
    assert '#define MonAppVersionNum "0.2.0.0"' in contenu


# ── Édition compilée (docs/44) ───────────────────────────────────────────────

def test_edition_defaut_est_complete(module_isole, tmp_path):
    module_isole.generer(_build_info(tmp_path))
    assert 'EDITION_COMPILEE = "complete"' in module_isole.VERSION_PY.read_text(encoding="utf-8")
    assert '#define MonAppEdition "complete"' in module_isole.VERSION_ISS.read_text(encoding="utf-8")


def test_edition_lite_ecrite_dans_les_deux_fichiers(module_isole, tmp_path):
    module_isole.generer(_build_info(tmp_path), edition="lite")
    assert 'EDITION_COMPILEE = "lite"' in module_isole.VERSION_PY.read_text(encoding="utf-8")
    assert '#define MonAppEdition "lite"' in module_isole.VERSION_ISS.read_text(encoding="utf-8")


def test_edition_inconnue_leve(module_isole, tmp_path):
    """`choices=` ne garde que la CLI — l'appel direct doit se garder tout seul."""
    with pytest.raises(SystemExit):
        module_isole.generer(_build_info(tmp_path), edition="turbo")


def test_edition_ecrase_la_precedente(module_isole, tmp_path):
    """Anti-obsolescence : la copie des sources sur la VM écrase mais ne supprime
    rien — un `_version.py`/`version.iss` « lite » laissé par le build précédent ne
    doit pas contaminer le build complet suivant (spec ET module embarqué)."""
    build_info = _build_info(tmp_path)
    module_isole.generer(build_info, edition="lite")
    module_isole.generer(build_info, edition="complete")
    assert "lite" not in module_isole.VERSION_PY.read_text(encoding="utf-8")
    assert "lite" not in module_isole.VERSION_ISS.read_text(encoding="utf-8")


def test_version_iss_exactement_trois_defines(module_isole, tmp_path):
    """Garde-fou contre un `#ifndef MonAppEdition` du .iss qui masquerait un
    générateur ayant cessé d'émettre l'édition."""
    module_isole.generer(_build_info(tmp_path), edition="lite")
    lignes = [l for l in module_isole.VERSION_ISS.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 3
    assert all(l.startswith("#define ") for l in lignes)


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
