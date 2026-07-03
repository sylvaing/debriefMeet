"""Garde-fou : la doc d'interprétation reste synchrone du schéma réel.

Si rapport.py gagne/perd une clé de premier niveau sans que docs/08-benchmark.md
soit mis à jour (ou l'inverse), ce test échoue — la doc étant la clé de lecture
des rapports, elle ne doit jamais diverger du code.
"""
from __future__ import annotations

import re
from pathlib import Path

from benchmark import rapport

DOC = Path(__file__).parent.parent / "docs" / "08-benchmark.md"


def _cles_documentees() -> set[str]:
    texte = DOC.read_text(encoding="utf-8")
    bloc = re.search(r"<!-- CLES-RAPPORT-DEBUT -->(.*?)<!-- CLES-RAPPORT-FIN -->",
                     texte, re.DOTALL)
    assert bloc, "Marqueurs CLES-RAPPORT introuvables dans docs/08-benchmark.md"
    return set(re.findall(r"`([a-z_]+)`", bloc.group(1)))


def test_cles_rapport_synchrones_avec_doc():
    produit = rapport.construire_rapport(
        materiel={}, mode={}, audio={}, transcription=[], diarisation=[],
        capture={}, accelerateurs={}, observations="")
    assert set(produit) == _cles_documentees(), (
        "Le schéma du rapport et docs/08-benchmark.md ont divergé — "
        "mettre à jour le bloc CLES-RAPPORT ou rapport.construire_rapport."
    )
