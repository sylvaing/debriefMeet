"""Export « en un clic » des logs + du contexte machine (docs/31 §3.6, docs/44).

Un seul chemin de code pour les deux points d'entrée — l'item du menu tray et le
bouton de Préférences › Journalisation. Le tray doit continuer à fonctionner même
fenêtre principale cassée : c'est pourquoi les deux appellent ce helper plutôt que
l'un de déléguer à l'autre.

Contrainte docs/31 §3.6 : « doit marcher même quand tout le reste est cassé » — aucune
dépendance au moteur de transcription, erreurs **affichées** plutôt que loguées
silencieusement. Le zip ne contient jamais de texte transcrit (règle §3.7.1) : logs
rotés, log de crash, `infos_systeme.json` et `config.json`.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QWidget

from debrief_meet.core.diagnostic import dossier_diagnostic_par_defaut, exporter_diagnostic
from debrief_meet.ui import dialogues

logger = logging.getLogger(__name__)


def reveler(chemin: Path) -> None:
    """Ouvre l'explorateur de fichiers sur `chemin` (sélectionné si possible)."""
    if not chemin.exists():
        return
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(chemin)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(chemin)])
    else:
        subprocess.Popen(["xdg-open", str(chemin.parent)])


def exporter_et_informer(parent: QWidget | None) -> Path | None:
    """Écrit le zip sur le Bureau, propose de le révéler. None en cas d'échec.

    Pas de sélecteur de dossier : pour un utilisateur non technique c'est une étape de
    plus et une chance de perdre le fichier — le Bureau est l'endroit le plus
    découvrable, et le dialogue de confirmation propose de l'y montrer.
    """
    try:
        from debrief_meet.platform.infos_systeme import collecter_infos_systeme

        chemin = exporter_diagnostic(dossier_diagnostic_par_defaut(), collecter_infos_systeme())
    except Exception as exc:  # noqa: BLE001 — affiché à l'utilisateur, jamais de crash
        logger.error("Export des logs impossible (%s)", exc, exc_info=True)
        dialogues.avertir(parent, titre="Erreur",
                          description=f"Impossible d'exporter les logs :\n{exc}")
        return None

    # Gabarit construit à la main plutôt que `dialogues.confirmer` : celui-ci code en
    # dur « Annuler », libellé absurde pour une action déjà réussie.
    dlg = dialogues.DialogueGabarit(
        parent, titre="Logs exportés",
        description=f"Archive déposée sur le Bureau : {chemin.name}\n"
                    "Envoyez ce fichier à Sylvain.",
        icone="file-zip", intention=dialogues.Intention.ACCENT)
    dlg.bouton_annuler().setText("Fermer")
    dlg.definir_action("Révéler dans le dossier")
    if dlg.exec() == dialogues.QDialog.DialogCode.Accepted:
        reveler(chemin)
    return chemin
