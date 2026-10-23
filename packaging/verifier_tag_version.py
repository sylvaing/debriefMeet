"""Garde-fou tag ↔ `__version__` du job `version` de la CI (docs/53 §4).

Une release candidate porte SON numéro dans le code : `__version__ = "0.4.1rc1"` pour le
tag `v0.4.1-rc1`, puis `"0.4.1"` pour `v0.4.1`. C'est ce qui rend la rc plus ANCIENNE
que la finale au sens PEP 440 (`0.4.1rc1 < 0.4.1`), donc remplacée par la mise à jour
automatique. Constaté le 2026-10-23 : la `v0.4.0-rc1`, construite avec `"0.4.0"`, se
présentait comme la finale et ne se voyait jamais proposer la vraie `v0.4.0`.

Seules deux formes sont admises (`X.Y.Z` et `X.Y.ZrcN`) : chacune a sa traduction pour
Inno Setup, Info.plist et Debian (`generer_version.py`, `debriefMeet.spec`,
`build_deb.sh`) — une forme de plus devrait être traduite aux trois endroits.

Usage : python3 packaging/verifier_tag_version.py <__version__> <tag>
"""
from __future__ import annotations

import re
import sys

_FINALE = re.compile(r"\d+\.\d+\.\d+")
_RC = re.compile(r"(\d+\.\d+\.\d+)rc(\d+)")


def tag_attendu(version: str) -> str:
    """`0.4.1` → `v0.4.1`, `0.4.1rc1` → `v0.4.1-rc1` ; toute autre forme est refusée."""
    if m := _RC.fullmatch(version):
        return f"v{m[1]}-rc{m[2]}"
    if _FINALE.fullmatch(version):
        return f"v{version}"
    raise ValueError(
        f"__version__ = {version!r} : formes admises X.Y.Z (release) ou X.Y.ZrcN (rc)")


def main(argv: list[str]) -> int:
    version, tag = argv
    try:
        attendu = tag_attendu(version)
    except ValueError as exc:
        print(f"::error::{exc}")
        return 1
    if tag != attendu:
        conseil = (
            f"pour publier {tag}, passer __version__ (et pyproject.toml) à la version "
            f"correspondante avant de tagger" if tag.startswith("v") else "")
        print(f"::error::le tag {tag} ne correspond pas à __version__ = {version} "
              f"(attendu : {attendu}) — {conseil}".rstrip(" —"))
        return 1
    print(f"tag {tag} conforme à __version__ = {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
