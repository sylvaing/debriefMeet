"""Téléchargement + (re)chargement d'un modèle Whisper, avec retour visuel.

Mutualisé entre (1) les Préférences — changer de modèle à chaud (docs/15) — et (2) le
**premier lancement** — télécharger le modèle initial avec une barre de progression
plutôt qu'en silence (sinon la première transcription « gèle » le temps du download).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QEventLoop, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from debrief_meet.core.arret_threads import arreter_thread
from debrief_meet.core.config import Config
from debrief_meet.platform.interfaces import MoteurTranscription

logger = logging.getLogger(__name__)


class ChargeurModele(QObject):
    """Télécharge (si demandé) puis recharge le moteur **à chaud**, dans un QThread —
    pour qu'un changement/téléchargement de modèle n'opère jamais sur le thread GUI."""

    fini = Signal()
    echec = Signal(str)

    def __init__(self, moteur: MoteurTranscription, nom: str, telecharger: bool) -> None:
        super().__init__()
        self._moteur = moteur
        self._nom = nom
        self._telecharger = telecharger

    @Slot()
    def executer(self) -> None:
        try:
            if self._telecharger:
                self._moteur.telecharger_modele(self._nom)
            self._moteur.recharger_modele(self._nom)
            self.fini.emit()
        except Exception as exc:  # noqa: BLE001 — remonté à l'UI, jamais de crash
            self.echec.emit(str(exc))


def precharger_au_demarrage(moteur: MoteurTranscription, config: Config,
                            parent: QWidget | None = None) -> None:
    """Au démarrage : si le modèle configuré est **déjà en cache**, le précharge en
    silence (comme avant). Sinon, le télécharge **une seule fois** avec une fenêtre de
    progression (barre indéterminée) puis précharge les workers. Hors-ligne / échec :
    message clair, l'app démarre quand même (transcription indisponible jusqu'au DL).

    Le téléchargement tourne dans un QThread ; une boucle d'événements imbriquée garde
    l'UI réactive le temps du download. Toute la GUI reste sur le thread principal."""
    nom = config.get("modele")
    try:
        deja_en_cache = moteur.est_telecharge(nom)
    except Exception:  # noqa: BLE001 — la vérif ne doit jamais empêcher le démarrage
        deja_en_cache = False
    if deja_en_cache:
        moteur.charger_modele(nom)
        return

    dlg = QProgressDialog(
        "Téléchargement du modèle initial…\n(une seule fois — cela peut prendre une minute)",
        None, 0, 0, parent)                          # pas de bouton Annuler ; barre indéterminée
    dlg.setWindowTitle("debriefMeet — modèle")
    dlg.setMinimumDuration(0)
    dlg.setValue(0)

    thread = QThread()
    chargeur = ChargeurModele(moteur, nom, telecharger=True)
    chargeur.moveToThread(thread)
    erreur: list[str] = []
    loop = QEventLoop()
    thread.started.connect(chargeur.executer)
    chargeur.fini.connect(thread.quit)
    chargeur.echec.connect(erreur.append)            # simple append (sans GUI) : OK hors thread GUI
    chargeur.echec.connect(thread.quit)
    thread.finished.connect(loop.quit)

    dlg.show()
    thread.start()
    loop.exec()                                       # attend la fin du DL, UI réactive
    arreter_thread(thread, 2_000, garder=(chargeur,))
    dlg.close()

    if erreur:
        logger.warning("Téléchargement du modèle initial échoué : %s", erreur[0])
        QMessageBox.warning(
            parent, "Modèle non disponible",
            f"Le téléchargement du modèle a échoué :\n{erreur[0]}\n\n"
            "debriefMeet démarre quand même, mais la transcription sera indisponible tant "
            "que le modèle n'est pas téléchargé (réessayez via les Préférences).")
