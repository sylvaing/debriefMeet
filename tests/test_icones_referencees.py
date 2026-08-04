"""Toute icône Phosphor référencée dans le code doit exister dans les assets.

Motivation (2026-08-04) : un `icone="file-zip"` inventé — absent des 38 SVG embarqués —
a fait **planter l'application** chez une utilisatrice, `icone_svg_teintee` faisant un
`read_text` sans garde. Le crash est survenu APRÈS un export de diagnostic réussi.

Les tests unitaires ne l'avaient pas vu : ils remplaçaient `DialogueGabarit` par un
double, donc ne construisaient jamais le vrai dialogue et ne touchaient jamais l'icône.
D'où ce test statique, qui couvre la classe entière du problème plutôt qu'un cas.

Analyse par `ast` et non par expression régulière : un regex attrape aussi les
occurrences dans les commentaires et les docstrings (constaté en écrivant ce test — la
mention de `file-zip` ci-dessus suffisait à le faire échouer).
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).parent.parent
SRC = RACINE / "src" / "debrief_meet"
PHOSPHOR = SRC / "ui" / "assets" / "icons" / "phosphor"

# Fonctions dont le 1er argument positionnel est un nom d'icône Phosphor.
_FONCTIONS_ICONE = {"icone_phosphor", "_icone_menu", "icone_bascule"}


def _noms_references() -> dict[str, set[str]]:
    """nom d'icône → fichiers qui la référencent (via ast, docstrings exclues)."""
    trouves: dict[str, set[str]] = {}

    def noter(nom: str, fichier: str) -> None:
        trouves.setdefault(nom, set()).add(fichier)

    for py in SRC.rglob("*.py"):
        fichier = str(py.relative_to(SRC))
        for noeud in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if not isinstance(noeud, ast.Call):
                continue
            nom_fn = getattr(noeud.func, "id", None) or getattr(noeud.func, "attr", None)
            if nom_fn in _FONCTIONS_ICONE and noeud.args:
                premier = noeud.args[0]
                if isinstance(premier, ast.Constant) and isinstance(premier.value, str):
                    noter(premier.value, fichier)
            for kw in noeud.keywords:
                if kw.arg == "icone" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    noter(kw.value.value, fichier)
    return trouves


def test_les_assets_contiennent_des_icones():
    """Garde-fou du garde-fou : si le dossier était vide ou déplacé, le test ci-dessous
    passerait en ne vérifiant rien."""
    assert PHOSPHOR.is_dir()
    assert len(list(PHOSPHOR.glob("*.svg"))) >= 30


def test_toute_icone_referencee_existe():
    references = _noms_references()
    assert references, "aucune icône détectée — l'analyse ast est à revoir"

    manquantes = {
        nom: f for nom, f in sorted(references.items())
        if not (PHOSPHOR / f"{nom}.svg").exists()
    }
    assert not manquantes, (
        "icône(s) référencée(s) mais absente(s) des assets — plantage à l'exécution :\n"
        + "\n".join(f"  {nom}.svg  ← {', '.join(sorted(f))}" for nom, f in manquantes.items()))


def test_detecte_bien_une_icone_inventee(tmp_path, monkeypatch):
    """Le test ci-dessus ne garde quelque chose que s'il sait échouer."""
    faux = tmp_path / "faux.py"
    faux.write_text('from x import dialogues\ndialogues.informer(None, icone="nawak-42")\n',
                    encoding="utf-8")
    monkeypatch.setattr("tests.test_icones_referencees.SRC", tmp_path)
    assert "nawak-42" in _noms_references()
