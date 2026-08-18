"""Icône WaveMark par état d'activité (`EtatVisuel`) — tray et toolbar de la
fenêtre principale (source unique, cf. IMPLEMENTATION_SPEC.md §8).

REPOS = monochrome ; les autres états sont pleins, colorés selon `theme.C.TRAY_*`.

Le rendu du REPOS dépend de la **couleur de la barre système**, pas du thème de
l'application :

* macOS/Windows — barre claire : contour `TRAY_IDLE` (gris ardoise), le « template »
  attendu par la barre de menus macOS ;
* Linux — le bandeau GNOME est noir *y compris en thème clair*, donc un contour gris
  foncé y est illisible (constaté chez le premier utilisateur Linux). On y bascule
  sur du **blanc plein** : un contour blanc de 6 % d'épaisseur reste peu lisible à
  22 px sur fond noir.

⚠️ Ne pas dériver ce choix de `QGuiApplication.styleHints().colorScheme()` : celui-ci
rapporte la préférence claire/sombre de l'application, sans rapport avec la couleur
du bandeau — sous Ubuntu en thème clair, il resterait noir.
"""
from __future__ import annotations

import sys

from PySide6.QtGui import QIcon

from debrief_meet.core.modes import EtatVisuel
from debrief_meet.ui.theme import C
from debrief_meet.ui.wavemark import wavemark_icon

_BARRE_SOMBRE = sys.platform.startswith("linux")


def repos_pour(barre_sombre: bool) -> tuple[str, bool]:
    """(couleur, rempli) de l'état REPOS selon la couleur de la barre système.

    Fonction plutôt que constante calculée : les deux branches restent testables
    sans `importlib.reload` — dangereux sur un module qui touche Qt (docs/26).

    Le `rempli=False` de la barre claire vaut aussi `setIsMask(True)` côté
    `wavemark_icon` : macOS reteint alors lui-même l'icône selon sa barre de menus,
    ce qui la rend correcte en clair comme en sombre. Cette bascule n'existe pas
    sous Linux (le drapeau y est ignoré), d'où la couleur explicite."""
    return (C.TRAY_IDLE_BARRE_SOMBRE, True) if barre_sombre else (C.TRAY_IDLE, False)


_REPOS = repos_pour(_BARRE_SOMBRE)

_COULEURS_ETAT: dict[EtatVisuel, tuple[str, bool]] = {
    EtatVisuel.REPOS: _REPOS,
    EtatVisuel.ENREGISTREMENT: (C.TRAY_RECORDING, True),
    EtatVisuel.TRANSCRIPTION: (C.TRAY_TRANSCRIBE, True),
    EtatVisuel.TERMINE: (C.TRAY_DONE, True),
    EtatVisuel.ERREUR: (C.TRAY_ERROR, True),
}


def icone_wavemark_pour_etat(etat: EtatVisuel, taille: int = 22) -> QIcon:
    couleur, rempli = _COULEURS_ETAT[etat]
    return wavemark_icon(taille, couleur, filled=rempli)
