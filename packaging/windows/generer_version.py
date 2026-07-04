"""Génère `_version.py` et `version.iss` à partir de `__version__` + `BUILD_INFO`
(docs/31 §3.2, docs/32 §3.1).

Exécuté sur la VM (Python portable, aucune dépendance Windows-only) — la copie des
sources sur la VM n'est PAS un dépôt git, donc la date et le hash git sont transmis
par le script Mac dans un fichier `BUILD_INFO` (2 lignes : AAAAMMJJ puis hash court),
rsyncé en même temps que les sources.

Format : VERSION_COMPLETE = "<__version__>+<AAAAMMJJ>.<hash-git-court>"
(ex. "0.2.0+20260703.a1b2c3d") — un log reçu ↔ un exécutable livré ↔ un commit git.

Usage : python packaging/windows/generer_version.py [--build-info CHEMIN]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
INIT_PY = RACINE / "src" / "debrief_meet" / "__init__.py"
VERSION_PY = RACINE / "src" / "debrief_meet" / "_version.py"
VERSION_ISS = Path(__file__).resolve().parent / "version.iss"
BUILD_INFO_DEFAUT = RACINE / "BUILD_INFO"


def lire_version() -> str:
    contenu = INIT_PY.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', contenu)
    if not m:
        raise SystemExit(f"__version__ introuvable dans {INIT_PY}")
    return m.group(1)


def lire_build_info(chemin: Path) -> tuple[str, str]:
    """`BUILD_INFO` : 2 lignes — date AAAAMMJJ puis hash git court."""
    if not chemin.exists():
        raise SystemExit(f"{chemin} introuvable — généré par le script Mac (rsync)")
    lignes = [l.strip() for l in chemin.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lignes) < 2:
        raise SystemExit(f"{chemin} invalide (attendu : 2 lignes — date puis hash git)")
    return lignes[0], lignes[1]


def version_numerique(version: str) -> str:
    """"0.2.0" → "0.2.0.0" : `VersionInfoVersion` (Inno Setup) exige 4 composants."""
    parties = version.split(".")
    while len(parties) < 4:
        parties.append("0")
    return ".".join(parties[:4])


def generer(build_info: Path = BUILD_INFO_DEFAUT) -> str:
    """Écrit `_version.py` et `version.iss`, retourne `VERSION_COMPLETE`."""
    version = lire_version()
    date, hash_git = lire_build_info(build_info)
    version_complete = f"{version}+{date}.{hash_git}"

    VERSION_PY.write_text(f'VERSION_COMPLETE = "{version_complete}"\n', encoding="utf-8")
    VERSION_ISS.write_text(
        f'#define MonAppVersion "{version_complete}"\n'
        f'#define MonAppVersionNum "{version_numerique(version)}"\n',
        encoding="utf-8",
    )
    return version_complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-info", type=Path, default=BUILD_INFO_DEFAUT)
    args = parser.parse_args()
    version_complete = generer(args.build_info)
    # ASCII strict : la console Windows par défaut (cp1252) ne sait pas encoder
    # les caractères comme "→" — cassé une première fois lors du build réel sur
    # la VM (docs/32, 2026-07-03).
    print(f"VERSION_COMPLETE = {version_complete}")
    print(f"-> {VERSION_PY}")
    print(f"-> {VERSION_ISS}")


if __name__ == "__main__":
    main()
