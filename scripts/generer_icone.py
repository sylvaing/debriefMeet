#!/usr/bin/env python3
"""Génère src/debrief_meet/ui/assets/AppIcon.icns (icône d'app macOS, Dock/Finder).

Rend le motif validé (carré bleu système + bulle blanche + ondes) à toutes les
tailles d'un .iconset, puis appelle `iconutil` pour produire le .icns.

Usage :  python scripts/generer_icone.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    racine = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(racine / "src"))

    from PySide6.QtGui import QGuiApplication

    QGuiApplication.instance() or QGuiApplication(sys.argv)
    from debrief_meet.ui.icones import ecrire_iconset

    assets = racine / "src" / "debrief_meet" / "ui" / "assets"
    iconset = assets / "AppIcon.iconset"
    icns = assets / "AppIcon.icns"

    ecrire_iconset(iconset)

    if not shutil.which("iconutil"):
        print(f"iconutil introuvable (macOS requis) — PNG laissés dans {iconset}",
              file=sys.stderr)
        return 1

    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    shutil.rmtree(iconset)
    print(f"✓ Icône générée : {icns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
