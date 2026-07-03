"""
Worker process pour mlx_whisper — isolation des crashes Metal (SIGBUS).

Protocole stdin/stdout binaire :
  Requête  : 4 octets big-endian (longueur) + pickle(dict)
  Réponse  : 4 octets big-endian (longueur) + pickle(dict)
  Prêt     : "READY\\n" sur stderr après préchargement du modèle

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

    repo = os.environ.get("MLX_WORKER_REPO", "mlx-community/whisper-large-v3-mlx")

    import mlx_whisper
    import numpy as np

    # Précharge le modèle avec 1 s de silence pour initialiser Metal
    mlx_whisper.transcribe(
        np.zeros(16_000, dtype=np.float32),
        path_or_hf_repo=repo,
        language="en",
        verbose=None,
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
            result = mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=request["repo"],
                language=request.get("langue") or None,
                verbose=None,
                condition_on_previous_text=False,
            )
            response = {
                "ok": True,
                "texte": result["text"].strip(),
                "langue": result.get("language"),
                "segments": result.get("segments", []),
            }
        except Exception as exc:
            response = {"ok": False, "erreur": str(exc)}

        response_bytes = pickle.dumps(response)
        stdout.write(len(response_bytes).to_bytes(4, "big") + response_bytes)
        stdout.flush()


if __name__ == "__main__":
    main()
