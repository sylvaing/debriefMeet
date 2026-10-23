# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller — debriefMeet.app (macOS, arm64).

Produit une app barre de menus (LSUIElement) signable avec une identité stable
pour des permissions TCC persistantes. Les poids de modèles ne sont PAS embarqués
(mlx-whisper / pyannote les téléchargent à la volée).

Build : depuis le venv 3.13 dédié →
    .venv-build/bin/pyinstaller packaging/debriefMeet.spec --noconfirm
"""
import os
import re

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

# Version lue depuis le paquet (source unique de vérité).
_init = open(os.path.join(SRC, "debrief_meet", "__init__.py"), encoding="utf-8").read()
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _init).group(1)
# Info.plist : CFBundle*Version = entiers séparés par des points. Une rc ("0.4.1rc1",
# docs/53 §6) n'y garde que sa partie numérique ; l'app lit __version__, pas le plist.
VERSION_PLIST = re.match(r"\d+(?:\.\d+)*", VERSION).group(0)

BUNDLE_ID = "com.sylvaingarcia.debriefmeet"
ASSETS = os.path.join(SRC, "debrief_meet", "ui", "assets")
ICONE = os.path.join(ASSETS, "icons", "debriefMeet.icns")  # refonte design (handoff)
HELPER = os.path.join(ROOT, "helpers", "macos", "sck-audio", "SCKAudioCapture")
FFMPEG = os.path.join(ROOT, "packaging", "vendor", "ffmpeg")
FFMPEG_LICENSE = os.path.join(ROOT, "packaging", "vendor", "LICENSE-ffmpeg.md")
if not os.path.exists(FFMPEG):
    raise SystemExit(
        "packaging/vendor/ffmpeg introuvable — lancer d'abord :\n"
        "    bash packaging/build_ffmpeg.sh\n"
        "(docs/16-packaging-macos.md §5.5)"
    )
# PortAudio 19.7.0 + correctif amont #1175 (interblocage CoreAudio à l'arrêt d'un flux,
# docs/16 §5.7) : REMPLACE la dylib que le hook sounddevice collecte, sans quoi le micro
# peut rester ouvert après une réunion et l'app se figer à la sortie.
PORTAUDIO = os.path.join(ROOT, "packaging", "vendor", "libportaudio.dylib")
PORTAUDIO_LICENSE = os.path.join(ROOT, "packaging", "vendor", "LICENSE-portaudio.md")
PORTAUDIO_DEST = os.path.join("_sounddevice_data", "portaudio-binaries", "libportaudio.dylib")
if not os.path.exists(PORTAUDIO):
    raise SystemExit(
        "packaging/vendor/libportaudio.dylib introuvable — lancer d'abord :\n"
        "    bash packaging/build_portaudio.sh\n"
        "(docs/16-packaging-macos.md §5.7)"
    )

# ── Ressources embarquées ─────────────────────────────────────────────────────
# Assets UI : résolus via Path(__file__).parent/"assets" → cible debrief_meet/ui/assets.
# Helper Swift : résolu via chemin_ressource("helpers","macos","sck-audio",...) → même
# chemin relatif sous _MEIPASS.
# ffmpeg (LGPL, compilé par build_ffmpeg.sh) : résolu via chemin_ressource("vendor","ffmpeg").
datas = [
    (ASSETS, os.path.join("debrief_meet", "ui", "assets")),
    (HELPER, os.path.join("helpers", "macos", "sck-audio")),
    (FFMPEG, "vendor"),
    (FFMPEG_LICENSE, "vendor"),
    (PORTAUDIO_LICENSE, "vendor"),
]
binaries = []
hiddenimports = [
    "debrief_meet.platform.macos._mlx_worker",  # relancé via --mlx-worker
]

# ── Dépendances lourdes (ML) ───────────────────────────────────────────────────
# torch / torchaudio / sounddevice / sklearn / numba ont des hooks contrib fiables.
# On collecte explicitement le reste (données + sous-modules souvent ratés).
for paquet in (
    "mlx",
    "mlx_whisper",
    "pyannote",
    "pyannote.audio",
    "lightning",
    "pytorch_lightning",
    "lightning_fabric",
    "asteroid_filterbanks",
    "julius",
    "torch_pitch_shift",
    "torch_audiomentations",
    "pytorch_metric_learning",
    "speechbrain",
    "livekit",
    "huggingface_hub",
    "tiktoken",
    "transformers",
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
    excludes=["tkinter", "pytest", "matplotlib"],  # inutiles à l'app packagée
    cipher=block_cipher,
    noarchive=False,
)

# Substitution de la dylib PortAudio (cf. PORTAUDIO ci-dessus) : même chemin de
# destination, seule la source change. Exactement une entrée attendue — zéro voudrait
# dire que le hook sounddevice a changé de layout et que l'app livrerait la dylib
# fautive sans que rien ne le signale.
binaires_app = []
substitutions = 0
for dest, source, type_toc in a.binaries:
    if os.path.normpath(dest) == PORTAUDIO_DEST:
        source = PORTAUDIO
        substitutions += 1
    binaires_app.append((dest, source, type_toc))
if substitutions != 1:
    raise SystemExit(
        f"[spec] {substitutions} entrée(s) {PORTAUDIO_DEST} dans a.binaries (1 attendue) — "
        "le hook sounddevice a changé : revoir la substitution PortAudio (docs/16 §5.7)."
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
    target_arch="arm64",
)

coll = COLLECT(
    exe,
    binaires_app,
    a.datas,
    strip=False,
    upx=False,
    name="debriefMeet",
)

app = BUNDLE(
    coll,
    name="debriefMeet.app",
    icon=ICONE,
    bundle_identifier=BUNDLE_ID,
    version=VERSION_PLIST,
    info_plist={
        "CFBundleName": "debriefMeet",
        "CFBundleDisplayName": "debriefMeet",
        "CFBundleShortVersionString": VERSION_PLIST,
        "CFBundleVersion": VERSION_PLIST,
        "LSMinimumSystemVersion": "14.4",
        "LSUIElement": True,  # app barre de menus, pas d'icône Dock
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            "debriefMeet transcrit votre voix localement (dictée, réunion, journal).",
        "NSAudioCaptureUsageDescription":
            "debriefMeet capture l'audio des participants pour transcrire vos réunions.",
    },
)
