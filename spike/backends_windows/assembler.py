"""Assembleur bundle portable spike backends Windows.

Adapté de benchmark/assembler_bundle.py pour le spike.
Bundle : Python embeddable + wheels + sources spike + modèles × 4 backends + binaire Vulkan
(whisper-cli.exe, tiers — cf. WHISPER_CLI_URL, doc 18 §13.6).
Lanceur : lancer.bat (Windows) — dézipper + double-cliquer, aucun pip, aucun réseau.

Build NATIF sur la VM Proxmox (voir scripts/build_spike_backends_vm.sh).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from spike.backends_windows import chemins
from spike.backends_windows import modeles as mdl

RACINE_SPIKE = Path(__file__).resolve().parent
RACINE_PROJET = RACINE_SPIKE.parent.parent
SRC_DEBRIEF = RACINE_PROJET / "src" / "debrief_meet"

PY_VERSION = "3.11"
PY_EMBED_VERSION = "3.11.9"
PY_EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"

# Dépendances spike (Windows uniquement — le bundle cible win_amd64).
DEPS_SPIKE = [
    "faster-whisper",
    "optimum-intel[openvino]",
    "onnxruntime-directml",
    "optimum[onnxruntime]",
    "transformers",
    "numpy",
    "scipy",
    "psutil",
    "py-cpuinfo",
    "huggingface-hub",
]

# Repos faster-whisper.
REPOS_FASTER_WHISPER = {
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
}

# Repos OpenVINO INT8.
REPOS_OPENVINO = {
    "small": "OpenVINO/whisper-small-int8-ov",
    "medium": "OpenVINO/whisper-medium-int8-ov",
    "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
    # turbo OV : converti en natif via optimum-cli (voir note ci-dessous)
}

# Modèles ONNX pré-convertis (compatible ORTModelForSpeechSeq2Seq).
# Évite torch + optimum au build — pas de conversion à la volée.
# Note : onnx-community/whisper-medium n'existe pas (401) → Xenova/whisper-medium.
# Xenova est l'ancienne org d'onnx-community ; même format, même structure onnx/.
REPOS_DIRECTML_ONNX = {
    "small": "onnx-community/whisper-small",
    "medium": "Xenova/whisper-medium",        # onnx-community/whisper-medium : 401
    "large-v3": "Xenova/whisper-large-v3",    # onnx-community/whisper-large-v3 : 401
    "large-v3-turbo": "onnx-community/whisper-large-v3-turbo",
}

# URLs ggml quantifiés (GitHub releases ggerganov/whisper.cpp).
# q5_0 : n'existe pas pour "small" (404) → q5_1 (même tier 5 bits) — doc 18 §12.4.
GGML_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
GGML_FICHIERS = {
    "small": "ggml-small-q5_1.bin",
    "medium": "ggml-medium-q5_0.bin",
    "large-v3": "ggml-large-v3-q5_0.bin",
    "large-v3-turbo": "ggml-large-v3-turbo-q5_0.bin",
}

# large-v3-turbo n'a pas de repo OpenVINO public — conversion locale (Mac), cf. doc 18 §12.2.
OV_TURBO_MODEL_ID = "openai/whisper-large-v3-turbo"

# whisper-cli.exe (Vulkan) : ggml-org/whisper.cpp ne publie aucun binaire Windows Vulkan
# officiel (issue upstream ggml-org/whisper.cpp#3673, toujours ouverte). Fork tiers retenu
# car buildé par CI GitHub Actions depuis les sources upstream (le plus traçable des tiers
# évalués), pas un exécutable uploadé à la main — doc 18 §13.6. Empreinte SHA256 pinnée :
# intégrité + reproductibilité (même binaire à chaque build).
WHISPER_CLI_URL = "https://github.com/jonasthilo/whisper.cpp/releases/download/v1.8.5/whisper-vulkan-bin-x64.zip"
WHISPER_CLI_SHA256 = "a28d7e4e3ce204c5b9771b329240c9d10d6f1b76f43d0439cf0d36972c0333ff"
WHISPER_CLI_FICHIERS = [
    "whisper-cli.exe",
    "ggml.dll",
    "ggml-base.dll",
    "ggml-cpu.dll",
    "ggml-vulkan.dll",
    "whisper.dll",
]


def whisper_cli_manquants(assets_dir: Path) -> list[str]:
    return [nom for nom in WHISPER_CLI_FICHIERS if not (assets_dir / nom).is_file()]


def telecharger_whisper_cli(assets_dir: Path) -> None:
    """Télécharge whisper-cli.exe + DLLs Vulkan (binaire tiers, doc 18 §13.6)."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    if not whisper_cli_manquants(assets_dir):
        print(f"  whisper-cli.exe (Vulkan) : déjà présent ({assets_dir})")
        return
    print(f"  whisper-cli.exe (Vulkan) ← {WHISPER_CLI_URL}")
    with urllib.request.urlopen(WHISPER_CLI_URL) as resp:  # noqa: S310
        data = resp.read()
    empreinte = hashlib.sha256(data).hexdigest()
    if empreinte != WHISPER_CLI_SHA256:
        raise ValueError(
            f"whisper-cli : empreinte SHA256 inattendue ({empreinte}), "
            f"attendu {WHISPER_CLI_SHA256} — binaire tiers potentiellement altéré, abandon.")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        noms_zip = set(zf.namelist())
        for nom in WHISPER_CLI_FICHIERS:
            if nom not in noms_zip:
                raise ValueError(f"whisper-cli : fichier {nom!r} absent de l'archive {WHISPER_CLI_URL}")
            with zf.open(nom) as src, open(assets_dir / nom, "wb") as dst:
                dst.write(src.read())

