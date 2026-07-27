#!/bin/bash
# build_app.sh — construit dist/debriefMeet.app avec une signature STABLE.
#
# Orchestration (docs/16-packaging-macos.md §5.2) :
#   1. Identité de signature stable (créée une fois, idempotent).
#   2. Helper SCK recompilé + signé avec cette identité.
#   3. VERSION_COMPLETE (mêmes forme et outillage que Windows, docs/32) :
#      "<__version__>+<AAAAMMJJ>.<hash-git-court>" → src/debrief_meet/_version.py,
#      embarqué dans le bundle par PyInstaller.
#   4. PyInstaller (packaging/debriefMeet.spec).
#   5. Signature de l'app (sans --options runtime : mlx/torch ont besoin de
#      mémoire exécutable non signée — le hardened runtime n'est requis que
#      pour la notarisation, hors périmètre v1).
#   6. Re-signature du helper (ses entitlements sont perdus au `--deep` de l'app).
#   7. Signature du binaire ffmpeg embarqué (vendor/).
#   8. Re-scellage de l'app (sans --deep, pour prendre en compte 6+7).
#
# Usage : bash packaging/build_app.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IDENTITY="debriefMeet Local"
VENV_BUILD="$ROOT/.venv-build"
PYINSTALLER="$VENV_BUILD/bin/pyinstaller"
APP="$ROOT/dist/debriefMeet.app"
HELPER_IN_APP="$APP/Contents/Resources/helpers/macos/sck-audio/SCKAudioCapture"
FFMPEG_IN_APP="$APP/Contents/Resources/vendor/ffmpeg"

info() { echo "==> $*"; }
err()  { echo "✗ $*" >&2; exit 1; }

[[ -x "$PYINSTALLER" ]] || err "$PYINSTALLER introuvable. Créer le venv de build (Python 3.13) :
    python3.13 -m venv .venv-build
    .venv-build/bin/pip install -e \".[macos]\" pyinstaller
(docs/16-packaging-macos.md §2)"

[[ -x "$ROOT/packaging/vendor/ffmpeg" ]] || err "packaging/vendor/ffmpeg introuvable. Lancer d'abord :
    bash packaging/build_ffmpeg.sh
(docs/16-packaging-macos.md §5.5)"

# ── 1. Identité de signature stable ─────────────────────────────────────────────
info "identité de signature stable…"
bash "$ROOT/packaging/creer_certificat.sh"

# ── 2. Helper SCK signé stable ───────────────────────────────────────────────────
info "recompilation du helper SCK (signature : $IDENTITY)…"
CODESIGN_IDENTITY="$IDENTITY" bash "$ROOT/helpers/macos/sck-audio/build.sh"

# ── 3. VERSION_COMPLETE (parité avec le build Windows, docs/32) ─────────────────
# BUILD_INFO n'est pas propre à la VM Windows : ici c'est juste le format d'échange
# attendu par generer_version.py (générique, aucun import Windows-only). Nettoyé en
# sortie (jamais commité — .gitignore), _version.py reste (comme sur la VM Windows :
# c'est lui qui porte le hash, PyInstaller doit le trouver sur disque).
info "génération de VERSION_COMPLETE (date + hash git)…"
date -u +%Y%m%d > "$ROOT/BUILD_INFO"
git -C "$ROOT" rev-parse --short HEAD >> "$ROOT/BUILD_INFO"
trap 'rm -f "$ROOT/BUILD_INFO"' EXIT
"$VENV_BUILD/bin/python" "$ROOT/packaging/windows/generer_version.py" \
    --build-info "$ROOT/BUILD_INFO"

# ── 4. PyInstaller ────────────────────────────────────────────────────────────────
info "PyInstaller (packaging/debriefMeet.spec)…"
rm -rf "$APP"
"$PYINSTALLER" "$ROOT/packaging/debriefMeet.spec" --noconfirm \
    --distpath "$ROOT/dist" --workpath "$ROOT/build/work"
[[ -d "$APP" ]] || err "PyInstaller n'a pas produit $APP."

# ── 5. Signature de l'app ────────────────────────────────────────────────────────
info "signature de l'app (identité : $IDENTITY)…"
codesign --force --deep --sign "$IDENTITY" "$APP"

# ── 6. Re-signature du helper avec ses entitlements ─────────────────────────────
info "re-signature du helper SCK avec ses entitlements…"
[[ -f "$HELPER_IN_APP" ]] || err "helper introuvable dans le bundle : $HELPER_IN_APP"
codesign --force --sign "$IDENTITY" \
    --entitlements "$ROOT/helpers/macos/sck-audio/entitlements.plist" \
    "$HELPER_IN_APP"

# ── 7. Signature du binaire ffmpeg embarqué ─────────────────────────────────────
info "signature du binaire ffmpeg embarqué…"
[[ -f "$FFMPEG_IN_APP" ]] || err "ffmpeg introuvable dans le bundle : $FFMPEG_IN_APP"
codesign --force --sign "$IDENTITY" "$FFMPEG_IN_APP"

# ── 8. Re-scellage de l'app (sans --deep) ───────────────────────────────────────
info "re-scellage de l'app…"
codesign --force --sign "$IDENTITY" "$APP"

info "vérification…"
codesign -dv --verbose=4 "$APP" 2>&1 | grep -E "Authority|Identifier"

info "OK : $APP"
echo "    Comparer l'Authority ci-dessus entre deux builds : elle doit être IDENTIQUE"
echo "    (garantie que TCC conservera les permissions Micro/Enregistrement de l'écran)."
