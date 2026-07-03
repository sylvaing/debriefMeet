"""Assemble un bundle portable du benchmark — SANS installation côté cible.

Tourne sur le Mac (ou n'importe quel poste de dev). Produit un dossier zippé
contenant : un Python « embeddable », les wheels de l'OS cible posées par
`pip --target` (sans exécution), les sources benchmark + debrief_meet, les
modèles et l'audio. L'utilisateur dézippe et double-clique le lanceur — aucun
`pip install`, aucun réseau, aucun droit admin.

⚠ Contraintes : voir docs/08-benchmark.md.
- Windows : assemblable depuis le Mac (wheels `--platform win_amd64`).
- Linux : passer par Docker `linux/amd64` (pip --target manylinux), cf. doc.
- `--only-binary=:all:` exige que toute dépendance ait une wheel pour la cible :
  utiliser `--verifier` AVANT pour détecter une dépendance sans wheel.
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RACINE_BENCH = Path(__file__).resolve().parent
RACINE_PROJET = RACINE_BENCH.parent
SRC_DEBRIEF = RACINE_PROJET / "src" / "debrief_meet"
MODELES_SHERPA_SPIKE = RACINE_PROJET / "spike" / "diarization" / "models"

PY_VERSION = "3.11"
# Python embeddable Windows — https://www.python.org/downloads/windows/
PY_EMBED_VERSION = "3.11.9"
PY_EMBED_URL = (
    "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
)
# Python portable relocatable (Linux/macOS) — astral-sh/python-build-standalone.
# Le tarball `install_only` s'extrait en un dossier `python/` (bin/python3, lib/…).
PY_STANDALONE_TAG = "20260610"
PY_STANDALONE_FICHIERS = {
    "linux": "cpython-3.11.15+{tag}-x86_64-unknown-linux-gnu-install_only.tar.gz",
    "macos-intel": "cpython-3.11.15+{tag}-x86_64-apple-darwin-install_only.tar.gz",
}
PY_STANDALONE_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    "{tag}/{fichier}"
)

# Plateformes pip par OS cible (la plus compatible en premier).
PLATEFORMES = {
    "windows": ["win_amd64"],
    "linux": ["manylinux2014_x86_64", "manylinux_2_17_x86_64"],
    "macos-intel": [
        "macosx_10_9_x86_64", "macosx_10_13_x86_64", "macosx_10_15_x86_64",
        "macosx_11_0_x86_64", "macosx_12_0_x86_64",
        "macosx_10_9_universal2", "macosx_11_0_universal2",
    ],
}

# Dépendances tierces embarquées (wheels). PySide6 inutile : le benchmark
# n'importe que core.audio / core.aec / platform.interfaces / core.modeles.
DEPS_TIERS = [
    "faster-whisper",
    "sherpa-onnx",
    # community-1 exige pyannote 4 ; sans pin, pip recule jusqu'à 1.1 (incompatible).
    "pyannote.audio>=4",
    # `torch<2.9` = série CUDA 12 (pilote NVIDIA ≥ R525, très répandu). torch ≥ 2.9 bascule
    # sur CUDA 13 (pilote ≥ R580, plus rare). cf. docs/08 + mémoire benchmark.
    "torch<2.9",
    "torchaudio",
    "numpy",
    "scipy",
    "sounddevice",
    # soundcard : capture loopback WASAPI sur Windows (sounddevice/PortAudio n'expose
    # aucun flag loopback). Pur Python + cffi (cffi est déjà tiré par sounddevice).
    "soundcard",
    "soundfile",
    "psutil",
    "py-cpuinfo",
    "huggingface-hub",
    "livekit",
]

# torch n'a plus de wheel macOS x86_64 (≥2.3 = arm64 uniquement) → toute la chaîne
# pyannote s'écroule (pip rétrograde jusqu'à pyannote.audio 1.1, incompatible avec
# le modèle community-1). Sur Intel Mac : transcription faster-whisper + diarisation
# sherpa (ONNX, sans torch). pyannote est signalé absent dans le rapport.
DEPS_SANS_TORCH = [d for d in DEPS_TIERS
                   if not d.startswith(("torch", "pyannote"))]

# Comparatif OpenVINO (GPU Intel) — Windows/Linux uniquement (pas de wheel
# OpenVINO macOS x86_64). optimum-intel tire openvino, transformers, nncf, torch
# (déjà présent), etc. Ajouté seulement sur les cibles qui ont torch.
DEPS_OPENVINO = ["optimum-intel[openvino]", "transformers"]


def supporte_openvino(os_cible: str) -> bool:
    return os_cible in ("windows", "linux")


def deps_pour(os_cible: str) -> list[str]:
    base = DEPS_SANS_TORCH if os_cible == "macos-intel" else list(DEPS_TIERS)
    if supporte_openvino(os_cible):
        base = base + DEPS_OPENVINO
    return base


def supporte_pyannote(os_cible: str) -> bool:
    return os_cible != "macos-intel"


# Modèles faster-whisper à pré-télécharger (un repo par taille).
REPOS_FASTER_WHISPER = {
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def _pth_avec_libs(contenu: str) -> str:
    """Adapte le `._pth` d'un Python embeddable Windows pour le bundle.

    Ajoute `..\\libs` à `sys.path` (le dossier des sources + wheels, relatif au dossier
    `python\\`) et active `import site`. Indispensable : l'embeddable **ignore
    `PYTHONPATH`** dès qu'un `._pth` existe — sans cette ligne, `python -m benchmark`
    échoue par « No module named benchmark ». Idempotent."""
    contenu = contenu.replace("#import site", "import site")
    if "..\\libs" not in contenu:
        contenu = contenu.rstrip() + "\n..\\libs\n"
    return contenu


def telecharger_python_embeddable(bundle: Path, os_cible: str,
                                   version: str = PY_EMBED_VERSION) -> None:
    """Télécharge et extrait un Python portable dans bundle/python/.

    - Windows : Python « embeddable » officiel. ⚠ L'embeddable IGNORE `PYTHONPATH`
      tant qu'un `._pth` existe → on déclare le dossier des libs (``..\\libs``)
      directement dans le `._pth`, et on active `import site` (wheels avec `.pth`).
    - Linux / macOS Intel : build relocatable `python-build-standalone`
      (s'extrait en `python/bin/python3` — ce qu'attend lancer.sh/.command).
    """
    if os_cible == "windows":
        url = PY_EMBED_URL.format(v=version)
        print(f"  Python embeddable {version} ← {url}")
        with urllib.request.urlopen(url) as resp:  # noqa: S310
            data = resp.read()
        python_dir = bundle / "python"
        python_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(python_dir)
        # L'embeddable ignore PYTHONPATH quand un ._pth existe : on ajoute le dossier
        # des libs (`..\libs`, relatif au dossier python\) DANS le ._pth, sinon
        # `python -m benchmark` échoue avec « No module named benchmark ».
        for pth in python_dir.glob("python3*._pth"):
            pth.write_text(_pth_avec_libs(pth.read_text(encoding="utf-8")),
                           encoding="utf-8")
            print(f"  ._pth : ..\\libs ajouté + import site activé ({pth.name})")
    elif os_cible in PY_STANDALONE_FICHIERS:
        fichier = PY_STANDALONE_FICHIERS[os_cible].format(tag=PY_STANDALONE_TAG)
        url = PY_STANDALONE_URL.format(tag=PY_STANDALONE_TAG, fichier=fichier)
        print(f"  Python standalone ← {url}")
        with urllib.request.urlopen(url) as resp:  # noqa: S310
            data = resp.read()
        bundle.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            # Le tarball contient un dossier racine `python/` → extrait tel quel.
            # On EXCLUT share/terminfo/ : ses centaines de symlinks entrent en
            # collision sur le FS insensible à la casse de macOS (ELOOP). Inutile
            # au benchmark (curses uniquement ; sur la cible Linux, le terminfo
            # système prend le relais). Filtre `fully_trusted` : source de
            # confiance (release officielle astral-sh), pas de validation realpath.
            membres = [m for m in tf.getmembers()
                       if "/share/terminfo/" not in m.name]
            try:
                tf.extractall(bundle, members=membres, filter="fully_trusted")
            except TypeError:
                tf.extractall(bundle, members=membres)


def generer_lanceur(os_cible: str) -> str:
    """Contenu du script de lancement : configure le path et lance, sans rien installer."""
    if os_cible == "windows":
        return (
            "@echo off\r\n"
            "REM Lanceur benchmark debriefMeet — aucune installation.\r\n"
            "setlocal\r\n"
            "set BASE=%~dp0\r\n"
            "set PYTHONPATH=%BASE%libs\r\n"
            "set HF_HUB_OFFLINE=1\r\n"
            "set TRANSFORMERS_OFFLINE=1\r\n"
            'set BENCH_MODELS=%BASE%libs\\benchmark\\assets\\models\r\n'
            '"%BASE%python\\python.exe" -m benchmark %*\r\n'
            "echo.\r\n"
            "pause\r\n"
        )
    # macOS : lève en plus la quarantaine Gatekeeper sur le Python téléchargé.
    quarantaine = ('xattr -dr com.apple.quarantine "$BASE" 2>/dev/null || true\n'
                   if os_cible == "macos-intel" else "")
    return (
        "#!/bin/sh\n"
        "# Lanceur benchmark debriefMeet — aucune installation.\n"
        'BASE="$(cd "$(dirname "$0")" && pwd)"\n'
        'export PYTHONPATH="$BASE/libs"\n'
        "export HF_HUB_OFFLINE=1\n"
        "export TRANSFORMERS_OFFLINE=1\n"
        'export BENCH_MODELS="$BASE/libs/benchmark/assets/models"\n'
        "# Restaure le bit exécutable si l'archive a été extraite via une GUI.\n"
        'chmod +x "$BASE/python/bin/python3" 2>/dev/null || true\n'
        + quarantaine +
        '"$BASE/python/bin/python3" -m benchmark "$@"\n'
    )


def _pip(args: list[str]) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def _args_wheels(libs: Path, os_cible: str, py_version: str, natif: bool) -> list[str]:
    """Arguments `pip install --target` pour poser les wheels (sans les exécuter).

    - `natif=False` (défaut, build **croisé** depuis le Mac) : on force la cible via
      `--platform/--python-version/--implementation`. ⚠ pip évalue alors les *markers*
      (`platform_system`) contre le Mac → les deps CUDA de torch (gated `== "Linux"`)
      sont écartées (bundle GPU cassé). OK pour les cibles sans GPU torch.
    - `natif=True` (build **sur la cible** : linux x86_64, Python 3.11) : résolution
      native → markers corrects (CUDA tirée), pas d'explosion multi-tags. Réservé au cas
      host == cible. cf. docs/08 + mémoire benchmark."""
    args = ["install", "--target", str(libs), "--only-binary=:all:"]
    if not natif:
        args += ["--python-version", py_version, "--implementation", "cp"]
        for p in PLATEFORMES[os_cible]:
            args += ["--platform", p]
    return args + deps_pour(os_cible)


def telecharger_wheels(libs: Path, os_cible: str, py_version: str = PY_VERSION,
                       natif: bool = False) -> None:
    """Pose les wheels de l'OS cible dans `libs` SANS les exécuter (pip --target)."""
    libs.mkdir(parents=True, exist_ok=True)
    _pip(_args_wheels(libs, os_cible, py_version, natif))


