#!/usr/bin/env python3
"""Génère les icônes d'app à partir du même motif SVG (carré bleu système + bulle
blanche + ondes) :
  - src/debrief_meet/ui/assets/AppIcon.icns (macOS, Dock/Finder) via `iconutil` ;
  - packaging/windows/debriefMeet.ico (Windows, installeur Inno Setup + .exe,
    docs/32 §3.2), multi-résolution (16/32/48/256) via Pillow.

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
    from debrief_meet.ui.icones import ecrire_ico, ecrire_iconset

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
    print(f"✓ Icône macOS générée : {icns}")

    ico = racine / "packaging" / "windows" / "debriefMeet.ico"
    ecrire_ico(ico)
    print(f"✓ Icône Windows générée : {ico}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
