from __future__ import annotations

import subprocess
from pathlib import Path

from debrief_meet.platform.interfaces import PressePapiers


class PressePapiersMaxOS(PressePapiers):
    def copier(self, texte: str) -> None:
        subprocess.run(["pbcopy"], input=texte.encode("utf-8"), check=True)

    def copier_fichier(self, chemin: Path) -> None:
        # `osascript` plutôt que le presse-papiers Qt : c'est le seul mécanisme dont
        # le collage dans le Finder est garanti (public.file-url natif). Le chemin
        # passe par argv — jamais interpolé dans le script (guillemets, injection).
        subprocess.run(
            ["osascript",
             "-e", "on run argv",
             "-e", "set the clipboard to POSIX file (item 1 of argv)",
             "-e", "end run",
             str(chemin)],
            check=True)

    def lire(self) -> str:
        return subprocess.run(["pbpaste"], capture_output=True).stdout.decode("utf-8")
