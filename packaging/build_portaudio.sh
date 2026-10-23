#!/bin/bash
# build_portaudio.sh — compile PortAudio v19.7.0 + le correctif amont de l'interblocage
# CoreAudio (PortAudio#1174/#1175) pour remplacer la dylib embarquée par sounddevice
# dans debriefMeet.app (docs/16 §5.7).
#
# Pourquoi : la dylib livrée par sounddevice (v19.7.0, 2021) peut s'interbloquer à
# l'ARRÊT d'un flux — le listener `kAudioOutputUnitProperty_IsRunning` appelle
# `AudioUnitGetProperty` sur le thread d'E/S du HAL, qui tient son mutex, pendant que
# `Pa_StopStream` tient celui de l'AudioUnit et attend celui du HAL. Constaté le
# 2026-10-23 sur le Mac de Sylvain : micro resté ouvert (pastille orange) après la fin
# d'une réunion, puis app figée à la sortie dans `Pa_Terminate`. Reproduit le même jour
# sur la dylib livrée (blocage en 265 à 327 cycles), corrigé par ce patch.
# Le correctif est fusionné en amont mais dans AUCUNE release : on le compile.
#
# Idempotent : si packaging/vendor/libportaudio.dylib existe déjà et passe la
# validation, ne recompile pas. Usage : bash packaging/build_portaudio.sh [--force]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/packaging/vendor"
BUILD="$VENDOR/_build"
OUT="$VENDOR/libportaudio.dylib"
LICENSE_OUT="$VENDOR/LICENSE-portaudio.md"
PATCH="$ROOT/packaging/patches/portaudio-1175-coreaudio-deadlock.patch"

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

# ── Version & checksum épinglés (archive officielle, vérifiée le 2026-10-23) ──────
PA_VERSION="19.7.0"
PA_URL="https://files.portaudio.com/archives/pa_stable_v190700_20210406.tgz"
PA_SHA256="47efbf42c77c19a05d22e627d42873e991ec0c1357219c0d74ce6a2948cb2def"

# Chaîne propre au patch (libellé de la file GCD créée par OpenStream) : sa présence
# prouve que la dylib est bien la version corrigée, pas celle de sounddevice.
MARQUEUR_PATCH="PortAudio.CoreAudio.startStop"

info() { echo "==> $*"; }
err()  { echo "✗ $*" >&2; exit 1; }

# ── Validation (réutilisée en sortie normale et pour le check idempotent) ─────────
# `return 1` et non `err` : sur le chemin idempotent, une dylib invalide doit être
# RECONSTRUITE, pas faire échouer le script.
valider_dylib() {
    local lib="$1"
    [[ -f "$lib" ]] || return 1
    # Même nom d'installation que la dylib de sounddevice (chargée par dlopen).
    if [[ "$(otool -D "$lib" | tail -1)" != "@rpath/libportaudio.dylib" ]]; then
        echo "✗ nom d'installation inattendu : $(otool -D "$lib" | tail -1)" >&2
        return 1
    fi
    # Aucune dépendance Homebrew/tierce : uniquement système. Seules les lignes
    # indentées sont des dépendances (dylib universelle : un en-tête par architecture).
    if otool -L "$lib" | grep -E '^\s' | grep -vqE '^\s*(@rpath/libportaudio\.dylib|/usr/lib/|/System/)'; then
        otool -L "$lib" >&2
        echo "✗ dylib liée à des bibliothèques non-système (voir ci-dessus)" >&2
        return 1
    fi
    if ! lipo -archs "$lib" | tr ' ' '\n' | grep -qx arm64; then
        echo "✗ architecture arm64 absente ($(lipo -archs "$lib"))" >&2
        return 1
    fi
    if ! strings "$lib" | grep -q "$MARQUEUR_PATCH"; then
        echo "✗ correctif #1175 absent de la dylib (marqueur « $MARQUEUR_PATCH »)" >&2
        return 1
    fi
    return 0
}

