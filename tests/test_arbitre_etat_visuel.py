"""Arbitre de l'état visuel de l'icône — jobs de l'Historique + orchestrateurs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from debrief_meet.core.modes import EtatVisuel
from debrief_meet.ui.arbitre_etat_visuel import ArbitreEtatVisuel


class FauxOrchestrateur(QObject):
    etat_visuel_change = Signal(object)


class FauxGestionnaireJobs(QObject):
    demarre = Signal(object)
    termine = Signal(object, object)
    echoue = Signal(object, str)


def _arbitre(qapp, delai_flash_ms: int = 0):
    orch = FauxOrchestrateur()
    jobs = FauxGestionnaireJobs()
    arbitre = ArbitreEtatVisuel(delai_flash_ms=delai_flash_ms)
    arbitre.suivre_orchestrateur(orch)
    arbitre.suivre_gestionnaire(jobs, "jobs")
    emis: list[EtatVisuel] = []
    arbitre.etat_change.connect(emis.append)
    return arbitre, orch, jobs, emis


MD = Path("/reunion/transcription.md")


def test_job_demarre_passe_en_orange(qapp):
    _, _, jobs, emis = _arbitre(qapp)
    jobs.demarre.emit(MD)
    assert emis == [EtatVisuel.TRANSCRIPTION]


def test_enregistrement_gagne_sur_le_job_puis_l_orange_revient(qapp):
    """Le rouge prime ; à l'arrêt de l'enregistrement, si le job tourne encore,
    l'icône revient à l'orange plutôt qu'au repos."""
    _, orch, jobs, emis = _arbitre(qapp)
    jobs.demarre.emit(MD)
    orch.etat_visuel_change.emit(EtatVisuel.ENREGISTREMENT)
    orch.etat_visuel_change.emit(EtatVisuel.REPOS)
    assert emis == [EtatVisuel.TRANSCRIPTION, EtatVisuel.ENREGISTREMENT,
                    EtatVisuel.TRANSCRIPTION]


def test_fin_de_job_flash_vert_puis_repos(qapp):
    _, _, jobs, emis = _arbitre(qapp)
    jobs.demarre.emit(MD)
    jobs.termine.emit(MD, MD)
    assert emis == [EtatVisuel.TRANSCRIPTION, EtatVisuel.TERMINE]
    qapp.processEvents()  # le singleShot(0) de fin de flash
    assert emis[-1] == EtatVisuel.REPOS


def test_echec_de_job_flash_gris(qapp):
    _, _, jobs, emis = _arbitre(qapp)
    jobs.demarre.emit(MD)
    jobs.echoue.emit(MD, "boum")
    assert emis == [EtatVisuel.TRANSCRIPTION, EtatVisuel.ERREUR]
    qapp.processEvents()
    assert emis[-1] == EtatVisuel.REPOS


def test_fin_de_flash_revient_a_l_orange_si_un_autre_job_tourne(qapp):
    arbitre = ArbitreEtatVisuel(delai_flash_ms=0)
    local = FauxGestionnaireJobs()
    mistral = FauxGestionnaireJobs()
    arbitre.suivre_gestionnaire(local, "local")
    arbitre.suivre_gestionnaire(mistral, "mistral")
    emis: list[EtatVisuel] = []
    arbitre.etat_change.connect(emis.append)
    local.demarre.emit(MD)
    mistral.demarre.emit(MD)
    local.termine.emit(MD, MD)
    assert emis == [EtatVisuel.TRANSCRIPTION, EtatVisuel.TERMINE]
    qapp.processEvents()
    assert emis[-1] == EtatVisuel.TRANSCRIPTION


def test_fin_de_job_pendant_l_enregistrement_reste_rouge(qapp):
    _, orch, jobs, emis = _arbitre(qapp)
    jobs.demarre.emit(MD)
    orch.etat_visuel_change.emit(EtatVisuel.ENREGISTREMENT)
    jobs.termine.emit(MD, MD)
    qapp.processEvents()
    assert emis[-1] == EtatVisuel.ENREGISTREMENT


def test_orchestrateur_seul_passe_tel_quel(qapp):
    """Sans job, l'arbitre est transparent pour les flux d'enregistrement."""
    _, orch, _, emis = _arbitre(qapp)
    for etat in (EtatVisuel.ENREGISTREMENT, EtatVisuel.TRANSCRIPTION,
                 EtatVisuel.TERMINE, EtatVisuel.REPOS):
        orch.etat_visuel_change.emit(etat)
    assert emis == [EtatVisuel.ENREGISTREMENT, EtatVisuel.TRANSCRIPTION,
                    EtatVisuel.TERMINE, EtatVisuel.REPOS]


def test_n_emet_que_sur_changement(qapp):
    _, orch, jobs, emis = _arbitre(qapp)
    jobs.demarre.emit(MD)
    orch.etat_visuel_change.emit(EtatVisuel.REPOS)  # déjà REPOS côté orchestrateur
    assert emis == [EtatVisuel.TRANSCRIPTION]
