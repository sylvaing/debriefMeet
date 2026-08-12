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
    echo "→ Première exécution : préparation de l'environnement (~30 s)…"
    if ! python3 -m venv "$VENV" 2>/dev/null; then
        echo
        echo "✗ Impossible de créer l'environnement Python. Il manque un paquet :"
        echo
        echo "    sudo apt install python3-venv"
        echo
        echo "  Relance ensuite cette même commande."
        exit 1
    fi
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet sounddevice numpy
fi

# Verification AVANT l'ecran d'accueil : `pip install sounddevice` ne fournit PAS la
# bibliotheque C PortAudio sous Linux (contrairement a macOS/Windows ou la roue
# l'embarque) — sans le paquet systeme, l'import leve « PortAudio library not found ».
# Constate chez le premier utilisateur du spike, le 2026-08-11.
if ! "$VENV/bin/python" -c "import sounddevice" >/dev/null 2>&1; then
    ERREUR="$("$VENV/bin/python" -c "import sounddevice" 2>&1 | tail -1)"
    echo
    echo "✗ Il manque une bibliothèque système pour lire le son."
    echo
    echo "  Installe-la avec :"
    echo
    echo "      sudo apt install libportaudio2"
    echo
    echo "  puis relance cette même commande (sh lancer.sh)."
    echo
    echo "  [détail technique : $ERREUR]"
    exit 1
fi

if ! command -v pactl >/dev/null 2>&1; then
    echo "⚠  Un outil optionnel est absent. Pour une mesure plus complète :"
    echo "     sudo apt install pulseaudio-utils"
    echo "   (le test fonctionne quand même sans, tu peux continuer)"
    echo
fi

cat <<'FIN'
═══════════════════════════════════════════════════════════════════════
  Test de captation du son système — environ 3 minutes

  Ce test mesure comment ton Ubuntu expose le son qui sort des
  haut-parleurs, pour préparer l'enregistrement des réunions.
  Il n'installe rien sur ton système et n'envoie rien sur Internet.

  CE QU'IL FAUT PRÉPARER AVANT DE COMMENCER :

    1. De quoi faire du son : une vidéo YouTube ouverte dans ton
       navigateur, ou un fichier de musique. N'importe quoi qui dure
       au moins 2 minutes.

    2. Un casque USB ou Bluetooth, à portée de main mais PAS ENCORE
       branché. (Si tu n'en as pas, tu pourras sauter cette partie.)

  COMMENT ÇA SE PASSE :

    Le test t'indique quoi faire, une action à la fois, et attend que
    tu appuies sur Entrée. Tu n'as jamais à deviner : suis les
    consignes à l'écran.

    Il enregistre le son pendant de courts moments. Les enregistrements
    restent sur ta machine ; à la fin, le test crée UN fichier .zip
    que tu renvoies à Sylvain.

═══════════════════════════════════════════════════════════════════════
FIN
printf "\n  Prêt ? Appuie sur Entrée pour commencer : "
read -r _ || true
echo

exec "$VENV/bin/python" "$ICI/sonde_monitor.py" "$@"