PLATEFORMES_WINDOWS = ["win_amd64"]


def _pip(args: list[str]) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def _pth_avec_libs(contenu: str) -> str:
    contenu = contenu.replace("#import site", "import site")
    if "..\\libs" not in contenu:
        contenu = contenu.rstrip() + "\n..\\libs\n"
    return contenu


def telecharger_python_embeddable(bundle: Path, version: str = PY_EMBED_VERSION) -> None:
    url = PY_EMBED_URL.format(v=version)
    print(f"  Python embeddable {version} ← {url}")
    with urllib.request.urlopen(url) as resp:  # noqa: S310
        data = resp.read()
    python_dir = bundle / "python"
    python_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(python_dir)
    for pth in python_dir.glob("python3*._pth"):
        pth.write_text(_pth_avec_libs(pth.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"  ._pth : ..\\libs ajouté + import site activé ({pth.name})")


def telecharger_wheels(libs: Path, natif: bool = False) -> None:
    libs.mkdir(parents=True, exist_ok=True)
    args = ["install", "--target", str(libs), "--only-binary=:all:"]
    if not natif:
        args += ["--python-version", PY_VERSION, "--implementation", "cp"]
        for p in PLATEFORMES_WINDOWS:
            args += ["--platform", p]
    args += DEPS_SPIKE
    _pip(args)


def copier_sources(libs: Path) -> None:
    shutil.copytree(RACINE_SPIKE.parent, libs / "spike",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "assets"),
                    dirs_exist_ok=True)
    shutil.copytree(SRC_DEBRIEF, libs / "debrief_meet",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    dirs_exist_ok=True)


def convertir_openvino_turbo(dest: Path) -> None:
    """Convertit large-v3-turbo en OpenVINO (aucun repo public — doc 18 §12.2).

    Nécessite torch + optimum-intel[openvino] dans l'environnement d'exécution
    (jamais dans DEPS_SPIKE, réservé aux wheels du bundle Windows) — à faire
    tourner côté Mac (scripts/prebuild_spike_modeles.sh), jamais sur la VM.
    """
    if dest.exists() and any(dest.iterdir()):
        print(f"  openvino large-v3-turbo : déjà converti ({dest})")
        return
    print(f"  openvino large-v3-turbo ← conversion locale de {OV_TURBO_MODEL_ID} (optimum-cli)")
    dest.mkdir(parents=True, exist_ok=True)
    # optimum-cli est un script installé dans le même bin/ que sys.executable —
    # ne pas dépendre de PATH (le venv de prebuild n'est pas forcément "activé").
    optimum_cli = shutil.which("optimum-cli") or str(Path(sys.executable).parent / "optimum-cli")
    subprocess.run([
        optimum_cli, "export", "openvino",
        "--model", OV_TURBO_MODEL_ID,
        "--weight-format", "int8",
        str(dest),
    ], check=True)
    # optimum-cli n'écrit que le tokenizer *fast* (tokenizer.json), mais le moteur
    # charge le processeur avec use_fast=False (correctif commit 30ddbcb) — le
    # tokenizer lent WhisperTokenizer exige vocab.json + merges.txt, absents de
    # l'export. Les autres repos OpenVINO/whisper-*-int8-ov les fournissent ; le
    # turbo étant le seul converti localement était le seul incomplet (doc 39 §1).
    from transformers import WhisperFeatureExtractor, WhisperTokenizer
    WhisperTokenizer.from_pretrained(OV_TURBO_MODEL_ID).save_pretrained(dest)      # vocab.json + merges.txt
    WhisperFeatureExtractor.from_pretrained(OV_TURBO_MODEL_ID).save_pretrained(dest)  # preprocessor_config.json


