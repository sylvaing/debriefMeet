from __future__ import annotations

import numpy as np
import pytest

from debrief_meet.core.config import Config
from debrief_meet.core.dictee import OrchestrateurDictee
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from tests.fakes.adapters import MicroFake, MoteurFake, PressePapiersFake


def _creer_orchestrateur(machine, micro=None, moteur=None, presse=None, config=None,
                          delai_termine_ms=100, delai_erreur_ms=100):
    micro = micro or MicroFake()
    moteur = moteur or MoteurFake()
    presse = presse or PressePapiersFake()
    config = config or Config()
    orch = OrchestrateurDictee(
        machine=machine,
        micro=micro,
        moteur=moteur,
        presse_papiers=presse,
        config=config,
        delai_termine_ms=delai_termine_ms,
        delai_erreur_ms=delai_erreur_ms,
    )
    return orch, micro, moteur, presse


def test_toggle_dictee_demarre_enregistrement(qapp):
    machine = MachineEtats()
    etats = []
    orch, micro, moteur, presse = _creer_orchestrateur(machine)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_dictee()

    assert micro.en_cours
    assert EtatVisuel.ENREGISTREMENT in etats


def test_toggle_stop_transcrit_et_copie(qapp, qtbot):
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(44100, dtype=np.float32))
    moteur = MoteurFake()
    presse = PressePapiersFake()
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, moteur=moteur, presse=presse, delai_termine_ms=100)

    machine.toggle_dictee()
    machine.toggle_dictee()

    qtbot.waitUntil(lambda: len(presse.historique) > 0, timeout=5000)
    assert presse.historique[-1] == "transcription de test"


def test_etats_visuels_flux_complet(qapp, qtbot):
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(44100, dtype=np.float32))
    etats = []
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, delai_termine_ms=100)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_dictee()
    machine.toggle_dictee()

    qtbot.waitUntil(lambda: EtatVisuel.TERMINE in etats, timeout=5000)

    assert EtatVisuel.ENREGISTREMENT in etats
    assert EtatVisuel.TRANSCRIPTION in etats
    assert EtatVisuel.TERMINE in etats


def test_audio_vide_emet_rien_entendu(qapp, qtbot):
    """`recuperer_echantillons()` vide → signal `rien_entendu`, aucune transcription
    lancée, ERREUR (pas REPOS direct) puis retour REPOS après le délai."""
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.zeros(0, dtype=np.float32))
    moteur = MoteurFake()
    presse = PressePapiersFake()
    etats = []
    messages = []
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, moteur=moteur, presse=presse,
                                          delai_erreur_ms=50)
    orch.etat_visuel_change.connect(etats.append)
    orch.rien_entendu.connect(messages.append)

    machine.toggle_dictee()
    machine.toggle_dictee()

    assert len(moteur.appels_transcrire) == 0
    assert len(presse.historique) == 0
    assert messages == ["Aucun son capté — vérifiez le micro."]
    assert EtatVisuel.ERREUR in etats
    qtbot.waitUntil(lambda: EtatVisuel.REPOS in etats, timeout=5000)


def test_erreur_transcription_emet_erreur(qapp, qtbot):
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(44100, dtype=np.float32))
    moteur = MoteurFake()
    moteur.lever_erreur = RuntimeError("crash")
    presse = PressePapiersFake()
    etats = []
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, moteur=moteur, presse=presse, delai_erreur_ms=100)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_dictee()
    machine.toggle_dictee()

    qtbot.waitUntil(lambda: EtatVisuel.ERREUR in etats, timeout=5000)
    assert len(presse.historique) == 0


def test_terminer_sans_thread_ne_leve_pas(qapp):
    machine = MachineEtats()
    orch, *_ = _creer_orchestrateur(machine)
    # Aucune dictée lancée : terminer() est un no-op sûr.
    orch.terminer()


