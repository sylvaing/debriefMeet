from __future__ import annotations

import subprocess

from debrief_meet.platform.interfaces import PressePapiers


class PressePapiersMaxOS(PressePapiers):
    def copier(self, texte: str) -> None:
        subprocess.run(["pbcopy"], input=texte.encode("utf-8"), check=True)

    def lire(self) -> str:
        return subprocess.run(["pbpaste"], capture_output=True).stdout.decode("utf-8")
