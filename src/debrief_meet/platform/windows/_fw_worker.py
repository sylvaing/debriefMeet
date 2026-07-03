"""
Worker process pour faster-whisper (CTranslate2) — isolation des crashes natifs
(DLL ctranslate2, drivers) et sémantique d'arrêt uniforme avec le pool MLX macOS
(docs/26, docs/34 §1). Miroir exact du protocole de `macos/_mlx_worker.py`.

Protocole stdin/stdout binaire :
  Requête  : 4 octets big-endian (longueur) + pickle(dict)
  Réponse  : 4 octets big-endian (longueur) + pickle(dict)
  Prêt     : "READY\\n" sur stderr après chargement du modèle

La séparation du canal de communication (stdout binaire) et des logs (stderr)
empêche les progress bars de huggingface_hub de corrompre le pipe.
"""
from __future__ import annotations

import os
import pickle
import sys


def main() -> None:
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_VERBOSITY"] = "warning"

    repo = os.environ.get("FW_WORKER_REPO", "Systran/faster-whisper-large-v3")
    download_root = os.environ.get("FW_WORKER_DOWNLOAD_ROOT") or None
    compute_type = os.environ.get("FW_WORKER_COMPUTE_TYPE", "int8")
    cpu_threads = int(os.environ.get("FW_WORKER_CPU_THREADS", "4"))

    from faster_whisper import WhisperModel
    import numpy as np

    model = WhisperModel(
        repo,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        download_root=download_root,
    )

    sys.stderr.write("READY\n")
    sys.stderr.flush()

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        header = stdin.read(4)
        if not header or len(header) < 4:
            break
        length = int.from_bytes(header, "big")
        data = stdin.read(length)
        if len(data) < length:
            break

        request = pickle.loads(data)
        if request.get("quit"):
            break

        try:
            audio = np.frombuffer(request["audio_bytes"], dtype=np.float32).copy()
            segments_iter, info = model.transcribe(
                audio,
                language=request.get("langue") or None,
                beam_size=5,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            segments = [{"start": s.start, "end": s.end, "text": s.text} for s in segments_iter]
            response = {
                "ok": True,
                "texte": "".join(s["text"] for s in segments).strip(),
                "langue": info.language,
                "segments": segments,
            }
        except Exception as exc:
            response = {"ok": False, "erreur": str(exc)}

        response_bytes = pickle.dumps(response)
        stdout.write(len(response_bytes).to_bytes(4, "big") + response_bytes)
        stdout.flush()


if __name__ == "__main__":
    main()
