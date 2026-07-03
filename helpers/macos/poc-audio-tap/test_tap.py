#!/usr/bin/env python3
"""
test_tap.py — orchestrateur Python pour le POC Core Audio taps.

Lance le binaire AudioTapPOC, lit le PCM float32 sur stdout, et sauvegarde un WAV.
Le format réel (sample rate, canaux) est détecté depuis la ligne "FORMAT:<sr>:<ch>"
que le binaire écrit sur stderr au démarrage.

Usage (après ./build.sh) :
    python3 test_tap.py [durée_secondes]     # défaut : 10 s
    python3 test_tap.py 30                   # 30 s de capture
"""
from __future__ import annotations

import struct
import subprocess
import sys
import threading
import wave
from pathlib import Path

HERE   = Path(__file__).parent
BINARY = HERE / "SCKAudioPOC"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 10


def main() -> None:
    if not BINARY.exists():
        print(f"[ERREUR] Binaire introuvable : {BINARY}")
        print("         Lance d'abord :  ./build.sh")
        sys.exit(1)

    print(f"[TEST] Lancement : {BINARY} {DURATION}s")
    print("       → Joue quelque chose (musique, visio…) pendant la capture.\n")

    proc = subprocess.Popen(
        [str(BINARY), str(DURATION)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Lire la ligne FORMAT:<sr>:<ch> depuis stderr dans un thread
    sample_rate = 48_000
    channels    = 1
    format_ready = threading.Event()

    def relay_stderr() -> None:
        nonlocal sample_rate, channels
        assert proc.stderr
        for raw in proc.stderr:
            line = raw.decode(errors="replace").rstrip()
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
            if line.startswith("FORMAT:"):
                parts = line.split(":")
                if len(parts) == 3:
                    sample_rate = int(parts[1])
                    channels    = int(parts[2])
                    format_ready.set()

    t = threading.Thread(target=relay_stderr, daemon=True)
    t.start()

    # Attendre que le format soit connu (timeout 8 s)
    if not format_ready.wait(timeout=8.0):
        print("[ERREUR] Aucune ligne FORMAT reçue — le binaire n'a pas démarré correctement.")
        proc.terminate()
        sys.exit(1)

    bytes_per_frame = channels * 4  # float32 = 4 octets
    total_bytes     = sample_rate * DURATION * bytes_per_frame
    print(f"[TEST] Format : {sample_rate}Hz {channels}ch — attente de {total_bytes:,} octets ({DURATION}s)…")

    assert proc.stdout
    raw = proc.stdout.read(total_bytes)
    proc.wait()
    t.join(timeout=2)

    received_frames = len(raw) // bytes_per_frame
    received_sec    = received_frames / sample_rate
    print(f"\n[TEST] Reçu : {len(raw):,} octets — {received_frames:,} frames — {received_sec:.2f}s")

    if len(raw) < bytes_per_frame:
        print("[ERREUR] Aucun audio reçu — voir les logs Swift ci-dessus.")
        sys.exit(1)

    # Analyser l'énergie
    n_floats = len(raw) // 4
    samples  = struct.unpack(f"<{n_floats}f", raw[:n_floats * 4])
    rms  = (sum(s * s for s in samples) / len(samples)) ** 0.5
    peak = max(abs(s) for s in samples)
    print(f"[TEST] Énergie — RMS={rms:.4f}  Pic={peak:.4f}")
    if rms < 1e-6:
        print("[ATTENTION] Signal quasi-nul — l'audio système était peut-être silencieux.")
    else:
        print("[OK] Signal présent ✓")

    # Sauvegarder en WAV (float32 → int16)
    wav_path = HERE / f"poc_capture_{DURATION}s.wav"
    pcm16 = [max(-32768, min(32767, int(s * 32767))) for s in samples]
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(pcm16)}h", *pcm16))

    print(f"[TEST] WAV sauvegardé : {wav_path}")
    print("\n=== RAPPORT GO/NO-GO ===")
    print(f"  Format           : {sample_rate}Hz {channels}ch")
    print(f"  Durée capturée   : {received_sec:.1f}s / {DURATION}s demandés")
    print(f"  RMS              : {rms:.4f}")
    print(f"  Pic              : {peak:.4f}")
    print(f"  Fichier WAV      : {wav_path.name}")
    print()
    print("  → Ouvre le WAV dans QuickTime ou un éditeur audio.")
    print("  → Vérifie que tu entends les participants d'une visio (pas seulement ton micro).")
    print("  → Si OK : GO pour la Phase 2 (mode Réunion).")
    print("  → Si silencieux ou erreur Swift : voir les logs ci-dessus, reporter ici.")


if __name__ == "__main__":
    main()
