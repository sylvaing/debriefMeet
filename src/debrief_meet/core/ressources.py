"""Résolution des ressources embarquées (helper Swift, etc.).

En développement, les ressources vivent dans l'arborescence du dépôt. Une fois
l'app figée par PyInstaller, elles sont extraites sous ``sys._MEIPASS``. Ce
module masque la différence : on utilise **le même chemin relatif** dans les
deux cas (la spec PyInstaller place les ressources à la même position relative).
"""

from __future__ import annotations

import sys
from pathlib import Path


def est_figee() -> bool:
    """True si on tourne dans une app PyInstaller (``.app`` packagée)."""
    return bool(getattr(sys, "frozen", False))


def _racine_ressources() -> Path:
    if est_figee():
        # PyInstaller extrait les datas sous _MEIPASS (repli : dossier du binaire).
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # Dev : racine du dépôt — src/debrief_meet/core/ressources.py → parents[3].
    return Path(__file__).resolve().parents[3]


def chemin_ressource(*parties: str) -> Path:
    """Chemin absolu d'une ressource, relatif à la racine (dépôt ou bundle)."""
    return _racine_ressources().joinpath(*parties)


def chemin_ffmpeg() -> str | None:
    """Chemin du ffmpeg à utiliser : embarqué (bundle Windows, docs/41) d'abord,
    PATH en repli.

    Retourne None si aucun ffmpeg n'est disponible (l'appelant se replie en WAV
    ou lève, selon le contexte). Pas de condition `est_figee()` : en dev le
    dossier embarqué n'existe pas (repli PATH naturel) ; en bundle il gagne
    toujours, même si le poste a un autre ffmpeg sur son PATH (déterminisme de
    version)."""
    import shutil

    nom = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    embarque = chemin_ressource("ffmpeg", nom)
    if embarque.exists():
        return str(embarque)
    return shutil.which("ffmpeg")
