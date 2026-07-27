#!/bin/bash
# build_dmg.sh — empaquette dist/debriefMeet.app dans un .dmg d'installation
# (glisser-déposer vers /Applications). Cf. docs/16-packaging-macos.md §5.3.
#
# Usage : bash packaging/build_dmg.sh   (après packaging/build_app.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_BUILD="$ROOT/.venv-build"
APP="$ROOT/dist/debriefMeet.app"

info() { echo "==> $*"; }
err()  { echo "✗ $*" >&2; exit 1; }

[[ -d "$APP" ]] || err "$APP introuvable. Lancer d'abord : bash packaging/build_app.sh"
command -v create-dmg >/dev/null || err "create-dmg introuvable (brew install create-dmg)."
[[ -x "$VENV_BUILD/bin/python" ]] || err "$VENV_BUILD/bin/python introuvable (voir docs/16 §2)."

# VERSION_COMPLETE (pas seulement __version__) : parité avec le nom du setup
# Windows (debriefMeet-setup-<VERSION_COMPLETE>.exe, docs/32 §1) — porte le hash
# git si packaging/build_app.sh a généré src/debrief_meet/_version.py juste avant,
# sinon repli "<version>+dev" (comportement normal de debrief_meet.__init__).
VERSION="$("$VENV_BUILD/bin/python" -c "import debrief_meet; print(debrief_meet.VERSION_COMPLETE)")"
OUT="$ROOT/dist/debriefMeet-$VERSION.dmg"

rm -f "$OUT"
info "création de ${OUT}…"
create-dmg --volname "debriefMeet" --app-drop-link 450 180 "$OUT" "$APP"

info "OK : $OUT"
