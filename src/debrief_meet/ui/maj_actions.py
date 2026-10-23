"""Câblage UI de la mise à jour automatique (docs/53 §3) — badge de la toolbar,
notification tray, dialogues, et le clic qui lance la procédure de l'OS.

Sorti de `__main__` pour être testable : `gerer_clic_maj` rend l'issue du clic.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from debrief_meet.core import mise_a_jour
from debrief_meet.ui import dialogues

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

    from debrief_meet.core.verificateur_maj import VerificateurMaj
    from debrief_meet.ui.fenetre_principale import FenetrePrincipale
    from debrief_meet.ui.tray import IconeTray

logger = logging.getLogger(__name__)

URL_RELEASES = f"https://github.com/{mise_a_jour.DEPOT}/releases/latest"


def ouvrir_page_release(verificateur: "VerificateurMaj") -> None:
    QDesktopServices.openUrl(QUrl(verificateur.notes_url() or URL_RELEASES))


def gerer_clic_maj(fenetre: "FenetrePrincipale", verificateur: "VerificateurMaj") -> str:
    """Clic sur le badge « Mise à jour X disponible ». Rend l'issue :
    `"aucune"` (badge périmé, retiré), `"occupe"` (enregistrement ou traitement en
    cours — on ne ferme jamais l'app sous un travail), `"manuel"` (Linux, sources,
    dossier non inscriptible : page de release ouverte dans le navigateur),
    `"annule"` (refus du dialogue), `"en_cours"`, ou `"lance"` / `"verification"`
    (téléchargement parti, le badge affiche la progression)."""
    version = verificateur.version_disponible()
    if not version:
        fenetre.definir_maj_disponible(None)
        return "aucune"
    if verificateur.est_occupe():
        dialogues.avertir(
            fenetre, titre="Mise à jour reportée",
            description="Un enregistrement ou un traitement est en cours. "
                        "Relancez l'installation une fois terminé.",
            icone="warning-circle")
        return "occupe"
    if not mise_a_jour.installation_possible():
        ouvrir_page_release(verificateur)
        return "manuel"
    if verificateur.en_cours():
        return "en_cours"
    confirme = dialogues.confirmer(
        fenetre, titre=f"Installer la version {version} ?",
        description="debriefMeet va télécharger la mise à jour, se fermer puis redémarrer "
                    "avec la nouvelle version. Les réunions et la configuration sont conservées.",
        label_action="Installer et redémarrer", icone="arrow-circle-up",
        intention=dialogues.Intention.ACCENT)
    if not confirme:
        return "annule"
    issue = verificateur.telecharger_et_installer()
    if issue in ("lance", "verification"):
        fenetre.definir_maj_progression(0)
    elif issue == "manuel":
        ouvrir_page_release(verificateur)
    elif issue == "occupe":
        dialogues.avertir(fenetre, titre="Mise à jour reportée",
                          description="Un enregistrement ou un traitement vient de démarrer.",
                          icone="warning-circle")
    return issue


def brancher(fenetre: "FenetrePrincipale", tray: "IconeTray", verificateur: "VerificateurMaj",
             app: "QApplication") -> None:
    """Connexions entre le vérificateur et l'UI (appelé une fois par `__main__`)."""
    verificateur.maj_disponible.connect(lambda version, _url: fenetre.definir_maj_disponible(version))
    verificateur.maj_disponible.connect(tray.notifier_maj_disponible)
    verificateur.verification_terminee.connect(
        lambda version: fenetre.definir_maj_disponible(version or None))
    verificateur.telechargement_progresse.connect(fenetre.definir_maj_progression)
    # Téléchargement vérifié : `mise_a_jour.demander()` est posé, on ferme — l'installeur
    # est lancé APRÈS le retour de `app.exec()` (cf. `__main__`).
    verificateur.telechargement_termine.connect(lambda _chemin: app.quit())

    def _sur_echec(message: str) -> None:
        fenetre.definir_maj_disponible(verificateur.version_disponible() or None)
        dialogues.avertir(fenetre, titre="Mise à jour impossible",
                          description=f"{message}\n\nVous pouvez réessayer plus tard ou "
                                      "télécharger la nouvelle version depuis la page des releases.")

    verificateur.telechargement_echoue.connect(_sur_echec)
    fenetre.maj_cliquee.connect(lambda: gerer_clic_maj(fenetre, verificateur))
    # Badge dès le lancement si une version a été vue lors d'une session précédente
    # (mémoire en config, même hors ligne).
    fenetre.definir_maj_disponible(verificateur.version_disponible() or None)
