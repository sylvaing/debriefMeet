"""Démarrage automatique Linux — `~/.config/autostart/` (docs/49 §5.3).

Spécification freedesktop « Desktop Application Autostart » : tout fichier `.desktop`
présent dans `$XDG_CONFIG_HOME/autostart/` est lancé à l'ouverture de session par
GNOME (comme par KDE/XFCE). Pas de registre, pas de service systemd : l'app est une
application de bureau avec une icône de tray, elle doit démarrer *avec la session
graphique* et non avec la machine — un `systemd --user` démarrerait aussi en session
console, sans serveur d'affichage.

`XDG_CONFIG_HOME` est respecté (et non `~/.config` en dur) : c'est ce que lit le
bureau, et ça rend la classe testable sans toucher au vrai dossier de l'utilisateur."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from debrief_meet.platform.interfaces import DemarrageAuto

logger = logging.getLogger(__name__)

# Nom du fichier — doit rester stable : c'est lui qu'on écrase/supprime, et il
# détermine l'unicité de l'entrée d'autostart.
_NOM_FICHIER = "debriefmeet.desktop"


def dossier_autostart() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "autostart"


def _chemin_executable() -> Path | None:
    """`None` en dev (venv) : pas de sens de lancer un venv à l'ouverture de session."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable)


def _contenu_desktop(executable: Path) -> str:
    # `X-GNOME-Autostart-enabled` : sans lui, l'entrée reste inerte quand
    # gnome-session a déjà mémorisé un état pour ce fichier.
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=debriefMeet\n"
        "Comment=Transcription vocale locale\n"
        f"Exec={executable}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


class DemarrageAutoLinux(DemarrageAuto):
    def __init__(self, dossier: Path | None = None) -> None:
        # Injectable pour les tests ; en production, résolu à chaque appel pour
        # suivre un éventuel changement de `XDG_CONFIG_HOME` en cours de session.
        self._dossier = dossier

    def _fichier(self) -> Path:
        return (self._dossier or dossier_autostart()) / _NOM_FICHIER

    def est_active(self) -> bool:
        fichier = self._fichier()
        if not fichier.exists():
            return False
        # Entrée orpheline (app déplacée/désinstallée depuis) = considérée inactive,
        # même règle que sur Windows pour une valeur de Registre pointant dans le vide.
        for ligne in fichier.read_text(encoding="utf-8").splitlines():
            if ligne.startswith("Exec="):
                return Path(ligne[len("Exec="):].strip()).exists()
        return False

    def activer(self) -> None:
        executable = _chemin_executable()
        if executable is None:
            logger.warning("Démarrage auto : exécution hors bundle (dev) — rien à activer")
            return
        fichier = self._fichier()
        try:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(_contenu_desktop(executable), encoding="utf-8")
            logger.info("Démarrage auto activé → %s (Exec=%s)", fichier, executable)
        except OSError as exc:
            logger.warning("Démarrage auto : activation impossible (%s)", exc)
            raise

    def desactiver(self) -> None:
        fichier = self._fichier()
        try:
            fichier.unlink()
            logger.info("Démarrage auto désactivé (%s supprimé)", fichier)
        except FileNotFoundError:
            logger.debug("Démarrage auto : déjà désactivé (rien à supprimer)")
        except OSError as exc:
            logger.warning("Démarrage auto : désactivation impossible (%s)", exc)
            raise
