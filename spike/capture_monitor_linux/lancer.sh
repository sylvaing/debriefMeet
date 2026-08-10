#!/bin/sh
# Spike capture système Linux (docs/49 §5.1) — sonde des sources .monitor PipeWire.
#
# À lancer sur une Ubuntu 26.04 AVEC SESSION GRAPHIQUE ET AUDIO (UTM arm64 convient,
# le comportement PipeWire ne dépend pas de l'architecture). Surtout PAS dans le
# conteneur LXC de build : il est headless, sans serveur audio.
#
#   sh spike/capture_monitor_linux/lancer.sh
#
# Le script est un protocole guidé : il annonce les actions à faire une par une et
# attend une validation. Ne pas le lancer en arrière-plan.
set -eu

ICI="$(cd "$(dirname "$0")" && pwd)"
VENV="$ICI/.venv"

if [ ! -d "$VENV" ]; then
    echo "→ Création du venv du spike (isolé de celui de l'app)…"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet sounddevice numpy
fi

if ! command -v pactl >/dev/null 2>&1; then
    echo "⚠  pactl absent — installe-le pour répondre à la question Q2 :"
    echo "     sudo apt install pulseaudio-utils"
    echo "   (le spike tourne quand même, Q2 sera notée « pactl absent »)"
    echo
fi

echo "═══════════════════════════════════════════════════════════════════════"
echo "  Spike « capture système Linux » — 3 phases, ~2 minutes"
echo
echo "  Phase 1  inventaire des périphériques (automatique)"
echo "  Phase 2  capture micro + moniteur — il te sera demandé de LANCER UNE"
echo "           MUSIQUE puis de parler dans le micro"
echo "  Phase 3  bascule à chaud — il te sera demandé de BRANCHER puis"
echo "           DÉBRANCHER un casque USB ou Bluetooth, flux ouvert"
echo
echo "  Prépare : un morceau de musique, et un casque USB ou BT sous la main."
echo "  Chaque action est annoncée à l'écran et attend ta validation."
echo "═══════════════════════════════════════════════════════════════════════"
echo

exec "$VENV/bin/python" "$ICI/sonde_monitor.py" "$@"
