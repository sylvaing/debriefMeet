# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller — debriefMeet (Windows, onedir).

Mode onedir (pas onefile) : démarrage rapide, DLL lourdes (ctranslate2, Qt) — Inno
Setup gère très bien un dossier de fichiers (docs/32 §3.2). Les poids de modèles ne
sont PAS embarqués (faster-whisper les télécharge à la demande, docs/34 §1.3).

Build (sur la VM, venv Python 3.13) :
    pyinstaller packaging/windows/debriefMeet.spec --noconfirm --distpath dist --workpath build/work

Variante debug (console visible — utile pour déboguer à distance sans machine
Windows de dev) : définir DEBRIEFMEET_CONSOLE=1 dans l'environnement avant de
lancer pyinstaller. v1 livrée en console=False.
"""
import os
import re

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")

# Version lue depuis le paquet (source unique de vérité) — le nom du dist reste
# "debriefMeet" quelle que soit VERSION_COMPLETE (portée par le setup, pas le dossier).
_init = open(os.path.join(SRC, "debrief_meet", "__init__.py"), encoding="utf-8").read()
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _init).group(1)

ASSETS = os.path.join(SRC, "debrief_meet", "ui", "assets")
# SPECPATH (fourni par PyInstaller) et pas __file__ : le spec est exécuté via
# exec(), sans __file__ défini.
ICONE = os.path.join(SPECPATH, "debriefMeet.ico")

CONSOLE = os.environ.get("DEBRIEFMEET_CONSOLE") == "1"

# ── Ressources embarquées ─────────────────────────────────────────────────────
datas = [
    (ASSETS, os.path.join("debrief_meet", "ui", "assets")),
]
binaries = []
hiddenimports = [
    "debrief_meet.platform.windows._fw_worker",  # relancé via --fw-worker
]

# ffmpeg embarqué (lgpl BtbN, rétention Opus — docs/41) : téléchargé par
# telecharger_ffmpeg.cmd, jamais commité. Échec dur si absent : le spec ne
# tourne que sur la VM, toujours après cette étape du build.
FFMPEG_EXE = os.path.join(SPECPATH, "ffmpeg", "ffmpeg.exe")
FFMPEG_LICENCE = os.path.join(SPECPATH, "ffmpeg", "LICENSE.txt")
if not os.path.exists(FFMPEG_EXE):
    raise SystemExit(
        "[spec] ffmpeg.exe manquant — lancer packaging/windows/telecharger_ffmpeg.cmd "
        "(appelé normalement par build_app.cmd)")
binaries.append((FFMPEG_EXE, "ffmpeg"))
datas.append((FFMPEG_LICENCE, "ffmpeg"))

# ── Dépendances lourdes (moteur CT2, loopback, AEC) ────────────────────────────
# ctranslate2/faster-whisper embarquent des DLL natives + données de config non
# détectées par l'analyse statique de PyInstaller sans collect_all.
for paquet in (
    "faster_whisper",
    "ctranslate2",
    "huggingface_hub",
    "tokenizers",
    "soundcard",
    "livekit",
):
    try:
        d, b, h = collect_all(paquet)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # paquet absent / non collectable → on continue
        print(f"[spec] collect_all({paquet}) ignoré : {exc}")

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Rien de macOS/diarization dans le bundle Windows v1 (docs/33 §2.7, docs/30 §8).
    excludes=["tkinter", "pytest", "matplotlib", "mlx", "mlx_whisper", "pyannote", "torch"],
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
    console=CONSOLE,
    icon=ICONE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="debriefMeet",
)