def copier_sources(libs: Path) -> None:
    """Copie les paquets benchmark + debrief_meet dans le bundle."""
    shutil.copytree(RACINE_BENCH, libs / "benchmark",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    dirs_exist_ok=True)
    shutil.copytree(SRC_DEBRIEF, libs / "debrief_meet",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    dirs_exist_ok=True)


def telecharger_modeles(models: Path, token: str | None, tailles: list[str],
                        avec_pyannote: bool = True, avec_openvino: bool = False) -> None:
    """Pré-télécharge tous les modèles dans le bundle (une fois, sur le Mac)."""
    from huggingface_hub import snapshot_download

    from benchmark import modeles as mdl

    models.mkdir(parents=True, exist_ok=True)
    for taille in tailles:
        repo = REPOS_FASTER_WHISPER[taille]
        print(f"  faster-whisper {taille} ← {repo}")
        snapshot_download(repo, local_dir=models / f"faster-whisper-{taille}")
    # sherpa-onnx : copie depuis le spike (déjà téléchargés, sans licence).
    if MODELES_SHERPA_SPIKE.exists():
        print("  sherpa-onnx ← spike/diarization/models")
        shutil.copytree(MODELES_SHERPA_SPIKE, models, dirs_exist_ok=True)
    # OpenVINO INT8 (GPU Intel, Windows/Linux) : modèles publics pré-convertis.
    if avec_openvino:
        for taille in tailles:
            repo = mdl.TABLE_OPENVINO[taille]
            print(f"  openvino {taille} ← {repo}")
            snapshot_download(repo, local_dir=models / f"openvino-whisper-{taille}")
    # pyannote inutilisable sur certaines cibles (pas de torch) → on ne l'embarque pas.
    if not avec_pyannote:
        print("  pyannote : non embarqué (cible sans torch)")
        return
    # pyannote (gated) : cache HF embarqué, token requis ICI seulement.
    dest_pyannote = models / "pyannote-community-1"
    if token:
        print("  pyannote (gated) ← HF (avec token)")
        snapshot_download("pyannote/speaker-diarization-community-1",
                          local_dir=dest_pyannote, token=token)
    else:
        # Tenter depuis le cache local (modèle déjà téléchargé avec token auparavant).
        # local_files_only=True ne fonctionne pas avec local_dir → récupérer d'abord
        # le chemin du cache, puis copier manuellement.
        print("  pyannote (gated) ← cache local (token absent)")
        try:
            cache_path = snapshot_download(
                "pyannote/speaker-diarization-community-1",
                local_files_only=True)
            shutil.copytree(cache_path, dest_pyannote, dirs_exist_ok=True)
            print(f"  pyannote copié depuis {cache_path}")
        except Exception as exc:
            print(f"  ⚠ pyannote : cache local absent ({exc}).\n"
                  "    Relancer avec HF_TOKEN=hf_xxx pour embarquer pyannote.",
                  file=sys.stderr)