def _backend_actif(nom: str, backends: list[str] | None) -> bool:
    """backends=None → comportement historique (tous les backends)."""
    return backends is None or nom in backends


def telecharger_modeles(models_dir: Path, tailles: list[str], backends: list[str] | None = None) -> None:
    from huggingface_hub import snapshot_download
    models_dir.mkdir(parents=True, exist_ok=True)

    if _backend_actif("faster-whisper", backends):
        for taille in tailles:
            if taille in REPOS_FASTER_WHISPER:
                dest = models_dir / f"faster-whisper-{taille}"
                if dest.exists():
                    print(f"  faster-whisper {taille} : déjà présent ({dest})")
                    continue
                repo = REPOS_FASTER_WHISPER[taille]
                print(f"  faster-whisper {taille} ← {repo}")
                snapshot_download(repo, local_dir=dest)

    if _backend_actif("openvino", backends):
        for taille in tailles:
            if taille in REPOS_OPENVINO:
                dest = models_dir / f"openvino-whisper-{taille}"
                if dest.exists():
                    print(f"  openvino {taille} : déjà présent ({dest})")
                    continue
                repo = REPOS_OPENVINO[taille]
                print(f"  openvino {taille} ← {repo}")
                snapshot_download(repo, local_dir=dest)

        if "large-v3-turbo" in tailles:
            convertir_openvino_turbo(models_dir / "openvino-whisper-large-v3-turbo")

    if _backend_actif("directml", backends):
        for taille in tailles:
            if taille in REPOS_DIRECTML_ONNX:
                dest = models_dir / f"directml-whisper-{taille}"
                if not dest.exists():
                    repo = REPOS_DIRECTML_ONNX[taille]
                    print(f"  directml {taille} ← {repo} (ONNX fp16 seulement)")
                    try:
                        snapshot_download(repo, local_dir=dest,
                                           allow_patterns=mdl.DIRECTML_ALLOW_PATTERNS)
                    except Exception as exc:
                        print(f"  ⚠ directml {taille} : téléchargement échoué ({exc.__class__.__name__}: {exc})")
                        print(f"    → taille sautée ; vérifier le repo {repo!r} ou définir HF_TOKEN")
                        if dest.exists():
                            shutil.rmtree(dest, ignore_errors=True)
                else:
                    print(f"  directml {taille} : déjà présent ({dest})")

    if _backend_actif("vulkan", backends):
        ggml_dir = models_dir / "ggml"
        ggml_dir.mkdir(exist_ok=True)
        for taille in tailles:
            if taille in GGML_FICHIERS:
                nom = GGML_FICHIERS[taille]
                dest = ggml_dir / nom
                if not dest.exists():
                    url = f"{GGML_BASE_URL}/{nom}"
                    print(f"  ggml {taille} ← {url}")
                    with urllib.request.urlopen(url) as resp:  # noqa: S310
                        dest.write_bytes(resp.read())
                else:
                    print(f"  ggml {taille} : déjà présent")


def _copier_si_absent(src: Path, dest: Path, fichier: bool = False) -> None:
    if dest.exists() or not src.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fichier:
        shutil.copy2(src, dest)
    else:
        shutil.copytree(src, dest)
    print(f"  {dest.name} ← copié depuis le prebuild ({src})")


