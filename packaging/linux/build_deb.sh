#!/bin/sh
# Assemble le .deb à partir du onedir PyInstaller (docs/49 §6.1).
#
# Exécuté sur le conteneur LXC par build_app.sh, APRÈS pyinstaller. Peut se rejouer
# seul si dist/debriefMeet existe déjà :
#   sh packaging/linux/build_deb.sh
#
# Arborescence produite :
#   /opt/debriefmeet/                              onedir PyInstaller
#   /usr/bin/debriefmeet                           lien vers l'exécutable
#   /usr/share/applications/debriefmeet.desktop    entrée de menu
#   /usr/share/icons/hicolor/512x512/apps/…        icône
#
# Les données utilisateur (config XDG, ~/Documents/debriefMeet) ne sont JAMAIS dans
# le paquet : apt remove/purge ne les touche pas (décision L6).
set -eu

RACINE="$(cd "$(dirname "$0")/../.." && pwd)"
ONEDIR="$RACINE/dist/debriefMeet"
ICONE="$RACINE/src/debrief_meet/ui/assets/icons/app-icon-512.png"

[ -d "$ONEDIR" ] || { echo "✗ $ONEDIR absent — lancer pyinstaller d'abord" >&2; exit 1; }
[ -f "$ICONE" ] || { echo "✗ icône $ICONE absente" >&2; exit 1; }

# VERSION_COMPLETE depuis _version.py (écrit par generer_version.py — le `+` de
# "0.3.0+20260813.abc1234" est une syntaxe de version Debian valide).
VERSION="$(sed -n 's/^VERSION_COMPLETE = "\(.*\)"$/\1/p' "$RACINE/src/debrief_meet/_version.py")"
[ -n "$VERSION" ] || { echo "✗ VERSION_COMPLETE introuvable dans _version.py — lancer generer_version.py" >&2; exit 1; }

PAQUET="debriefmeet_${VERSION}_amd64"
STAGING="$RACINE/build/deb/$PAQUET"

echo "[build_deb] $PAQUET"
rm -rf "$STAGING"
mkdir -p "$STAGING/opt/debriefmeet" \
         "$STAGING/usr/bin" \
         "$STAGING/usr/share/applications" \
         "$STAGING/usr/share/icons/hicolor/512x512/apps" \
         "$STAGING/DEBIAN"

cp -a "$ONEDIR/." "$STAGING/opt/debriefmeet/"
ln -s /opt/debriefmeet/debriefMeet "$STAGING/usr/bin/debriefmeet"
cp "$RACINE/packaging/linux/debriefmeet.desktop" "$STAGING/usr/share/applications/"
cp "$ICONE" "$STAGING/usr/share/icons/hicolor/512x512/apps/debriefmeet.png"

TAILLE_KO="$(du -sk "$STAGING" | cut -f1)"

# Depends — chaque entrée a une raison mesurée, ne rien retirer sans la relire :
#   ffmpeg           décision L3 : rien d'embarqué, chemin_ffmpeg() résout le PATH
#   libportaudio2    la roue pip de sounddevice NE la fournit PAS sous Linux —
#                    OSError "PortAudio library not found" à l'import, vécu chez le
#                    premier utilisateur du spike (docs/49 §6.1)
#   pulseaudio-utils pactl, indispensable pour résoudre le moniteur de la sortie
#                    par défaut (spike Q2 : PortAudio ne rend que "default")
#   libxcb-cursor0   requis par le plugin Qt xcb (session X11) non couvert par le
#                    bundle PySide6
#   libgtk-3-0t64    le bundle embarque platformthemes/libqgtk3.so, qui lie
#                    libgtk-3/libgdk-3/libgdk_pixbuf : sans elles, Qt ignore le thème
#                    d'icônes du bureau et le décorateur Wayland ne trouve plus ses
#                    boutons (« Failed to find an svg icon for window-close-symbolic »)
#   adwaita-icon-theme  fournit précisément ces icônes symboliques
cat > "$STAGING/DEBIAN/control" <<FIN
Package: debriefmeet
Version: $VERSION
Architecture: amd64
Maintainer: Sylvain Garcia <sylvain.garcia@bluemind.net>
Installed-Size: $TAILLE_KO
Depends: ffmpeg, libportaudio2, pulseaudio-utils, libxcb-cursor0, libgtk-3-0t64, adwaita-icon-theme
Section: sound
Priority: optional
Description: Transcription vocale de réunions (dictée, réunion, journal)
 Enregistre les réunions (micro + son système via PipeWire), transcrit et
 produit des comptes rendus via l'API Mistral. Les transcriptions vivent dans
 ~/Documents/debriefMeet et survivent à la désinstallation.
FIN

mkdir -p "$RACINE/dist"
# --root-owner-group : les fichiers appartiennent à root:root dans le paquet, quel
# que soit l'utilisateur qui builde.
dpkg-deb --build --root-owner-group "$STAGING" "$RACINE/dist/$PAQUET.deb"
echo "[build_deb] OK → dist/$PAQUET.deb"
