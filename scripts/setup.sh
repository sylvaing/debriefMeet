#!/bin/bash
# setup.sh — Installe l'environnement de développement debriefMeet
#
# Usage :
#   bash scripts/setup.sh           # installation complète + tests
#   bash scripts/setup.sh --deps-only  # venv + deps uniquement (appelé par le Makefile)
#
# Prérequis (vérifiés par ce script) :
#   • Python 3.11+
#   • Xcode Command Line Tools (macOS) — pour compiler les helpers Swift
#
# Ce que fait ce script :
#   1. Vérifie les prérequis
#   2. Crée le venv (.venv/) si absent
#   3. Installe les dépendances Python (extras selon l'OS)
#   4. Compile les helpers Swift (macOS uniquement)
#   5. Lance les tests unitaires (sauf si --deps-only)

set -euo pipefail

DEPS_ONLY=false
[[ "${1:-}" == "--deps-only" ]] && DEPS_ONLY=true

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── Couleurs ──────────────────────────────────────────────────────────────────
GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; RESET="\033[0m"
ok()   { echo -e "${GREEN}[OK]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[!]${RESET}   $*"; }
err()  { echo -e "${RED}[ERR]${RESET} $*"; exit 1; }

echo ""
echo "debriefMeet — installation de l'environnement"
echo "─────────────────────────────────────────────"

# ── 1. Python 3.11+ ───────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    err "python3 introuvable. Installer via Homebrew : brew install python"
fi
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"; then
    err "Python 3.11+ requis (actuel : $PYTHON_VER). Mettre à jour : brew upgrade python"
fi
ok "Python $PYTHON_VER"

# ── 2. Xcode Command Line Tools (macOS) ───────────────────────────────────────
OS="$(uname)"
if [[ "$OS" == "Darwin" ]]; then
    if ! xcrun --find swiftc &>/dev/null 2>&1; then
        err "Xcode Command Line Tools manquants. Lancer : xcode-select --install"
    fi
    SWIFT_VER=$(xcrun swiftc --version 2>&1 | head -1 | sed 's/.*version //')
    ok "swiftc $SWIFT_VER"
fi

# ── 3. Venv ───────────────────────────────────────────────────────────────────
if [[ ! -f .venv/bin/activate ]]; then
    echo "→ Création du venv..."
    python3 -m venv .venv
    ok "venv créé dans .venv/"
else
    ok "venv déjà présent"
fi

# ── 4. Dépendances Python ─────────────────────────────────────────────────────
echo "→ Installation des dépendances Python..."
.venv/bin/pip install --quiet --upgrade pip

if [[ "$OS" == "Darwin" ]]; then
    EXTRAS="dev,macos"
elif [[ "$OS" == "Linux" ]]; then
    EXTRAS="dev,linux"
else
    EXTRAS="dev,windows"
fi

.venv/bin/pip install --quiet -e ".[$EXTRAS]"
ok "dépendances installées (extras : $EXTRAS)"

# ── 5. Helpers Swift ──────────────────────────────────────────────────────────
if [[ "$OS" == "Darwin" ]]; then
    echo "→ Compilation du helper Swift (ScreenCaptureKit)..."
    bash helpers/macos/poc-audio-tap/build.sh
    # build.sh affiche déjà son propre [OK]
fi

$DEPS_ONLY && exit 0

# ── 6. Tests unitaires ────────────────────────────────────────────────────────
echo ""
echo "→ Tests unitaires..."
.venv/bin/pytest -m "not integration" -q

echo ""
echo "─────────────────────────────────────────────"
ok "Setup terminé."
echo ""
echo "  Lancer l'app    : make run"
echo "  Relancer tests  : make test"
echo ""

# ── Notes post-install ────────────────────────────────────────────────────────
if [[ "$OS" == "Darwin" ]]; then
    echo -e "${YELLOW}Note :${RESET} Pour le mode Réunion, accorder la permission"
    echo "       «\033[1mEnregistrement de l'écran\033[0m» au terminal dans :"
    echo "       Réglages Système → Confidentialité → Enregistrement de l'écran"
    echo ""
fi