def _copier_modeles_deja_prets(source: Path, models_dir: Path, tailles: list[str],
                                backends: list[str]) -> None:
    """Copie (sans déplacer) les artefacts déjà présents dans le cache prebuild.

    Contrairement au déplacement complet (backends=None), on ne prend que les
    artefacts des backends filtrés : le cache reste intact pour les prochains
    builds (complets ou filtrés), et le bundle réduit ne récupère pas ce qui ne
    sert pas (doc 39 §2.2).
    """
    for taille in tailles:
        if "faster-whisper" in backends and taille in REPOS_FASTER_WHISPER:
            nom = f"faster-whisper-{taille}"
            _copier_si_absent(source / nom, models_dir / nom)
        if "openvino" in backends and (taille in REPOS_OPENVINO or taille == "large-v3-turbo"):
            nom = f"openvino-whisper-{taille}"
            _copier_si_absent(source / nom, models_dir / nom)
        if "directml" in backends and taille in REPOS_DIRECTML_ONNX:
            nom = f"directml-whisper-{taille}"
            _copier_si_absent(source / nom, models_dir / nom)
    if "vulkan" in backends:
        for taille in tailles:
            nom = GGML_FICHIERS.get(taille)
            if nom:
                _copier_si_absent(source / "ggml" / nom, models_dir / "ggml" / nom, fichier=True)


def preparer_modeles(models_dir: Path, tailles: list[str], backends: list[str] | None = None) -> None:
    """Copie les modèles prébuild (Mac) dans le bundle, sinon les télécharge.

    Le build --natif sur la VM n'a pas torch/optimum dans son venv (spike_build.cmd
    n'installe que huggingface-hub) — il ne doit jamais déclencher la conversion
    OpenVINO turbo à la volée. Les modèles sont déjà synchronisés depuis le prebuild
    Mac (scripts/prebuild_spike_modeles.sh) dans chemins.dossier_modeles() ; on les
    copie tels quels plutôt que de refaire un telecharger_modeles vers models_dir.

    Avec un filtre `backends` (bundle réduit, doc 39 §2.2), le cache prebuild n'est
    JAMAIS déplacé en bloc (il contient tous les backends, pas seulement ceux
    demandés) : on copie sélectivement ce qui existe déjà, puis on télécharge le
    reste avec le même filtre.
    """
    source = chemins.dossier_modeles()
    if backends is None:
        if source.resolve() != models_dir.resolve() and source.is_dir() and not modeles_prets(source, tailles):
            # move plutôt que copie : évite de doubler ~20 Go sur un disque VM à l'étroit —
            # source est un simple cache de sync Mac->VM, retélécharger via tar au prochain build.
            models_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(models_dir))
            print(f"  modèles ← déplacés depuis le prebuild ({source})")
            return
    elif source.resolve() != models_dir.resolve() and source.is_dir():
        _copier_modeles_deja_prets(source, models_dir, tailles, backends)
    telecharger_modeles(models_dir, tailles, backends=backends)


def modeles_prets(models_dir: Path, tailles: list[str]) -> list[str]:
    """Liste les modèles manquants dans models_dir pour les tailles données."""
    manquants: list[str] = []
    for taille in tailles:
        if taille in REPOS_FASTER_WHISPER and not (models_dir / f"faster-whisper-{taille}").is_dir():
            manquants.append(f"faster-whisper-{taille}")
        if taille == "large-v3-turbo":
            if not (models_dir / "openvino-whisper-large-v3-turbo").is_dir():
                manquants.append("openvino-whisper-large-v3-turbo")
        elif taille in REPOS_OPENVINO and not (models_dir / f"openvino-whisper-{taille}").is_dir():
            manquants.append(f"openvino-whisper-{taille}")
        if taille in REPOS_DIRECTML_ONNX and not (models_dir / f"directml-whisper-{taille}").is_dir():
            manquants.append(f"directml-whisper-{taille}")
        if taille in GGML_FICHIERS and not (models_dir / "ggml" / GGML_FICHIERS[taille]).is_file():
            manquants.append(f"ggml/{GGML_FICHIERS[taille]}")
    return manquants


