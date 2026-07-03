#!/bin/bash
# build.sh — compile + signe SCKAudioPOC (ScreenCaptureKit)
# Usage : ./build.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SCRIPT_DIR/SCKAudioPOC"

echo "==> Compilation Swift (ScreenCaptureKit)..."
swiftc \
    -O \
    -framework ScreenCaptureKit \
    -framework AVFoundation \
    -framework CoreMedia \
    -framework Foundation \
    "$SCRIPT_DIR/SCKAudioPOC.swift" \
    -o "$OUT"

echo "==> Signature ad-hoc avec entitlements audio..."
codesign \
    --force \
    --sign - \
    --entitlements "$SCRIPT_DIR/entitlements.plist" \
    "$OUT"

echo "==> OK : $OUT"
echo ""
echo "IMPORTANT — premier lancement :"
echo "  macOS va demander la permission 'Enregistrement de l'écran'."
echo "  Si le terminal n'est pas déjà dans la liste, aller dans :"
echo "  Réglages Système › Confidentialité et sécurité › Enregistrement de l'écran"
echo "  → activer le terminal (iTerm2, Terminal, etc.)"
echo ""
echo "Utilisation :"
echo "  python3 test_tap.py 10"
