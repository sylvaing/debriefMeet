#!/bin/bash
# build_ffmpeg.sh — compile un ffmpeg minimal LGPL (arm64) pour l'embarquer dans
# debriefMeet.app (docs/16 §5.5, décision utilisateur du 2026-07-12 : option b).
#
# Pourquoi compiler nous-mêmes plutôt qu'utiliser un prébuild communautaire :
# les prébuilds courants (evermeet, John Van Sickle…) sont quasi tous
# --enable-gpl (x264/x265…) et le binaire Homebrew embarque des dylibs
# /opt/homebrew non portables sur une machine cible sans brew (Bastien/Alix).
# Le code de l'app n'utilise que : encodage PCM→Opus (core/fichiers.py) et
# décodage Opus/PCM/WAV→PCM (core/audio.py) — entièrement dans le périmètre LGPL
# (--disable-gpl --disable-nonfree, libopus = BSD).
#
# Idempotent : si packaging/vendor/ffmpeg existe déjà et passe la validation,
# ne recompile pas. Usage : bash packaging/build_ffmpeg.sh [--force]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/packaging/vendor"
BUILD="$VENDOR/_build"
OUT="$VENDOR/ffmpeg"
LICENSE_OUT="$VENDOR/LICENSE-ffmpeg.md"

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

# ── Versions & checksums épinglés (sources officielles, vérifiés le 2026-07-12) ─
FFMPEG_VERSION="8.1.2"
FFMPEG_URL="https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz"
FFMPEG_SHA256="464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"

OPUS_VERSION="1.6.1"
OPUS_URL="https://downloads.xiph.org/releases/opus/opus-${OPUS_VERSION}.tar.gz"
OPUS_SHA256="6ffcb593207be92584df15b32466ed64bbec99109f007c82205f0194572411a1"

echo() { command echo "$@"; }
info() { echo "==> $*"; }
err()  { echo "✗ $*" >&2; exit 1; }

# ── Validation du binaire (réutilisée en sortie normale et pour le check idempotent) ─
valider_binaire() {
    local bin="$1"
    [[ -x "$bin" ]] || return 1
    # Aucune dépendance Homebrew/tierce : uniquement système.
    if otool -L "$bin" | tail -n +2 | grep -vqE '^\s*(/usr/lib|/System)/'; then
        otool -L "$bin" >&2
        err "binaire lié à des dylibs non-système (voir ci-dessus) — build non portable."
    fi
    "$bin" -hide_banner -encoders 2>/dev/null | grep -q "libopus" \
        || err "encodeur libopus absent du binaire compilé."
    # `aselect`/`asetpts` : compaction des silences avant envoi à Voxtral
    # (core/mistral/silences.py). Absents du build d'origine → la compaction échouait
    # DANS L'APP LIVRÉE et jamais en dev (ffmpeg Homebrew complet) : chaque transcription
    # envoyait l'audio intégral, silences compris (constaté le 2026-08-18).
    # `return 1` et non `err` : sur le chemin idempotent, un binaire dépourvu de ces
    # filtres doit être RECONSTRUIT, pas faire échouer le script.
    local dispo
    dispo="$("$bin" -hide_banner -filters 2>/dev/null | awk '{print $2}')"
    for filtre in aselect asetpts; do
        if ! grep -qx "$filtre" <<< "$dispo"; then
            echo "✗ filtre $filtre absent du binaire (compaction des silences cassée)" >&2
            return 1
        fi
    done
    # Muxer `segment` : repli découpage quand une piste entière est refusée
    # (core/mistral/decoupage.py). Absent du build d'origine → le repli échouait DANS
    # L'APP LIVRÉE et jamais en dev : sans ce muxer, ffmpeg ne reconnaît même pas
    # `-segment_time` et sort en 8 (« Unrecognized option »). Constaté le 2026-09-02
    # sur une réunion de 1 h 52 : 503 Mistral → repli découpage → CR perdu.
    # `return 1` pour la même raison que les filtres : reconstruire, pas échouer.
    if ! "$bin" -hide_banner -muxers 2>/dev/null | awk '{print $2}' | grep -qx "segment"; then
        echo "✗ muxer segment absent du binaire (repli découpage Mistral cassé)" >&2
        return 1
    fi
    "$bin" -version 2>/dev/null | grep -q -- "--enable-gpl" \
        && err "le binaire est compilé --enable-gpl (inattendu, licence non conforme)."
    return 0
}

