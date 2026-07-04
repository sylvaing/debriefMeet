"""Icône WaveMark par état d'activité (`EtatVisuel`) — tray et toolbar de la
fenêtre principale (source unique, cf. IMPLEMENTATION_SPEC.md §8).

REPOS = contour (template : s'adapte à la barre macOS claire/sombre) ; les
autres états sont pleins, colorés selon `theme.C.TRAY_*`.
"""
from __future__ import annotations

from PySide6.QtGui import QIcon

from debrief_meet.core.modes import EtatVisuel
from debrief_meet.ui.theme import C
from debrief_meet.ui.wavemark import wavemark_icon

_COULEURS_ETAT: dict[EtatVisuel, tuple[str, bool]] = {
    EtatVisuel.REPOS: (C.TRAY_IDLE, False),
    EtatVisuel.ENREGISTREMENT: (C.TRAY_RECORDING, True),
    EtatVisuel.TRANSCRIPTION: (C.TRAY_TRANSCRIBE, True),
    EtatVisuel.TERMINE: (C.TRAY_DONE, True),
    EtatVisuel.ERREUR: (C.TRAY_ERROR, True),
}


def icone_wavemark_pour_etat(etat: EtatVisuel, taille: int = 22) -> QIcon:
    couleur, rempli = _COULEURS_ETAT[etat]
    return wavemark_icon(taille, couleur, filled=rempli)
