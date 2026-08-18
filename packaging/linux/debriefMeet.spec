# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller — debriefMeet (Linux, onedir) — docs/49 §6.1.

Mode onedir comme sur Windows : démarrage rapide, bibliothèques Qt lourdes, et le
`.deb` empaquette un dossier tel quel sous /opt/debriefmeet.

Build (sur le conteneur LXC, venv Python système 3.14 — décision L7) :
    pyinstaller packaging/linux/debriefMeet.spec --noconfirm --distpath dist --workpath build/work

Différences assumées avec le spec Windows :

* **Pas de ffmpeg embarqué** (décision L3) : le `.deb` déclare `Depends: ffmpeg`,
  `core/fichiers.chemin_ffmpeg()` résout /usr/bin/ffmpeg par le PATH même en figé.
* **Pas de pile de transcription locale** (décision L1, v1 = distant seul) :
  ni faster-whisper/ctranslate2, ni soundcard (loopback WASAPI, sans objet ici) —
  `_linux()` ne construit jamais de moteur, les embarquer serait ~100 Mo de lest.
  Les paquets sont aussi dans EXCLUDES : si l'un traîne dans le venv de build,
  il ne doit PAS grossir le bundle en silence.
* **Pas de tzdata** : la base de fuseaux système suffit (le piège était Windows-only).
* livekit (AEC3) reste : il nettoie la piste micro retenue même en mode distant
  (docs/48), et sa roue manylinux est vérifiée sur le conteneur.
"""
import os
import re

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")

# Version lue depuis le paquet (source unique de vérité) — le nom du dist reste
# "debriefMeet" quelle que soit VERSION_COMPLETE (portée par le .deb, pas le dossier).
_init = open(os.path.join(SRC, "debrief_meet", "__init__.py"), encoding="utf-8").read()
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _init).group(1)

ASSETS = os.path.join(SRC, "debrief_meet", "ui", "assets")

# ── Ressources embarquées ─────────────────────────────────────────────────────
datas = [
    (ASSETS, os.path.join("debrief_meet", "ui", "assets")),
]
binaries = []
hiddenimports = []

# livekit (AEC3) embarque des .so natives non détectées par l'analyse statique.
for paquet in ("livekit",):
    try:
        d, b, h = collect_all(paquet)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # paquet absent / non collectable → on continue
        print(f"[spec] collect_all({paquet}) ignoré : {exc}")

# Rien de macOS/Windows/diarization ni de moteur local dans le bundle Linux v1
# (docs/49 L1) — les paquets moteur sont exclus explicitement pour qu'une présence
# accidentelle dans le venv de build ne gonfle pas le .deb en silence.
EXCLUDES = [
    "tkinter", "pytest", "matplotlib",
    "mlx", "mlx_whisper", "pyannote", "torch",
    "faster_whisper", "ctranslate2", "soundcard",
]

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="debriefMeet",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="debriefMeet",
)