def generer_lanceur(args: str = "") -> str:
    """`args` (p. ex. "--backends openvino --modeles large-v3-turbo") est injecté
    avant `%*`, qui reste disponible pour une surcharge manuelle (doc 39 §2.2)."""
    ligne_commande = '"%BASE%python\\python.exe" -m spike.backends_windows'
    if args:
        ligne_commande += f" {args}"
    ligne_commande += " %*\r\n"
    return (
        "@echo off\r\n"
        "REM Lanceur spike backends Windows — aucune installation.\r\n"
        "setlocal\r\n"
        "set BASE=%~dp0\r\n"
        "set PYTHONPATH=%BASE%libs\r\n"
        "set HF_HUB_OFFLINE=1\r\n"
        "set TRANSFORMERS_OFFLINE=1\r\n"
        'set SPIKE_MODELS=%BASE%libs\\spike\\backends_windows\\assets\\models\r\n'
        'set SPIKE_AUDIO=%BASE%libs\\spike\\backends_windows\\assets\\audio_canonique.wav\r\n'
        'set SPIKE_WHISPER_CLI=%BASE%libs\\spike\\backends_windows\\assets\\whisper-cli.exe\r\n'
        + ligne_commande +
        "echo.\r\n"
        "pause\r\n"
    )


def copier_audio(libs: Path) -> None:
    """Copie l'audio canonique du benchmark dans le bundle spike."""
    src = RACINE_PROJET / "benchmark" / "assets" / "audio_canonique.wav"
    dest_dir = libs / "spike" / "backends_windows" / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.copy2(src, dest_dir / "audio_canonique.wav")
        print(f"  audio canonique ← {src}")
    else:
        print(f"  ⚠ audio canonique absent ({src}) — ajouter manuellement.")


def copier_whisper_cli(libs: Path) -> None:
    """Copie whisper-cli.exe (Vulkan) + DLLs prébuildés (Mac, cf. telecharger_whisper_cli)."""
    src_dir = chemins.dossier_assets()
    dest_dir = libs / "spike" / "backends_windows" / "assets"
    dest_dir.mkdir(parents=True, exist_ok=True)
    manquants = whisper_cli_manquants(src_dir)
    if manquants:
        print(f"  ⚠ whisper-cli absent ({manquants}) — lancer scripts/prebuild_spike_modeles.sh d'abord.")
        return
    for nom in WHISPER_CLI_FICHIERS:
        shutil.copy2(src_dir / nom, dest_dir / nom)
    print(f"  whisper-cli.exe (Vulkan) + DLLs ← {src_dir}")


def verifier_wheels(paquets: list[str] | None = None) -> dict:
    paquets = paquets or DEPS_SPIKE
    resultats: dict[str, bool] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for pkg in paquets:
            args = ["download", "--no-deps", "--only-binary=:all:", "-d", tmp,
                    "--python-version", PY_VERSION, "--implementation", "cp"]
            for p in PLATEFORMES_WINDOWS:
                args += ["--platform", p]
            args.append(pkg)
            try:
                subprocess.run([sys.executable, "-m", "pip", *args],
                               check=True, capture_output=True, text=True)
                resultats[pkg] = True
            except subprocess.CalledProcessError as exc:
                print(f"  ✗ {pkg} : pas de wheel windows\n{exc.stderr}", file=sys.stderr)
                resultats[pkg] = False
    return resultats


def _suffixe_bundle(backends: list[str] | None, tailles: list[str]) -> str:
    """Suffixe vide par défaut (rétrocompatible, cf. scripts/build_spike_backends_vm.sh
    qui attend `spike-backends-windows.zip`) ; sinon dérivé des backends/tailles
    filtrés pour ne pas écraser le bundle complet (doc 39 §2.2.3)."""
    morceaux = list(backends) if backends else []
    if tailles != mdl.SWEEP:
        morceaux += list(tailles)
    return f"-{'-'.join(morceaux)}" if morceaux else ""


def _args_lanceur(backends: list[str] | None, tailles: list[str]) -> str:
    parties = []
    if backends:
        parties.append("--backends " + " ".join(backends))
    if tailles != mdl.SWEEP:
        parties.append("--modeles " + " ".join(tailles))
    return " ".join(parties)


