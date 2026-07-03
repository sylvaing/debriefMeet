#!/bin/sh
# Prebuild local (Mac) des modeles du spike backends Windows.
#
# Telecharge faster-whisper/OpenVINO/DirectML(fp16)/ggml pour les 4 tailles,
# convertit large-v3-turbo en OpenVINO (aucun repo public - doc 18 SS12.2), et
# telecharge whisper-cli.exe (Vulkan, binaire tiers - doc 18 SS13.6, ggml-org
# ne publie aucun build Windows Vulkan officiel).
# Idempotent : relancer ne re-telecharge/reconvertit que ce qui manque.
#
# Pourquoi un venv dedie : la conversion OpenVINO turbo a besoin de torch +
# optimum-intel[openvino], qu'on ne veut jamais dans le bundle Windows
# (DEPS_SPIKE reste reserve aux wheels win_amd64) - doc 18 SS13.3.
#
# IMPORTANT : Python 3.14 casse la conversion OpenVINO (optimum-intel utilise
# `functools.partial` comme attribut de classe pour NORMALIZED_CONFIG_CLASS ;
# Python 3.14 a rendu `functools.partial` descripteur (`__get__`), ce qui fait
# auto-binder `self` et double `allow_new` -> `TypeError: NormalizedConfig.__init__()
# got multiple values for argument 'allow_new'`). Utiliser Python 3.13 (meme
# contrainte que .venv-build pour PyInstaller, cf. CLAUDE.md).
#
# Usage : bash scripts/prebuild_spike_modeles.sh [tailles...]
#   ex : bash scripts/prebuild_spike_modeles.sh large-v3-turbo
set -eu

RACINE="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$RACINE/.venv-spike-prebuild"
PYTHON313="${PYTHON313:-python3.13}"

if [ ! -d "$VENV" ]; then
    echo "[prebuild] Creation du venv dedie Python 3.13 ($VENV)..."
    "$PYTHON313" -m venv "$VENV"
fi

echo "[prebuild] Installation torch + optimum-intel[openvino] + huggingface-hub..."
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q torch "optimum-intel[openvino]" huggingface-hub

echo "[prebuild] Telechargement/conversion des modeles..."
cd "$RACINE"
if [ "$#" -gt 0 ]; then
    "$VENV/bin/python" -m spike.backends_windows.assembler --prebuild-modeles-seulement --modeles "$@"
else
    "$VENV/bin/python" -m spike.backends_windows.assembler --prebuild-modeles-seulement
fi
