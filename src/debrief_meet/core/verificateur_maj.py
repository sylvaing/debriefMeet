"""Vérificateur de mise à jour — gestionnaire persistant côté Qt (docs/53 §2).

Modèle : `core/bluemind/sync.py::SynchroCalendrier` (un worker QThread sans parent
protégé par `proteger_thread`, un verrou, `terminer()` → `arreter_thread`, INFO au
succès / WARNING à l'échec, jamais de popup) et `core/planificateur_reunions.py`
(QTimer porté par l'objet, `tick()` public et déterministe dans les tests).

Quand vérifie-t-on : 30 s après le démarrage, puis toutes les 24 h tant que l'app
tourne — elle vit dans le tray et n'est presque jamais relancée, le timer est donc le
chemin principal — et à la demande (« Vérifier maintenant »). Le tick relit la config
à chaque passage (`Config` n'a pas de signal) : l'opt-out prend effet au tick suivant.

Le résultat est mémorisé dans la config (`maj_version_disponible`, `maj_notes_url`) :
le badge est posé dès le lancement suivant, même hors ligne, et `maj_disponible` n'est
émis qu'**une fois par version** — pas de notification quotidienne pour la même
version (le badge, lui, reste).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from debrief_meet.core import mise_a_jour
from debrief_meet.core.arret_threads import arreter_thread, proteger_thread
from debrief_meet.core.mise_a_jour import ClientMaj, ErreurMaj, Manifeste

if TYPE_CHECKING:
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)

DELAI_PREMIERE_VERIF_MS = 30_000
INTERVALLE_TICK_MS = 60 * 60_000
INTERVALLE_VERIF = timedelta(hours=24)


def _maintenant_utc() -> datetime:
    return datetime.now(timezone.utc)


class _WorkerVerification(QObject):
    terminee = Signal(object)   # Manifeste | None
    erreur = Signal(str)

    @Slot()
    def executer(self) -> None:
        try:
            with ClientMaj() as client:
                self.terminee.emit(client.recuperer_manifeste())
        except ErreurMaj as exc:
            self.erreur.emit(str(exc))
        except Exception as exc:  # jamais une exception non rattrapée dans un QThread
            logger.exception("Vérification de mise à jour : erreur inattendue")
            self.erreur.emit(str(exc))


class _WorkerTelechargement(QObject):
    progression = Signal(int)
    terminee = Signal(object)   # Path
    erreur = Signal(str)

    def __init__(self, fichier: mise_a_jour.Fichier, dossier: Path) -> None:
        super().__init__()
        self._fichier = fichier
        self._dossier = dossier

    @Slot()
    def executer(self) -> None:
        try:
            with ClientMaj() as client:
                chemin = client.telecharger(self._fichier, self._dossier, self.progression.emit)
            self.terminee.emit(chemin)
        except ErreurMaj as exc:
            self.erreur.emit(str(exc))
        except Exception as exc:
            logger.exception("Téléchargement de mise à jour : erreur inattendue")
            self.erreur.emit(str(exc))


class VerificateurMaj(QObject):
    maj_disponible = Signal(str, str)          # version, notes_url — une fois par version
    verification_terminee = Signal(object)     # str (version disponible) | None (à jour)
    verification_echouee = Signal(str)
    telechargement_progresse = Signal(int)
    telechargement_termine = Signal(object)    # Path — `mise_a_jour.demander()` déjà posé
    telechargement_echoue = Signal(str)

    def __init__(self, config: "Config", est_occupe: Callable[[], bool] | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._est_occupe = est_occupe or (lambda: False)
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVALLE_TICK_MS)
        self._timer.timeout.connect(self.tick)
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self._en_cours = False
        self._manifeste: Manifeste | None = None
        self._installer_apres_verification = False

    # ── Cycle de vie ─────────────────────────────────────────────────────────

    def demarrer(self) -> None:
        QTimer.singleShot(DELAI_PREMIERE_VERIF_MS, self.tick)
        self._timer.start()

    def arreter(self) -> None:
        self._timer.stop()

    def terminer(self) -> None:
        self.arreter()
        if self._thread is not None and self._thread.isRunning():
            arreter_thread(self._thread, 5_000, garder=(self._worker,))

    # ── État ─────────────────────────────────────────────────────────────────

    def en_cours(self) -> bool:
        return self._en_cours

    def est_occupe(self) -> bool:
        """Enregistrement ou job en cours (fourni par `__main__`) — on ne ferme
        jamais l'app sous un travail."""
        return bool(self._est_occupe())

    def manifeste(self) -> Manifeste | None:
        return self._manifeste

    def version_disponible(self) -> str:
        """Version mémorisée en config si elle est encore plus récente que l'app ;
        sinon (on vient d'être mis à jour) la mémoire est effacée et "" rendu."""
        version = str(self._config.get("maj_version_disponible") or "")
        if version and not mise_a_jour.est_plus_recente(version):
            self._memoriser_disponible("", "")
            return ""
        return version

    def notes_url(self) -> str:
        if self._manifeste is not None:
            return self._manifeste.notes_url
        return str(self._config.get("maj_notes_url") or "")

    # ── Vérification ─────────────────────────────────────────────────────────

    def tick(self, maintenant: datetime | None = None) -> bool:
        """Un passage du timer : vérifie si l'opt-out n'est pas posé et si la dernière
        vérification date de plus de 24 h. Rend True si une vérification part."""
        if not self._config.get("maj_verifier_auto"):
            return False
        maintenant = maintenant or _maintenant_utc()
        derniere = self._derniere_verification()
        if derniere is not None and maintenant - derniere < INTERVALLE_VERIF:
            return False
        return self.verifier()

    def verifier(self) -> bool:
        """Lance la vérification en fond (une seule à la fois). Rend False si une
        opération est déjà en cours."""
        if self._en_cours:
            return False
        worker = _WorkerVerification()
        worker.terminee.connect(self._sur_verification_terminee)
        worker.erreur.connect(self._sur_verification_echouee)
        self._lancer(worker)
        return True

    def _derniere_verification(self) -> datetime | None:
        brut = str(self._config.get("maj_derniere_verification") or "")
        if not brut:
            return None
        try:
            d = datetime.fromisoformat(brut)
        except ValueError:
            return None
        return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)

    @Slot(object)
    def _sur_verification_terminee(self, manifeste: object) -> None:
        self._en_cours = False
        self._config.set("maj_derniere_verification", _maintenant_utc().isoformat(timespec="seconds"))
        version_dispo = ""
        notes_url = ""
        if isinstance(manifeste, Manifeste) and mise_a_jour.est_plus_recente(manifeste.version):
            self._manifeste = manifeste
            version_dispo, notes_url = manifeste.version, manifeste.notes_url
        else:
            self._manifeste = None
        deja_connue = str(self._config.get("maj_version_disponible") or "")
        self._memoriser_disponible(version_dispo, notes_url)
        if version_dispo:
            # INFO et non DEBUG : sans cette ligne, un diagnostic ne peut que constater
            # l'absence d'échec, jamais affirmer que la vérification fonctionne.
            logger.info("Mise à jour disponible : %s (app %s)", version_dispo, mise_a_jour.__version__)
            if version_dispo != deja_connue:
                self.maj_disponible.emit(version_dispo, notes_url)
        else:
            logger.info("Vérification de mise à jour : à jour (%s)", mise_a_jour.__version__)
        self.verification_terminee.emit(version_dispo or None)
        if self._installer_apres_verification:
            self._installer_apres_verification = False
            if version_dispo:
                self.telecharger_et_installer()
            else:
                self.telechargement_echoue.emit("Aucune mise à jour disponible.")

    @Slot(str)
    def _sur_verification_echouee(self, message: str) -> None:
        self._en_cours = False
        self._installer_apres_verification = False
        # WARNING : une vérification qui échoue est invisible de l'utilisateur
        # (aucune popup, docs/53) — le log est le seul endroit où elle se voit.
        logger.warning("Vérification de mise à jour échouée : %s", message)
        self.verification_echouee.emit(message)

    def _memoriser_disponible(self, version: str, notes_url: str) -> None:
        if (self._config.get("maj_version_disponible") or "") == version \
                and (self._config.get("maj_notes_url") or "") == notes_url:
            self._config.sauvegarder()
            return
        self._config.set("maj_version_disponible", version)
        self._config.set("maj_notes_url", notes_url)
        self._config.sauvegarder()

    # ── Téléchargement + installation ────────────────────────────────────────

    def telecharger_et_installer(self) -> str:
        """Rend l'issue immédiate : `"occupe"` (enregistrement ou job en cours —
        on ne ferme jamais l'app sous un travail), `"manuel"` (Linux, sources, ou
        dossier non inscriptible sur macOS : l'UI ouvre la page de release),
        `"aucune"` (rien à installer), `"en_cours"`, `"verification"` (manifeste pas
        encore chargé — ex. badge posé depuis la config au lancement — la
        vérification part et le téléchargement enchaîne), ou `"lance"`."""
        if self._est_occupe():
            return "occupe"
        if not mise_a_jour.installation_possible():
            return "manuel"
        if self._en_cours:
            return "en_cours"
        if self._manifeste is None:
            if not self.version_disponible():
                return "aucune"
            self._installer_apres_verification = True
            self.verifier()
            return "verification"
        fichier = self._manifeste.fichier_pour()
        if fichier is None:
            return "manuel"
        worker = _WorkerTelechargement(fichier, mise_a_jour.dossier_telechargements())
        worker.progression.connect(self.telechargement_progresse)
        worker.terminee.connect(self._sur_telechargement_termine)
        worker.erreur.connect(self._sur_telechargement_echoue)
        self._lancer(worker)
        logger.info("Téléchargement de la mise à jour %s : %s", self._manifeste.version, fichier.url)
        return "lance"

    @Slot(object)
    def _sur_telechargement_termine(self, chemin: object) -> None:
        self._en_cours = False
        chemin = Path(str(chemin))
        mise_a_jour.purger(sauf=chemin)
        mise_a_jour.demander(chemin)
        self.telechargement_termine.emit(chemin)

    @Slot(str)
    def _sur_telechargement_echoue(self, message: str) -> None:
        self._en_cours = False
        logger.warning("Téléchargement de mise à jour échoué : %s", message)
        self.telechargement_echoue.emit(message)

    # ── Thread ───────────────────────────────────────────────────────────────

    def _lancer(self, worker: QObject) -> None:
        thread = QThread()
        worker.moveToThread(thread)
        proteger_thread(thread, worker)
        thread.started.connect(worker.executer)
        for fin in ("terminee", "erreur"):
            getattr(worker, fin).connect(thread.quit)
        self._thread = thread
        self._worker = worker
        self._en_cours = True
        thread.start()
