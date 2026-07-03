#!/usr/bin/env bash
#
# Spike AEC WebRTC — installation du moteur AEC3 retenu : SDK LiveKit.
#
# livekit.rtc.AudioProcessingModule expose l'APM WebRTC de production (AEC3),
# utilisable en standalone (sans serveur). Le wheel est `py3-none` (binaire
# Rust/FFI, pas une extension CPython) → s'installe sur Python 3.14 SANS build.
#
set -euo pipefail

RACINE="$(cd "$(dirname "$0")/../.." && pwd)"
PIP="$RACINE/.venv/bin/pip"
VENV_PY="$RACINE/.venv/bin/python"
[ -x "$VENV_PY" ] || { echo "ERREUR : venv introuvable ($VENV_PY)." >&2; exit 1; }

echo "→ Installation de livekit (wheel py3-none, sans compilation)…"
"$PIP" install --only-binary :all: livekit

echo "→ Vérification de l'import (APM AEC3, standalone)…"
"$VENV_PY" - <<'PY'
import numpy as np
from livekit import rtc
apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True,
                                high_pass_filter=True)
apm.set_stream_delay_ms(0)
n = 160  # 10 ms @ 16 kHz
z = np.zeros(n, np.int16).tobytes()
apm.process_reverse_stream(rtc.AudioFrame(data=z, sample_rate=16000,
                                          num_channels=1, samples_per_channel=n))
apm.process_stream(rtc.AudioFrame(data=z, sample_rate=16000,
                                  num_channels=1, samples_per_channel=n))
print("OK — livekit.rtc.AudioProcessingModule (AEC3) fonctionnel en standalone.")
PY
