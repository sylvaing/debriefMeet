"""Lancement de ffmpeg — un seul point de passage, **stderr compris**.

Trois diagnostics terrain ont buté sur le même angle mort : `subprocess.run(...,
check=True, capture_output=True)` lève une `CalledProcessError` qui ne porte que la
commande et le code de sortie, et tous les appelants journalisent `exc`. Le message
de ffmpeg — la seule chose qui dise ce qu'il reproche — était donc systématiquement
perdu :

- **2026-09-02**, `exit 8` : muxer `segment` absent du ffmpeg embarqué, CR d'une
  réunion de 1 h 52 perdu (docs/42 §10.4). Rien dans « 8 » ne suggère un composant
  manquant ; ffmpeg disait « Unrecognized option ».
- **2026-09-07**, `exit 244` : expression `aselect` trop imbriquée (docs/42 §10.2).
  244 n'est documenté nulle part — c'est `AVERROR(ENOMEM)` rendu en octet non signé,
  et il a fallu rejouer la commande à la main pour lire « Cannot allocate memory ».

D'où ce module : les codes de sortie de ffmpeg sont des `AVERROR` négatifs repliés
sur un octet, ils ne se lisent pas ; le texte, lui, se lit. Le résumé est borné parce
que ffmpeg réémet l'expression de filtre fautive dans son message (3 ko mesurés),
alors que l'information tient dans les dernières lignes.
"""
from __future__ import annotations

import subprocess

#: Nombre de lignes de stderr conservées (les dernières : ffmpeg y met son verdict).
MAX_LIGNES_STDERR = 5
#: Longueur au-delà de laquelle une ligne — ou un argument de la commande — est tronquée.
MAX_CAR_LIGNE = 200


class ErreurFfmpeg(RuntimeError):
    """Échec d'une commande ffmpeg, avec le résumé de stderr dans le message."""


def abreger(texte: str) -> str:
    """Tronque `texte` en annonçant ce qui a été retiré."""
    if len(texte) <= MAX_CAR_LIGNE:
        return texte
    return f"{texte[:MAX_CAR_LIGNE]}… (+{len(texte) - MAX_CAR_LIGNE} car.)"


def resumer_stderr(flux: bytes | str | None) -> str:
    """Dernières lignes de stderr, chacune tronquée — journalisables telles quelles."""
    if not flux:
        return "aucune sortie d'erreur"
    texte = flux.decode("utf-8", "replace") if isinstance(flux, bytes) else flux
    lignes = [ligne.strip() for ligne in texte.splitlines() if ligne.strip()]
    if not lignes:
        return "aucune sortie d'erreur"
    return " | ".join(abreger(ligne) for ligne in lignes[-MAX_LIGNES_STDERR:])


def executer(exe: str, *args: str) -> None:
    """Lance `exe` avec `args` et lève `ErreurFfmpeg` en cas d'échec.

    Aucun argument implicite : chaque appelant garde la maîtrise de sa commande
    (`-y`, `-loglevel`…), qui reste ainsi reproductible telle qu'elle apparaît dans
    le message d'erreur."""
    commande = [exe, *args]
    try:
        subprocess.run(
            commande,
            check=True, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.CalledProcessError as exc:
        raise ErreurFfmpeg(
            f"ffmpeg code {exc.returncode} : {resumer_stderr(exc.stderr)}"
            f" — commande : {' '.join(abreger(a) for a in commande)}"
        ) from exc