def assembler(sortie: Path, tailles: list[str] | None = None, natif: bool = False,
              backends: list[str] | None = None) -> Path:
    tailles = tailles or mdl.SWEEP
    nom_bundle = "spike-backends-windows" + _suffixe_bundle(backends, tailles)
    bundle = sortie / nom_bundle
    libs = bundle / "libs"
    bundle.mkdir(parents=True, exist_ok=True)

    print("[1/7] Wheels Windows")
    telecharger_wheels(libs, natif=natif)
    print("[2/7] Sources spike + debrief_meet")
    copier_sources(libs)
    print(f"[3/7] Modèles ({backends or '4 backends'} × {tailles})")
    preparer_modeles(libs / "spike" / "backends_windows" / "assets" / "models", tailles, backends=backends)
    if backends is None or "vulkan" in backends:
        print("[4/7] whisper-cli.exe (Vulkan)")
        copier_whisper_cli(libs)
    else:
        print("[4/7] whisper-cli.exe (Vulkan) : sauté (backend vulkan non demandé)")
    print("[5/7] Audio canonique")
    copier_audio(libs)
    print("[6/7] Python embeddable")
    telecharger_python_embeddable(bundle)
    print("[7/7] Lanceur + zip")
    lanceur = bundle / "lancer.bat"
    lanceur.write_text(generer_lanceur(_args_lanceur(backends, tailles)), encoding="utf-8")
    archive = sortie / f"{nom_bundle}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(bundle.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(bundle.parent))
    shutil.rmtree(bundle, ignore_errors=True)
    print(f"✓ {archive}")
    return archive


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Assemble le bundle spike backends Windows")
    ap.add_argument("--sortie", type=Path, default=Path.cwd() / "bundles")
    ap.add_argument("--verifier", action="store_true",
                    help="Vérifie seulement la disponibilité des wheels.")
    ap.add_argument("--natif", action="store_true",
                    help="Résolution native (build SUR la VM : même OS/arch/Python 3.11).")
    ap.add_argument("--modeles", nargs="+", default=None)
    ap.add_argument("--backends", nargs="+", default=None,
                    help="Filtrer les backends inclus dans le bundle (défaut : tous — "
                         "faster-whisper/openvino/directml/vulkan).")
    ap.add_argument("--prebuild-modeles-seulement", action="store_true",
                    help="Télécharge/convertit les modèles en local (Mac) sans assembler le bundle.")
    ap.add_argument("--verifier-modeles", action="store_true",
                    help="Vérifie que les modèles locaux sont complets (exit 1 sinon).")
    args = ap.parse_args(argv)

    if args.verifier_modeles:
        tailles = args.modeles or mdl.SWEEP
        models_dir = chemins.dossier_modeles()
        assets_dir = chemins.dossier_assets()
        manquants = modeles_prets(models_dir, tailles) + whisper_cli_manquants(assets_dir)
        if manquants:
            print(f"✗ Modèles/binaires manquants dans {assets_dir} : {manquants}", file=sys.stderr)
            return 1
        print(f"✓ Modèles + whisper-cli complets dans {assets_dir} ({tailles}).")
        return 0

    if args.prebuild_modeles_seulement:
        tailles = args.modeles or mdl.SWEEP
        models_dir = chemins.dossier_modeles()
        assets_dir = chemins.dossier_assets()
        print(f"[prebuild] Modèles ({tailles}) → {models_dir}")
        telecharger_modeles(models_dir, tailles)
        telecharger_whisper_cli(assets_dir)
        manquants = modeles_prets(models_dir, tailles) + whisper_cli_manquants(assets_dir)
        if manquants:
            print(f"✗ Prebuild incomplet : {manquants}", file=sys.stderr)
            return 1
        print("✓ Prebuild complet.")
        return 0

    if args.verifier:
        res = verifier_wheels()
        manquants = [p for p, ok in res.items() if not ok]
        print("\nWheels :", {p: ("ok" if ok else "MANQUANTE") for p, ok in res.items()})
        if manquants:
            print(f"✗ Sans wheel windows : {manquants}", file=sys.stderr)
            return 1
        print("✓ Toutes les dépendances ont une wheel windows.")
        return 0

    assembler(args.sortie, tailles=args.modeles, natif=args.natif, backends=args.backends)
    return 0


if __name__ == "__main__":
    sys.exit(main())
