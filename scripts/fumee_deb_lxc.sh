#!/bin/sh
# Fumee du .deb sur le conteneur LXC (docs/49 §6.3) — miroir de fumee_setup_vm.sh.
#
# Via SSH, sans session graphique : install par apt (resout les Depends),
# --version, reinstall par-dessus, purge, verification qu'il ne reste rien.
# Rejouable (nettoie avant/apres). Utilise le .deb construit sur le conteneur
# par le dernier build_app_linux_lxc.sh.
#
# Ce que la fumee NE couvre PAS (necessite le poste graphique de l'utilisateur) :
# lancement complet de l'app, tray, capture audio — c'est la campagne de
# validation chez l'utilisateur (docs/49 §8 etape 6).
#
# Usage (depuis le Mac) :
#   bash scripts/fumee_deb_lxc.sh
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

echo "=== Fumee .deb — ${LXC_USER}@${LXC_HOST} ==="
ssh_lxc 'set -eu
    export DEBIAN_FRONTEND=noninteractive
    DEB="$(ls -t $HOME/build/debrief-meet/dist/debriefmeet_*_amd64.deb | head -n 1)"
    [ -n "$DEB" ] || { echo "Aucun .deb — lancer build_app_linux_lxc.sh d abord"; exit 1; }
    echo "[0/6] Paquet teste : $DEB"

    echo "[1/6] Nettoyage prealable (rejouabilite)..."
    apt-get remove --purge -y -qq debriefmeet 2>/dev/null || true

    echo "[2/6] Champ Depends du paquet..."
    DEPS="$(dpkg-deb -f "$DEB" Depends)"
    echo "   Depends: $DEPS"
    # libportaudio2 : la roue pip de sounddevice ne la fournit pas sous Linux —
    # crash a l import chez le premier utilisateur du spike (docs/49 §6.1). Toute
    # regression de ce champ doit faire echouer la fumee, pas le poste cible.
    for dep in ffmpeg libportaudio2 pulseaudio-utils; do
        case "$DEPS" in *"$dep"*) ;; *) echo "✗ Depends sans $dep"; exit 1;; esac
    done

    echo "[3/6] Installation (apt resout les Depends)..."
    apt-get install -y -qq "$DEB" >/dev/null

    echo "[4/6] Verifications post-install..."
    test -x /opt/debriefmeet/debriefMeet || { echo "✗ executable absent"; exit 1; }
    test -L /usr/bin/debriefmeet || { echo "✗ lien /usr/bin/debriefmeet absent"; exit 1; }
    test -f /usr/share/applications/debriefmeet.desktop || { echo "✗ .desktop absent"; exit 1; }
    test -f /usr/share/icons/hicolor/512x512/apps/debriefmeet.png || { echo "✗ icone absente"; exit 1; }
    command -v ffmpeg >/dev/null || { echo "✗ ffmpeg non installe par les Depends"; exit 1; }
    VERSION_ATTENDUE="$(dpkg-deb -f "$DEB" Version)"
    SORTIE_VERSION="$(debriefmeet --version)"
    echo "   debriefmeet --version → $SORTIE_VERSION"
    # --version affiche __version__ (0.3.0), prefixe de la version deb (0.3.0+date.hash).
    case "$VERSION_ATTENDUE" in "$(echo "$SORTIE_VERSION" | awk "{print \$2}")"*) ;; *)
        echo "✗ version du binaire ($SORTIE_VERSION) incoherente avec le paquet ($VERSION_ATTENDUE)"; exit 1;; esac

    echo "[5/6] Reinstallation par-dessus (mise a jour)..."
    apt-get install --reinstall -y -qq "$DEB" >/dev/null
    debriefmeet --version >/dev/null

    echo "[6/6] Desinstallation complete..."
    apt-get remove --purge -y -qq debriefmeet >/dev/null
    test ! -e /opt/debriefmeet || { echo "✗ /opt/debriefmeet subsiste apres purge"; exit 1; }
    test ! -e /usr/bin/debriefmeet || { echo "✗ /usr/bin/debriefmeet subsiste apres purge"; exit 1; }
    test ! -e /usr/share/applications/debriefmeet.desktop || { echo "✗ .desktop subsiste"; exit 1; }

    echo ""
    echo "✓ Fumee OK — install, --version, reinstall, purge"'
