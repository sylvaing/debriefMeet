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

Édition compilée : lue dans `src/debrief_meet/_version.py` (généré par
generer_version.py --edition, étape 3/6 de build_app.cmd) — source UNIQUE de vérité,
partagée avec le module `core/edition.py` embarqué. En lite, toute la pile de
transcription locale sort du bundle (docs/44).
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


def _edition_compilee():
    """Édition lue dans `_version.py` (généré juste avant ce spec, build_app.cmd 3/6).

    Pas de variable d'environnement : le module `core/edition.py` embarqué lit le MÊME
    fichier, donc les `excludes` ci-dessous et le comportement à l'exécution ne peuvent
    pas se contredire — un bundle privé de ctranslate2 mais dont l'app se croit complète
    proposerait une transcription locale qui meurt au premier usage. Fichier absent
    (pyinstaller lancé à la main) → édition complète.
    """
    try:
        contenu = open(os.path.join(SRC, "debrief_meet", "_version.py"), encoding="utf-8").read()
    except OSError:
        return "complete"
    m = re.search(r'EDITION_COMPILEE\s*=\s*"([^"]+)"', contenu)
    return m.group(1) if m else "complete"


EDITION = _edition_compilee()
LITE = EDITION == "lite"
print(f"[spec] edition = {EDITION}")

# ── Ressources embarquées ─────────────────────────────────────────────────────
datas = [
    (ASSETS, os.path.join("debrief_meet", "ui", "assets")),
]
binaries = []
hiddenimports = []
if not LITE:
    # Relancé via --fw-worker ; aucun moteur local en lite → aucun worker à relancer.
    hiddenimports.append("debrief_meet.platform.windows._fw_worker")

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
PAQUETS_MOTEUR_LOCAL = ("faster_whisper", "ctranslate2", "huggingface_hub", "tokenizers")
PAQUETS_COMMUNS = ("soundcard", "livekit")   # loopback WASAPI + AEC3 : les DEUX éditions
for paquet in (PAQUETS_COMMUNS if LITE else PAQUETS_MOTEUR_LOCAL + PAQUETS_COMMUNS):
    try:
        d, b, h = collect_all(paquet)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # paquet absent / non collectable → on continue
        print(f"[spec] collect_all({paquet}) ignoré : {exc}")

# Rien de macOS/diarization dans le bundle Windows (docs/33 §2.7, docs/30 §8).
EXCLUDES = ["tkinter", "pytest", "matplotlib", "mlx", "mlx_whisper", "pyannote", "torch"]
# Lite : toute la pile de transcription locale sort (docs/44). `av` et `onnxruntime` ne
# sont JAMAIS importés par notre code (zéro occurrence dans src/) — ils n'entrent que
# via faster_whisper, mais _pyinstaller_hooks_contrib fournit un hook dédié pour chacun
# (hook-av.py, hook-onnxruntime.py) : il faut donc les exclure NOMMÉMENT, sinon ils
# restent dans le bundle (~41 Mo de wheel à eux deux, le plus gros du gain).
# `hf_xet` est tiré par huggingface_hub 1.x (ceinture + bretelles).
EXCLUDES_LITE = ["faster_whisper", "ctranslate2", "tokenizers", "huggingface_hub",
                 "hf_xet", "onnxruntime", "av"]

block_cipher = None

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=(EXCLUDES + EXCLUDES_LITE) if LITE else EXCLUDES,
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