if [[ -f "$OUT" ]] && ! $FORCE; then
    if valider_dylib "$OUT" 2>/dev/null; then
        info "dylib déjà présente et validée : $OUT (skip — utiliser --force pour rebuilder)"
        exit 0
    fi
    info "dylib présente mais invalide — reconstruction."
fi

command -v cmake >/dev/null || err "cmake introuvable (brew install cmake)."
[[ -f "$PATCH" ]] || err "patch introuvable : $PATCH"

mkdir -p "$BUILD"
NPROC="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"

# ── 1. Télécharge + vérifie la source ─────────────────────────────────────────────
ARCHIVE="$BUILD/pa_stable_v${PA_VERSION}.tgz"
if [[ -f "$ARCHIVE" ]] && [[ "$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')" == "$PA_SHA256" ]]; then
    info "source déjà présente et vérifiée : $(basename "$ARCHIVE")"
else
    info "téléchargement : $PA_URL"
    curl -fSL --retry 3 -o "$ARCHIVE" "$PA_URL"
    obtenu="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
    [[ "$obtenu" == "$PA_SHA256" ]] || err "SHA-256 invalide pour $(basename "$ARCHIVE") (attendu $PA_SHA256, obtenu $obtenu)."
fi

SRC="$BUILD/portaudio"
CMAKE_BUILD="$BUILD/portaudio-build"
rm -rf "$SRC" "$CMAKE_BUILD"
tar -xzf "$ARCHIVE" -C "$BUILD"

# ── 2. Patch amont #1175 ──────────────────────────────────────────────────────────
info "application du correctif PortAudio#1175…"
( cd "$SRC" && patch -p1 --forward --quiet < "$PATCH" ) || err "le patch ne s'applique pas sur v${PA_VERSION}."

# ── 3. Compilation ────────────────────────────────────────────────────────────────
# Universelle et minos 11.0 comme la dylib de sounddevice qu'elle remplace (PyInstaller
# l'amincit ensuite en arm64). CMAKE_POLICY_VERSION_MINIMUM : le CMakeLists de 2021
# déclare un minimum < 3.5, refusé par CMake 4.
info "compilation de PortAudio ${PA_VERSION} + #1175 (universelle, macOS 11+)…"
LOG="$BUILD/portaudio-build.log"
if ! { cmake -S "$SRC" -B "$CMAKE_BUILD" \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_BUILD_TYPE=Release \
        -DPA_BUILD_SHARED=ON -DPA_BUILD_STATIC=OFF \
        -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64" \
        -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0 \
        -DCMAKE_INSTALL_NAME_DIR=@rpath \
    && cmake --build "$CMAKE_BUILD" -j"$NPROC"; } >"$LOG" 2>&1; then
    tail -60 "$LOG" >&2
    err "compilation en échec (journal : $LOG)."
fi

# Validée AVANT la copie : une dylib refusée laissée dans vendor/ pourrait passer
# le contrôle idempotent d'un appel suivant sans que la licence soit écrite.
info "validation de la dylib produite…"
valider_dylib "$CMAKE_BUILD/libportaudio.dylib" \
    || err "validation de la dylib produite en échec (voir ci-dessus)."
mkdir -p "$VENDOR"
cp "$CMAKE_BUILD/libportaudio.dylib" "$OUT"

# ── 4. Licence ────────────────────────────────────────────────────────────────────
{
    cat <<EOF
# Licence — PortAudio embarqué (vendor/libportaudio.dylib)

PortAudio ${PA_VERSION} (${PA_URL}), compilé par debriefMeet avec le correctif amont
PortAudio#1175 (interblocage CoreAudio à l'arrêt d'un flux, cf. docs/16 §5.7).
Remplace la dylib fournie par le paquet Python \`sounddevice\`.

EOF
    cat "$SRC/LICENSE.txt"
} > "$LICENSE_OUT"

info "OK : $OUT"
info "licence : $LICENSE_OUT"
