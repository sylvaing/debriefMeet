#!/bin/sh
# Provisionnement du conteneur LXC Ubuntu 26.04 de build (docs/49 §6.2, étape 1).
#
# Installe tout ce qu'il faut pour : faire tourner la gate pytest en offscreen, puis
# construire le .deb (PyInstaller + dpkg-deb). Idempotent — rejouable sans risque.
#
# Usage (depuis le Mac) :
#   sh scripts/provisionner_lxc_ubuntu.sh
#
# Pre-requis Mac : sshpass (brew install sshpass).
# Pre-requis conteneur : SSH accessible pour LXC_USER (cf. README de docs/49 §6.2 —
# sur une Ubuntu fraiche, root par mot de passe est refuse par defaut :
# PermitRootLogin prohibit-password).
set -eu

LXC_HOST="${LXC_HOST:-192.168.1.32}"
LXC_USER="${LXC_USER:-root}"
LXC_PASS="${LXC_PASS:-sylvain}"

ssh_lxc() {
    sshpass -p "$LXC_PASS" ssh \
        -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 \
        "$LXC_USER@$LXC_HOST" "$@"
}

echo "=== [1/5] Verification de l'acces et de l'OS ==="
ssh_lxc 'set -eu
    . /etc/os-release
    echo "  $PRETTY_NAME ($(uname -m))"
    case "$VERSION_ID" in
        26.04) ;;
        *) echo "  ATTENTION : version attendue 26.04, trouvee $VERSION_ID" ;;
    esac
    case "$(uname -m)" in
        x86_64) ;;
        *) echo "  ERREUR : le livrable doit etre amd64 (PyInstaller ne cross-compile pas)" ; exit 1 ;;
    esac'

echo "=== [2/5] Paquets systeme ==="
# - binutils : requis par PyInstaller sous Linux (objcopy/strip)
# - ffmpeg : Depends du .deb, present sur le builder pour que la gate pytest ne
#   saute pas les tests qui le resolvent
# - lib* : dependances runtime de PySide6, necessaires meme en QT_QPA_PLATFORM=offscreen
# - pulseaudio-utils : pactl, utilise par infos_systeme (rubrique serveur_audio)
ssh_lxc 'set -eu
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        git rsync binutils dpkg-dev fakeroot \
        ffmpeg pulseaudio-utils \
        libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 \
        libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
        libportaudio2
    echo "  paquets installes"'

echo "=== [3/5] Python 3.13 (PyInstaller ne supporte pas 3.14) ==="
ssh_lxc 'set -eu
    export DEBIAN_FRONTEND=noninteractive
    if command -v python3.13 >/dev/null 2>&1; then
        echo "  deja present : $(python3.13 --version)"
    elif apt-get install -y -qq python3.13 python3.13-venv python3.13-dev 2>/dev/null; then
        echo "  installe depuis archive : $(python3.13 --version)"
    else
        echo "  absent de l archive — bascule sur le PPA deadsnakes"
        apt-get install -y -qq software-properties-common
        add-apt-repository -y ppa:deadsnakes/ppa
        apt-get update -qq
        apt-get install -y -qq python3.13 python3.13-venv python3.13-dev
        echo "  installe depuis deadsnakes : $(python3.13 --version)"
    fi'

echo "=== [4/5] Venv de build + dependances de l app ==="
ssh_lxc 'set -eu
    RACINE=$HOME/build/debrief-meet
    mkdir -p "$RACINE"
    if [ ! -d "$HOME/build/.venv-build" ]; then
        python3.13 -m venv "$HOME/build/.venv-build"
    fi
    "$HOME/build/.venv-build/bin/pip" install --quiet --upgrade pip wheel
    echo "  venv pret : $("$HOME/build/.venv-build/bin/python" --version)"
    echo "  (les dependances de l app sont installees par le script de build,"
    echo "   depuis le pyproject.toml synchronise)"'

echo "=== [5/5] Recapitulatif ==="
ssh_lxc 'set -eu
    echo "  python3.13 : $(command -v python3.13)"
    echo "  ffmpeg     : $(command -v ffmpeg) ($(ffmpeg -version 2>/dev/null | head -1))"
    echo "  dpkg-deb   : $(command -v dpkg-deb)"
    echo "  venv build : $HOME/build/.venv-build"
    echo "  sources    : $HOME/build/debrief-meet (synchronisees par le script de build)"'

echo
echo "Conteneur pret. Etape suivante : gate pytest (docs/49 §8 etape 1) —"
echo "  sh scripts/gate_pytest_lxc.sh"