def verifier_wheels(os_cible: str, paquets: list[str] | None = None,
                    py_version: str = PY_VERSION) -> dict:
    """Vérifie que chaque paquet a une wheel pour l'OS cible (résout le risque tôt).

    Retourne {paquet: ok/ko}. Télécharge la wheel (--no-deps) dans un dossier jetable.
    """
    paquets = paquets or deps_pour(os_cible)
    plateformes = PLATEFORMES[os_cible]
    resultats: dict[str, bool] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for pkg in paquets:
            args = ["download", "--no-deps", "--only-binary=:all:", "-d", tmp,
                    "--python-version", py_version, "--implementation", "cp"]
            for p in plateformes:
                args += ["--platform", p]
            args.append(pkg)
            try:
                subprocess.run([sys.executable, "-m", "pip", *args],
                               check=True, capture_output=True, text=True)
                resultats[pkg] = True
            except subprocess.CalledProcessError as exc:
                print(f"  ✗ {pkg} : pas de wheel {os_cible}\n{exc.stderr}", file=sys.stderr)
                resultats[pkg] = False
    return resultats


def assembler(os_cible: str, sortie: Path, token: str | None,
              tailles: list[str] | None = None, natif: bool = False) -> Path:
    """Assemble le bundle complet et le zippe. Retourne le chemin du zip."""
    from benchmark import modeles as mdl

    tailles = tailles or mdl.SWEEP
    bundle = sortie / f"benchmark-{os_cible}"
    libs = bundle / "libs"
    bundle.mkdir(parents=True, exist_ok=True)

    print(f"[1/6] Wheels {os_cible} → libs/{' (natif)' if natif else ''}")
    telecharger_wheels(libs, os_cible, natif=natif)
    print("[2/6] Sources benchmark + debrief_meet")
    copier_sources(libs)
    print("[3/6] Modèles + audio")
    telecharger_modeles(libs / "benchmark" / "assets" / "models", token, tailles,
                        avec_pyannote=supporte_pyannote(os_cible),
                        avec_openvino=supporte_openvino(os_cible))
    print("[4/6] Python portable")
    telecharger_python_embeddable(bundle, os_cible)
    print("[5/6] Lanceur")
    nom_lanceur = {"windows": "lancer.bat",
                   "macos-intel": "lancer.command"}.get(os_cible, "lancer.sh")
    lanceur = bundle / nom_lanceur
    lanceur.write_text(generer_lanceur(os_cible), encoding="utf-8")
    if os_cible != "windows":
        lanceur.chmod(0o755)
    print("[6/6] Zip")
    archive = sortie / f"benchmark-{os_cible}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(bundle.rglob("*")):
            # is_file() suit les symlinks (python/bin/python3 → contenu réel).
            if f.is_file():
                zf.write(f, f.relative_to(bundle.parent))
    # Le dossier non-zippé est un doublon du zip (plusieurs Go) → on le supprime.
    shutil.rmtree(bundle, ignore_errors=True)
    print(f"✓ {archive}")
    return archive


