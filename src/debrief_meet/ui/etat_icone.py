"""Icône WaveMark par état d'activité (`EtatVisuel`) — tray et toolbar de la
fenêtre principale (source unique, cf. IMPLEMENTATION_SPEC.md §8).

REPOS = monochrome ; les autres états sont pleins, colorés selon `theme.C.TRAY_*`.

Le rendu du REPOS dépend de la **couleur de la barre système**, pas du thème de
l'application :

* macOS/Windows — barre claire : contour `TRAY_IDLE` (gris ardoise), le « template »
  attendu par la barre de menus macOS ;
* Linux — le bandeau GNOME est noir *y compris en thème clair*, donc un contour gris
  foncé y est illisible (constaté chez le premier utilisateur Linux). On y garde le
  **contour**, en blanc. ⚠️ Surtout pas « blanc plein » : `wavemark_icon` peint les
  barres en blanc SUR le carré coloré, donc un plein blanc donne un carré blanc uni,
  sans la marque — livré par erreur le 2026-08-18 avant d'être corrigé.

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


def repos_pour(barre_sombre: bool) -> tuple[str, bool, bool]:
    """(couleur, rempli, masque) de l'état REPOS selon la couleur de la barre système.

    Fonction plutôt que constante calculée : les deux branches restent testables
    sans `importlib.reload` — dangereux sur un module qui touche Qt (docs/26).

    Dans les deux cas l'icône est un **contour** : c'est lui qui dessine la marque.
    Seuls changent la couleur et le masque — sur barre claire, `setIsMask(True)`
    laisse macOS reteindre lui-même l'icône selon sa barre de menus (correct en clair
    comme en sombre) ; sur barre sombre la couleur est déjà la bonne, et le drapeau
    est de toute façon ignoré sous Linux."""
    if barre_sombre:
        return (C.TRAY_IDLE_BARRE_SOMBRE, False, False)
    return (C.TRAY_IDLE, False, True)


_REPOS = repos_pour(_BARRE_SOMBRE)

_COULEURS_ETAT: dict[EtatVisuel, tuple[str, bool, bool]] = {
    EtatVisuel.REPOS: _REPOS,
    EtatVisuel.ENREGISTREMENT: (C.TRAY_RECORDING, True, False),
    EtatVisuel.TRANSCRIPTION: (C.TRAY_TRANSCRIBE, True, False),
    EtatVisuel.TERMINE: (C.TRAY_DONE, True, False),
    EtatVisuel.ERREUR: (C.TRAY_ERROR, True, False),
}


def icone_wavemark_pour_etat(etat: EtatVisuel, taille: int = 22) -> QIcon:
    couleur, rempli, masque = _COULEURS_ETAT[etat]
    return wavemark_icon(taille, couleur, filled=rempli, masque=masque)