def test_terminer_attend_le_thread_de_transcription(qapp, qtbot):
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(44100, dtype=np.float32))
    moteur = MoteurFake()
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, moteur=moteur, delai_termine_ms=100)

    machine.toggle_dictee()
    machine.toggle_dictee()  # lance le QThread de transcription

    orch.terminer()

    assert not (orch._thread and orch._thread.isRunning())


# ── Feedback « rien entendu » (docs/27 correctif 2) ─────────────────────────────

def test_transcription_vide_emet_rien_entendu_et_erreur(qapp, qtbot):
    """Transcription vide → rien copié, signal `rien_entendu` émis, ERREUR (pas TERMINE)."""
    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(44100, dtype=np.float32))
    moteur = MoteurFake()
    moteur.resultat_fixe.texte = "   "
    presse = PressePapiersFake()
    etats = []
    messages = []
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, moteur=moteur, presse=presse,
                                          delai_erreur_ms=50)
    orch.etat_visuel_change.connect(etats.append)
    orch.rien_entendu.connect(messages.append)

    machine.toggle_dictee()
    machine.toggle_dictee()

    qtbot.waitUntil(lambda: EtatVisuel.ERREUR in etats, timeout=5000)
    assert EtatVisuel.TERMINE not in etats
    assert len(presse.historique) == 0
    assert messages == ["Aucune parole détectée — rien n'a été copié."]


# ── Micro configuré + échec de démarrage géré (docs/27 correctif 4) ─────────────

def test_demarrer_passe_le_micro_index_configure(qapp):
    machine = MachineEtats()
    micro = MicroFake()
    config = Config()
    config.set("micro_index", 3)
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, config=config)

    machine.toggle_dictee()

    assert micro.index_utilise == 3


def test_micro_indisponible_au_demarrage_annule_la_dictee(qapp, qtbot):
    machine = MachineEtats()
    micro = MicroFake(lever_au_demarrage=RuntimeError("périphérique absent"))
    etats = []
    messages = []
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, delai_erreur_ms=50)
    orch.etat_visuel_change.connect(etats.append)
    orch.rien_entendu.connect(messages.append)

    machine.toggle_dictee()

    assert messages == ["Micro indisponible — dictée annulée."]
    assert EtatVisuel.ERREUR in etats
    assert orch._enregistrement_actif is False
    qtbot.waitUntil(lambda: machine.mode == Mode.IDLE, timeout=5000)


# ── Câblage arreter_thread() (docs/26) ────────────────────────────────────────

class _MoteurLent(MoteurFake):
    """Transcription volontairement lente — garde le QThread « en vol » le temps de
    vérifier l'appel à `terminer()` sans course avec l'assertion."""

    def transcrire(self, audio, langue=None):
        import time
        time.sleep(0.4)
        return super().transcrire(audio, langue)


def test_terminer_appelle_arreter_thread_avec_deblocage_moteur(qapp, monkeypatch):
    import debrief_meet.core.dictee as dictee_module

    machine = MachineEtats()
    micro = MicroFake(echantillons=np.ones(44100, dtype=np.float32))
    moteur = _MoteurLent()
    orch, _, _, _ = _creer_orchestrateur(machine, micro=micro, moteur=moteur, delai_termine_ms=100)

    reel = dictee_module.arreter_thread
    appels = []

    def _espion(thread, timeout_ms, debloquer=None, timeout_deblocage_ms=5_000, garder=()):
        appels.append((thread, timeout_ms, debloquer, garder))
        return reel(thread, timeout_ms, debloquer=debloquer,
                    timeout_deblocage_ms=timeout_deblocage_ms, garder=garder)

    monkeypatch.setattr(dictee_module, "arreter_thread", _espion)

    machine.toggle_dictee()
    machine.toggle_dictee()  # lance le QThread de transcription (moteur lent → en cours)
    assert orch._thread is not None and orch._thread.isRunning()

    orch.terminer()

    assert len(appels) == 1
    _, timeout_ms, debloquer, garder = appels[0]
    assert timeout_ms == 10_000
    assert debloquer == moteur.terminer
    assert garder == (orch._worker,)
