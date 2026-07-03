"""Démarrage automatique Windows — Registre `HKCU\\...\\Run` (docs/34 §4).

`winreg` est importé paresseusement dans chaque méthode (module absent hors Windows,
et ça permet aux tests de l'injecter dans `sys.modules` sans dépendre de l'OS réel)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from debrief_meet.platform.interfaces import DemarrageAuto

logger = logging.getLogger(__name__)

_CLE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Nom de valeur — doit être identique à celui nettoyé par le désinstalleur (docs/32 §4).
_NOM_VALEUR = "debriefMeet"


def _chemin_executable() -> Path | None:
    """`None` en dev (venv) : pas de sens de lancer un venv au boot."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable)


class DemarrageAutoWindows(DemarrageAuto):
    def est_active(self) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CLE_RUN) as cle:
                valeur, _ = winreg.QueryValueEx(cle, _NOM_VALEUR)
        except OSError:
            return False
        # Valeur orpheline (exécutable déplacé/supprimé depuis) = considérée inactive.
        return Path(valeur.strip('"')).exists()

    def activer(self) -> None:
        import winreg

        executable = _chemin_executable()
        if executable is None:
            logger.warning("Démarrage auto : exécution hors bundle (dev) — rien à activer")
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CLE_RUN, 0, winreg.KEY_SET_VALUE) as cle:
                winreg.SetValueEx(cle, _NOM_VALEUR, 0, winreg.REG_SZ, f'"{executable}"')
            logger.info("Démarrage auto activé → %s", executable)
        except OSError as exc:
            logger.warning("Démarrage auto : activation impossible (%s)", exc)
            raise

    def desactiver(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CLE_RUN, 0, winreg.KEY_SET_VALUE) as cle:
                winreg.DeleteValue(cle, _NOM_VALEUR)
            logger.info("Démarrage auto désactivé")
        except FileNotFoundError:
            logger.debug("Démarrage auto : déjà désactivé (rien à supprimer)")
        except OSError as exc:
            logger.warning("Démarrage auto : désactivation impossible (%s)", exc)
            raise