if [[ -x "$OUT" ]] && ! $FORCE; then
    if valider_binaire "$OUT" 2>/dev/null; then
        info "binaire déjà présent et validé : $OUT (skip — utiliser --force pour rebuilder)"
        exit 0
    fi
    info "binaire présent mais invalide — reconstruction."
fi

command -v pkg-config >/dev/null || err "pkg-config introuvable (brew install pkg-config)."

mkdir -p "$BUILD"
NPROC="$(sysctl -n hw.ncpu 2>/dev/null || echo 4)"

# ── 1. Télécharge + vérifie les sources ─────────────────────────────────────────
descendre() {
    local url="$1" sha="$2" dest="$3"
    if [[ -f "$dest" ]] && [[ "$(shasum -a 256 "$dest" | awk '{print $1}')" == "$sha" ]]; then
        info "source déjà présente et vérifiée : $(basename "$dest")"
        return
    fi
    info "téléchargement : $url"
    curl -fSL --retry 3 -o "$dest" "$url"
    local obtenu
    obtenu="$(shasum -a 256 "$dest" | awk '{print $1}')"
    [[ "$obtenu" == "$sha" ]] || err "SHA-256 invalide pour $(basename "$dest") (attendu $sha, obtenu $obtenu)."
}

descendre "$OPUS_URL" "$OPUS_SHA256" "$BUILD/opus-${OPUS_VERSION}.tar.gz"
descendre "$FFMPEG_URL" "$FFMPEG_SHA256" "$BUILD/ffmpeg-${FFMPEG_VERSION}.tar.xz"

OPUS_SRC="$BUILD/opus-${OPUS_VERSION}"
FFMPEG_SRC="$BUILD/ffmpeg-${FFMPEG_VERSION}"
OPUS_PREFIX="$BUILD/opus-install"

rm -rf "$OPUS_SRC" "$FFMPEG_SRC" "$OPUS_PREFIX"
tar -xzf "$BUILD/opus-${OPUS_VERSION}.tar.gz" -C "$BUILD"
tar -xJf "$BUILD/ffmpeg-${FFMPEG_VERSION}.tar.xz" -C "$BUILD"

# Exécute une commande en journalisant sa sortie ; affiche la fin du journal et
# quitte en erreur si la commande échoue (sinon un `./configure` silencieux qui
# échoue ne laisserait aucune trace exploitable).
lancer() {
    local log="$1"; shift
    if ! "$@" >"$log" 2>&1; then
        echo "✗ échec de : $* — dernières lignes de $log :" >&2
        tail -60 "$log" >&2
        exit 1
    fi
}

# ── 2. libopus statique ──────────────────────────────────────────────────────────
info "compilation de libopus ${OPUS_VERSION} (statique)…"
(
    cd "$OPUS_SRC"
    lancer "$BUILD/opus-configure.log" \
        ./configure --prefix="$OPUS_PREFIX" --disable-shared --enable-static --disable-doc \
        --disable-extra-programs
    lancer "$BUILD/opus-make.log" make -j"$NPROC"
    lancer "$BUILD/opus-install.log" make install
)

# ── 3. ffmpeg minimal LGPL ────────────────────────────────────────────────────────
info "compilation de ffmpeg ${FFMPEG_VERSION} (LGPL minimal, libopus statique)…"
(
    cd "$FFMPEG_SRC"
    export PKG_CONFIG_PATH="$OPUS_PREFIX/lib/pkgconfig"
    lancer "$BUILD/ffmpeg-configure.log" \
        ./configure \
        --disable-gpl --disable-nonfree \
        --disable-everything \
        --disable-doc --disable-ffplay --disable-ffprobe \
        --disable-network --disable-avdevice \
        --disable-autodetect \
        --enable-protocol=file,pipe \
        --enable-demuxer=pcm_f32le,pcm_s16le,ogg,wav \
        --enable-muxer=opus,ogg,wav,pcm_s16le,segment \
        --enable-decoder=pcm_f32le,pcm_s16le,opus,libopus \
        --enable-encoder=pcm_s16le,libopus \
        --enable-filter=aresample,aformat,anull,aselect,asetpts \
        --enable-libopus \
        --pkg-config-flags="--static" \
        --extra-cflags="-I$OPUS_PREFIX/include" \
        --extra-ldflags="-L$OPUS_PREFIX/lib" \
        --disable-debug --disable-shared --enable-static
    lancer "$BUILD/ffmpeg-make.log" make -j"$NPROC" ffmpeg
)

