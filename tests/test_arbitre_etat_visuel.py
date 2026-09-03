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


# ── Toutes les paires de fin d'un gestionnaire doivent éteindre le job ──────────

class FauxGestionnaireDeuxTaches(QObject):
    """Gestionnaire annonçant ses fins sur DEUX paires (comme GestionnaireCRMistral :
    CR d'un côté, transcription distante de l'autre)."""

    demarre = Signal(object)
    termine = Signal(object, object)
    echoue = Signal(object, str)
    transcription_terminee = Signal(object, object)
    transcription_echouee = Signal(object, str)


def test_seconde_paire_de_fin_eteint_bien_le_job(qapp):
    """Sans le câblage de cette paire, `demarre` allumait l'orange et RIEN ne
    l'éteignait : icône bloquée jusqu'à la fin de la session, sans erreur visible."""
    g = FauxGestionnaireDeuxTaches()
    arbitre = ArbitreEtatVisuel(delai_flash_ms=0)
    arbitre.suivre_gestionnaire(g, "mistral")
    emis: list[EtatVisuel] = []
    arbitre.etat_change.connect(emis.append)

    g.demarre.emit(MD)
    assert emis[-1] == EtatVisuel.TRANSCRIPTION
    g.transcription_terminee.emit(MD, MD)
    assert emis[-1] != EtatVisuel.TRANSCRIPTION      # le job est bien éteint


def test_seconde_paire_dechec_eteint_aussi_le_job(qapp):
    g = FauxGestionnaireDeuxTaches()
    arbitre = ArbitreEtatVisuel(delai_flash_ms=0)
    arbitre.suivre_gestionnaire(g, "mistral")
    emis: list[EtatVisuel] = []
    arbitre.etat_change.connect(emis.append)

    g.demarre.emit(MD)
    g.transcription_echouee.emit(MD, "boum")
    assert emis[-1] != EtatVisuel.TRANSCRIPTION


def test_toutes_les_fins_des_vrais_gestionnaires_sont_dans_paires_fin():
    """Garde-fou de la famille de bug ci-dessus, sur les VRAIES classes.

    Ajouter une tâche à un gestionnaire, c'est ajouter une paire de signaux de fin —
    et oublier de la déclarer dans `PAIRES_FIN` ne casse rien de visible : le job
    s'allume et ne s'éteint jamais. Ce test refuse tout signal de fin non couvert."""
    from PySide6.QtCore import Signal as _Signal

    from debrief_meet.ui.arbitre_etat_visuel import PAIRES_FIN
    from debrief_meet.ui.generateur_cr_mistral import GestionnaireCRMistral
    from debrief_meet.ui.gestionnaire_diarization import GestionnaireDiarization

    couverts = {nom for paire in PAIRES_FIN for nom in paire}
    for classe in (GestionnaireCRMistral, GestionnaireDiarization):
        fins = {
            nom for nom in dir(classe)
            if isinstance(getattr(classe, nom, None), type(_Signal()))
            and (nom.startswith("termine") or nom.startswith("echou")
                 or nom.endswith("_terminee") or nom.endswith("_echouee"))
        }
        manquants = fins - couverts
        assert not manquants, (
            f"{classe.__name__} : signal(aux) de fin non déclaré(s) dans "
            f"arbitre_etat_visuel.PAIRES_FIN : {sorted(manquants)} — le job resterait "
            "allumé (icône orange bloquée) après cette tâche.")
