#!/bin/bash
# build.sh — compile + signe SCKAudioCapture (ScreenCaptureKit), version production.
# Usage : ./build.sh
#
# Signature : ad-hoc par défaut. Pour le packaging (.app), passer l'identité
# stable afin que l'helper et l'app partagent la même signature (permissions TCC
# persistantes) :
#     CODESIGN_IDENTITY="debriefMeet Local" ./build.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="$SCRIPT_DIR/SCKAudioCapture"
IDENTITY="${CODESIGN_IDENTITY:--}"   # "-" = signature ad-hoc

echo "==> Compilation Swift (ScreenCaptureKit)..."
swiftc \
    -O \
    -framework ScreenCaptureKit \
    -framework AVFoundation \
    -framework CoreMedia \
    -framework Foundation \
    "$SCRIPT_DIR/SCKAudioCapture.swift" \
    -o "$OUT"

echo "==> Signature (identité : $IDENTITY) avec entitlements audio..."
codesign \
    --force \
    --sign "$IDENTITY" \
    --entitlements "$SCRIPT_DIR/entitlements.plist" \
    "$OUT"

echo "==> OK : $OUT"