mkdir -p "$VENDOR"
cp "$FFMPEG_SRC/ffmpeg" "$OUT"
chmod +x "$OUT"

info "validation du binaire produit…"
valider_binaire "$OUT" || err "validation du binaire produit en échec (voir ci-dessus)."

# ── 4. Test bout-en-bout : encode (commande core/fichiers.py) → décode (core/audio.py) ─
# `lavfi` (génération de signal) appartient à avdevice, désactivé ici — on génère le
# PCM brut en Python (aucune dépendance au venv du projet), comme le fait réellement
# core/fichiers.py qui pipe des échantillons f32le bruts sur stdin de ffmpeg.
info "test réel encode/décode (commandes exactes utilisées par l'app)…"
TMPT="$(mktemp -d)"
trap 'rm -rf "$TMPT"' EXIT
python3 -c '
import math, struct
with open("'"$TMPT"'/in.f32", "wb") as f:
    for i in range(16000):
        f.write(struct.pack("<f", 0.2 * math.sin(2 * math.pi * 440 * i / 16000)))
'
"$OUT" -y -loglevel error \
    -f f32le -ar 16000 -ac 1 -i pipe:0 \
    -c:a libopus -b:a 24k "$TMPT/test.opus" < "$TMPT/in.f32"
"$OUT" -y -loglevel error -i "$TMPT/test.opus" -ac 1 -ar 16000 -f wav "$TMPT/decode.wav"
[[ -s "$TMPT/test.opus" && -s "$TMPT/decode.wav" ]] || err "cycle encode/décode Opus en échec."
info "cycle encode → décode Opus OK."

# Compaction des silences (core/mistral/silences.py::compacter_piste) — les DEUX passes,
# avec la syntaxe exacte de l'app. Ce que la vérification des filtres seule ne dit pas :
# que la chaîne complète (aselect + asetpts + muxer wav + réencodage Opus) fonctionne.
info "test réel compaction des silences (2 passes, commandes exactes de l'app)…"
"$OUT" -y -loglevel error -i "$TMPT/test.opus" \
    -af "aselect='between(t,0.000,0.400)+between(t,0.600,0.900)',asetpts=N/SR" \
    -ac 1 -ar 16000 "$TMPT/compacte.wav"
"$OUT" -y -loglevel error -i "$TMPT/compacte.wav" -c:a libopus -b:a 24k "$TMPT/compacte.opus"
[[ -s "$TMPT/compacte.wav" && -s "$TMPT/compacte.opus" ]] \
    || err "compaction des silences en échec (aselect/asetpts)."
info "compaction des silences OK."

# Découpage en segments (core/mistral/decoupage.py::decouper_piste) — commande exacte du
# repli. La vérification du muxer seule ne dit pas que la chaîne complète fonctionne :
# `-f segment` délègue à un muxer enfant (ici `opus`) qui doit être présent lui aussi.
info "test réel découpage en segments (commande exacte du repli Mistral)…"
"$OUT" -y -loglevel error -i "$TMPT/test.opus" \
    -f segment -segment_time 1 -reset_timestamps 1 -c copy "$TMPT/seg_%03d.opus"
[[ -s "$TMPT/seg_000.opus" ]] || err "découpage en segments en échec (muxer segment)."
info "découpage en segments OK."

# ── 5. Licence (LGPL 2.1 + mention libopus BSD) ─────────────────────────────────
cat > "$LICENSE_OUT" <<EOF
# Licence — ffmpeg embarqué (vendor/ffmpeg)

Ce binaire est un build **minimal** de ffmpeg ${FFMPEG_VERSION}, compilé par
debriefMeet pour l'encodage/décodage Opus (rétention audio des réunions,
cf. \`docs/16-packaging-macos.md\` §5.5). Aucun composant \`--enable-gpl\` n'est
activé — build sous licence **LGPL 2.1 ou supérieure**.

- ffmpeg ${FFMPEG_VERSION} — https://ffmpeg.org — LGPL 2.1+ (\`--disable-gpl --disable-nonfree\`).
  Sources : ${FFMPEG_URL}
- libopus ${OPUS_VERSION} — https://opus-codec.org — licence BSD (liaison statique).
  Sources : ${OPUS_URL}

L'app invoque ce binaire en **subprocess** (programme séparé) : simple agrégation,
aucune contamination du code de l'app (\`src/debrief_meet\`, propriétaire).

Texte complet de la LGPL 2.1 : https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
EOF

info "OK : $OUT"
info "licence : $LICENSE_OUT"
