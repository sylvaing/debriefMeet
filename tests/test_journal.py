"""Tests unitaires — OrchestrateurJournal + EcrivainJournal."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import EcrivainJournal
from debrief_meet.core.journal import OrchestrateurJournal
from debrief_meet.core.modes import EtatVisuel, MachineEtats, Mode
from tests.fakes.adapters import MicroFake, MoteurFake


# ── EcrivainJournal ──────────────────────────────────────────────────────────

def test_cree_fichier_du_jour(tmp_path):
    e = EcrivainJournal(tmp_path)
    ts = datetime(2026, 5, 5, 9, 15)
    chemin = e.ajouter_entree("Mon texte.", ts)
    assert chemin == tmp_path / "2026-05-05.md"
    assert chemin.exists()


def test_entete_premiere_entree(tmp_path):
    e = EcrivainJournal(tmp_path)
    ts = datetime(2026, 5, 5, 9, 15)
    chemin = e.ajouter_entree("Texte de test.", ts)
    contenu = chemin.read_text(encoding="utf-8")
    assert contenu.startswith("# Activités — 2026-05-05\n\n")


def test_format_section(tmp_path):
    e = EcrivainJournal(tmp_path)
    ts = datetime(2026, 5, 5, 9, 15)
    chemin = e.ajouter_entree("Revue du ticket #42.", ts)
    contenu = chemin.read_text(encoding="utf-8")
    assert "## 09:15\n\nRevue du ticket #42.\n\n---\n\n" in contenu


def test_append_plusieurs_entrees(tmp_path):
    e = EcrivainJournal(tmp_path)
    e.ajouter_entree("Première entrée.", datetime(2026, 5, 5, 9, 0))
    e.ajouter_entree("Deuxième entrée.", datetime(2026, 5, 5, 11, 30))
    chemin = tmp_path / "2026-05-05.md"
    contenu = chemin.read_text(encoding="utf-8")
    # Un seul en-tête
    assert contenu.count("# Activités") == 1
    assert "## 09:00" in contenu
    assert "## 11:30" in contenu
    assert "Première entrée." in contenu
    assert "Deuxième entrée." in contenu


def test_entrees_jours_differents(tmp_path):
    e = EcrivainJournal(tmp_path)
    e.ajouter_entree("Hier.", datetime(2026, 5, 4, 10, 0))
    e.ajouter_entree("Aujourd'hui.", datetime(2026, 5, 5, 10, 0))
    assert (tmp_path / "2026-05-04.md").exists()
    assert (tmp_path / "2026-05-05.md").exists()


def test_cree_dossier_si_absent(tmp_path):
    dossier = tmp_path / "sous" / "dossier"
    e = EcrivainJournal(dossier)
    e.ajouter_entree("Test.", datetime(2026, 5, 5, 9, 0))
    assert dossier.exists()


# ── OrchestrateurJournal ─────────────────────────────────────────────────────

def test_demarrage_sur_mode_journal(qtbot, tmp_path):
    machine = MachineEtats()
    micro = MicroFake()
    moteur = MoteurFake()
    etats = []
    orch = OrchestrateurJournal(machine, micro, moteur, tmp_path, config=Config(), delai_termine_ms=50)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_journal()
    assert micro.en_cours
    assert EtatVisuel.ENREGISTREMENT in etats


def test_transcription_ecrit_fichier(qtbot, tmp_path):
    import numpy as np
    machine = MachineEtats()
    micro = MicroFake(np.ones(16000, dtype=np.float32))
    moteur = MoteurFake()
    moteur.resultat_fixe.texte = "Réunion de synchronisation."
    orch = OrchestrateurJournal(machine, micro, moteur, tmp_path, config=Config(), delai_termine_ms=50)

    machine.toggle_journal()
    machine.toggle_journal()

    # Attendre la fin du thread de transcription
    qtbot.waitUntil(
        lambda: any(tmp_path.glob("*.md")),
        timeout=5000,
    )
    contenu = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "Réunion de synchronisation." in contenu


def test_audio_vide_emet_rien_entendu(qtbot, tmp_path):
    """`recuperer_echantillons()` vide → signal `rien_entendu`, aucune transcription
    lancée, ERREUR (pas REPOS direct) puis retour REPOS après le délai."""
    import numpy as np
    machine = MachineEtats()
    micro = MicroFake(np.zeros(0, dtype=np.float32))
    moteur = MoteurFake()
    etats = []
    messages = []
    orch = OrchestrateurJournal(machine, micro, moteur, tmp_path, config=Config(), delai_erreur_ms=50)
    orch.etat_visuel_change.connect(etats.append)
    orch.rien_entendu.connect(messages.append)

    machine.toggle_journal()
    machine.toggle_journal()

    assert not list(tmp_path.glob("*.md"))
    assert messages == ["Aucun son capté — vérifiez le micro."]
    assert EtatVisuel.ERREUR in etats
    qtbot.waitUntil(lambda: EtatVisuel.REPOS in etats, timeout=5000)


def test_erreur_moteur_emet_erreur(qtbot, tmp_path):
    import numpy as np
    machine = MachineEtats()
    micro = MicroFake(np.ones(16000, dtype=np.float32))
    moteur = MoteurFake()
    moteur.lever_erreur = RuntimeError("GPU absent")
    etats = []
    orch = OrchestrateurJournal(machine, micro, moteur, tmp_path, config=Config(), delai_erreur_ms=50)
    orch.etat_visuel_change.connect(etats.append)

    machine.toggle_journal()
    machine.toggle_journal()

    qtbot.waitUntil(lambda: EtatVisuel.ERREUR in etats, timeout=5000)


def test_terminer_sans_thread_ne_leve_pas(qtbot, tmp_path):
    machine = MachineEtats()
    orch = OrchestrateurJournal(machine, MicroFake(), MoteurFake(), tmp_path, config=Config())
    # Aucun journal lancé : terminer() est un no-op sûr.
    orch.terminer()


def test_terminer_attend_le_thread_de_transcription(qtbot, tmp_path):
    import numpy as np
    machine = MachineEtats()
    micro = MicroFake(np.ones(16000, dtype=np.float32))
    moteur = MoteurFake()
    orch = OrchestrateurJournal(machine, micro, moteur, tmp_path, config=Config(), delai_termine_ms=100)

    machine.toggle_journal()
    machine.toggle_journal()  # lance le QThread de transcription

    orch.terminer()

    assert not (orch._thread and orch._thread.isRunning())


# ── Feedback « rien entendu » (docs/27 correctif 2) ─────────────────────────────

def test_transcription_vide_emet_rien_entendu_et_erreur(qtbot, tmp_path):
    """Transcription vide → rien écrit, signal `rien_entendu` émis, ERREUR (pas TERMINE)."""
    import numpy as np
    machine = MachineEtats()
    micro = MicroFake(np.ones(16000, dtype=np.float32))
    moteur = MoteurFake()
    moteur.resultat_fixe.texte = "   "
    etats = []
    messages = []
    orch = OrchestrateurJournal(machine, micro, moteur, tmp_path, config=Config(), delai_erreur_ms=50)
    orch.etat_visuel_change.connect(etats.append)
    orch.rien_entendu.connect(messages.append)

    machine.toggle_journal()
    machine.toggle_journal()

    qtbot.waitUntil(lambda: EtatVisuel.ERREUR in etats, timeout=5000)
    assert EtatVisuel.TERMINE not in etats
    assert not list(tmp_path.glob("*.md"))
    assert messages == ["Aucune parole détectée — rien n'a été écrit dans le journal."]


# ── Micro configuré + échec de démarrage géré (docs/27 correctif 4) ─────────────

def test_demarrer_passe_le_micro_index_configure(qtbot, tmp_path):
    machine = MachineEtats()
    micro = MicroFake()
    config = Config()
    config.set("micro_index", 3)
    orch = OrchestrateurJournal(machine, micro, MoteurFake(), tmp_path, config=config)

    machine.toggle_journal()

    assert micro.index_utilise == 3


def test_micro_indisponible_au_demarrage_annule_le_journal(qtbot, tmp_path):
    machine = MachineEtats()
    micro = MicroFake(lever_au_demarrage=RuntimeError("périphérique absent"))
    etats = []
    messages = []
    orch = OrchestrateurJournal(machine, micro, MoteurFake(), tmp_path, config=Config(),
                                delai_erreur_ms=50)
    orch.etat_visuel_change.connect(etats.append)
    orch.rien_entendu.connect(messages.append)

    machine.toggle_journal()

    assert messages == ["Micro indisponible — journal annulé."]
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


def test_terminer_appelle_arreter_thread_avec_deblocage_moteur(qtbot, monkeypatch, tmp_path):
    import numpy as np

    import debrief_meet.core.journal as journal_module

    machine = MachineEtats()
    micro = MicroFake(np.ones(16000, dtype=np.float32))
    moteur = _MoteurLent()
    orch = OrchestrateurJournal(machine, micro, moteur, tmp_path, config=Config(), delai_termine_ms=100)

    reel = journal_module.arreter_thread
    appels = []

    def _espion(thread, timeout_ms, debloquer=None, timeout_deblocage_ms=5_000, garder=()):
        appels.append((thread, timeout_ms, debloquer, garder))
        return reel(thread, timeout_ms, debloquer=debloquer,
                    timeout_deblocage_ms=timeout_deblocage_ms, garder=garder)

    monkeypatch.setattr(journal_module, "arreter_thread", _espion)

    machine.toggle_journal()
    machine.toggle_journal()  # lance le QThread de transcription (moteur lent → en cours)
    assert orch._thread is not None and orch._thread.isRunning()

    orch.terminer()

    assert len(appels) == 1
    _, timeout_ms, debloquer, garder = appels[0]
    assert timeout_ms == 10_000
    assert debloquer == moteur.terminer
    assert garder == (orch._worker,)
