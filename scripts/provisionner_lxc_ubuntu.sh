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

echo "=== [3/5] Python : celui de la distribution, sans PPA ==="
# Decision du 2026-08-10 : le port Linux utilise le Python SYSTEME d'Ubuntu 26.04
# (3.14), pas une version installee depuis un PPA tiers. La contrainte historique
# « PyInstaller ne supporte pas 3.14 » (CLAUDE.md, chaines macOS/Windows en 3.13)
# a expire : PyInstaller 6.22 accepte 3.14, et PySide6 est distribue en roue abi3
# (cp310-abi3) donc compatible par construction. Mac et Windows seront alignes
# plus tard, separement.
#
# `python3-venv` n'est PAS tire par defaut sur une image LXC minimale : sans lui,
# `python3 -m venv` echoue sur « ensurepip is not available ».
ssh_lxc 'set -eu
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y -qq python3 python3-venv python3-dev
    echo "  python systeme : $(python3 --version) ($(command -v python3))"'

echo "=== [4/5] Venv de build + dependances de l app ==="
ssh_lxc 'set -eu
    RACINE=$HOME/build/debrief-meet
    mkdir -p "$RACINE"
    VENV=$HOME/build/.venv-build
    # Recree le venv s il pointe sur un interpreteur disparu (ex. bascule 3.13 -> 3.14) :
    # un venv orphelin echoue plus tard, au milieu du build, avec un message obscur.
    if [ -d "$VENV" ] && ! "$VENV/bin/python" --version >/dev/null 2>&1; then
        echo "  venv casse (interpreteur disparu) — recreation"
        rm -rf "$VENV"
    fi
    [ -d "$VENV" ] || python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip wheel
    echo "  venv pret : $("$VENV/bin/python" --version)"
    echo "  (les dependances de l app sont installees par le script de gate/build,"
    echo "   depuis le pyproject.toml synchronise)"'

echo "=== [5/5] Recapitulatif ==="
ssh_lxc 'set -eu
    echo "  python     : $(python3 --version) ($(command -v python3))"
    echo "  ffmpeg     : $(command -v ffmpeg) ($(ffmpeg -version 2>/dev/null | head -1))"
    echo "  dpkg-deb   : $(command -v dpkg-deb)"
    echo "  venv build : $HOME/build/.venv-build"
    echo "  sources    : $HOME/build/debrief-meet (synchronisees par le script de build)"
    if [ -n "$(ls /etc/apt/sources.list.d/ 2>/dev/null | grep -i deadsnakes || true)" ]; then
        echo "  ATTENTION : un depot deadsnakes traine encore dans les sources apt"
    fi'

echo
echo "Conteneur pret. Etape suivante : gate pytest (docs/49 §8 etape 1) —"
echo "  sh scripts/gate_pytest_lxc.sh"