def main(argv: list[str] | None = None) -> int:
    # Les messages de progression contiennent → ✓ ✗ : sous Windows, stdout est en cp1252
    # quand redirigé vers un fichier → UnicodeEncodeError. On force UTF-8 (no-op ailleurs).
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Assemble un bundle portable du benchmark")
    ap.add_argument("--os", dest="os_cible",
                    choices=["windows", "linux", "macos-intel"], required=True)
    ap.add_argument("--sortie", type=Path, default=Path.cwd() / "bundles")
    ap.add_argument("--token", default=None, help="Token HF (pyannote gated).")
    ap.add_argument("--verifier", action="store_true",
                    help="Vérifie seulement la disponibilité des wheels (rapide).")
    ap.add_argument("--natif", action="store_true",
                    help="Résolution native (build SUR la cible : même OS/arch/Python 3.11). "
                         "Indispensable pour embarquer CUDA sous Linux.")
    args = ap.parse_args(argv)

    if args.verifier:
        res = verifier_wheels(args.os_cible)
        manquants = [p for p, ok in res.items() if not ok]
        print("\nWheels :", {p: ("ok" if ok else "MANQUANTE") for p, ok in res.items()})
        if manquants:
            print(f"✗ Sans wheel {args.os_cible} : {manquants}", file=sys.stderr)
            return 1
        print(f"✓ Toutes les dépendances ont une wheel {args.os_cible}.")
        return 0

    assembler(args.os_cible, args.sortie, args.token, natif=args.natif)
    return 0


if __name__ == "__main__":
    sys.exit(main())
