#!/bin/sh
# Build NATIF du .deb debriefMeet sur le conteneur LXC Ubuntu 26.04 (docs/49 §6).
#
# Meme mecanique que scripts/build_app_windows_vm.sh : tar over ssh, sshpass,
# session SSH gardee OUVERTE pendant tout le build (un process detache serait tue
# a la fermeture de session).
#
# Usage (depuis le Mac) :
#   bash scripts/build_app_linux_lxc.sh
#
# Pre-requis Mac : sshpass. Pre-requis conteneur : scripts/provisionner_lxc_ubuntu.sh
# execute une fois (Python systeme 3.14, ffmpeg, dpkg-dev, deps Qt offscreen).
set -eu

LXC_HOST="${LXC_HOST:-192.168.1.32}"
LXC_USER="${LXC_USER:-root}"
LXC_PASS="${LXC_PASS:-sylvain}"
RACINE="$(cd "$(dirname "$0")/.." && pwd)"
SORTIE="${SORTIE:-$RACINE/dist}"
DEPOT='$HOME/build/debrief-meet'

ssh_lxc() {
    sshpass -p "$LXC_PASS" ssh \
        -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=1000 \
        "$LXC_USER@$LXC_HOST" "$@"
}

echo "=== debriefMeet — build .deb Linux ==="
echo "LXC     : ${LXC_USER}@${LXC_HOST}"

echo ""
echo "[1/4] Preparation de BUILD_INFO (date + hash git)..."
date -u +%Y%m%d > "$RACINE/BUILD_INFO"
git -C "$RACINE" rev-parse --short HEAD >> "$RACINE/BUILD_INFO"
trap 'rm -f "$RACINE/BUILD_INFO"' EXIT
cat "$RACINE/BUILD_INFO"

echo ""
echo "[2/4] Sync sources Mac -> conteneur ($DEPOT)"
# Purge AVANT extraction : tar ecrase mais ne supprime jamais un fichier retire a
# la source — un module supprime survivrait indefiniment (bug vecu sur la VM
# Windows le 2026-08-05). dist/ est purge des anciens .deb pour que le rapatriement
# n'ait qu'un seul candidat (bug vecu le 2026-07-06 cote Windows).
ssh_lxc "rm -rf $DEPOT/src $DEPOT/tests $DEPOT/packaging $DEPOT/dist/debriefmeet_*.deb && mkdir -p $DEPOT"
COPYFILE_DISABLE=1 tar czf - \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    --exclude='packaging/vendor' \
    -C "$RACINE" src tests packaging pyproject.toml BUILD_INFO \
    | ssh_lxc "tar -xzf - -C $DEPOT"

echo ""
echo "[3/4] Build natif sur le conteneur (venv + pytest bloquant + PyInstaller + dpkg-deb)"
echo "      NE PAS fermer ce terminal — un process detache serait tue a la deconnexion SSH."
ssh_lxc "cd $DEPOT && sh packaging/linux/build_app.sh" || true

RC="$(ssh_lxc "cat $DEPOT/build_app.done" 2>/dev/null | tr -dc '0-9' | head -c 3)"
if [ "$RC" != "0" ]; then
    echo "" >&2
    echo "✗ build_app.sh a echoue (RC=${RC:-?}) — relire la sortie ci-dessus" >&2
    exit 1
fi

echo ""
echo "[4/4] Rapatriement du .deb -> $SORTIE/"
mkdir -p "$SORTIE"
NOM_DEB="$(ssh_lxc "ls -t \$HOME/build/debrief-meet/dist/debriefmeet_*_amd64.deb" | head -n 1 | xargs basename)"
if [ -z "$NOM_DEB" ]; then
    echo "✗ Aucun debriefmeet_*_amd64.deb trouve dans $DEPOT/dist" >&2
    exit 1
fi
sshpass -p "$LXC_PASS" scp -o StrictHostKeyChecking=no -o NumberOfPasswordPrompts=1 \
    "$LXC_USER@$LXC_HOST:build/debrief-meet/dist/$NOM_DEB" "$SORTIE/$NOM_DEB"

echo ""
echo "✓ $SORTIE/$NOM_DEB"
echo "  Fumee : bash scripts/fumee_deb_lxc.sh"
