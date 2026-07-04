"""Tests de HistoryView (refonte design) — porte la couverture comportementale de
l'ancienne FenetreHistorique (tests/test_historique_diarization.py) sur la nouvelle
structure table + délégués. L'ancienne fenêtre reste en place (câblée au tray)
jusqu'à l'Étape 4 ; ses propres tests ne sont pas touchés ici.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox
from scipy.io import wavfile

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE, chemin_locuteurs
from debrief_meet.ui import history_view as hv_module
from debrief_meet.ui.history_view import HistoryView


class FauxGestionnaire(QObject):
    demarre = Signal(object)
    termine = Signal(object, object)
    echoue = Signal(object, str)

    def __init__(self, dispo=True, job=None, type_job="diarization", diar_prete=True):
        super().__init__()
        self._dispo = dispo
        self._job = job
        self._type_job = type_job
        self._diar_prete = diar_prete
        self.lances: list = []
        self.lances_transcription: list = []

    def disponible(self):
        return self._dispo

    def diarization_prete(self):
        return self._dispo and self._diar_prete

    def job_en_cours(self):
        return self._job

    def type_job_en_cours(self):
        return self._type_job if self._job is not None else None

    def dernier_termine(self):
        return None

    def lancer(self, chemin_md):
        self.lances.append(chemin_md)
        if self._job is not None:
            return False
        self._job = chemin_md
        return True

    def lancer_transcription(self, chemin_md):
        self.lances_transcription.append(chemin_md)
        if self._job is not None:
            return False
        self._job = chemin_md
        return True


def _config(tmp_path):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path))
    cfg.set("dossier_journal", str(tmp_path))
    return cfg


def _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00", avec_systeme=True):
    md = tmp_path / f"{nom}.md"
    md.write_text("# brouillon", encoding="utf-8")
    n = 16000
    wavfile.write(tmp_path / f"{nom}_moi.wav", 16000, np.zeros(n, dtype=np.int16))
    if avec_systeme:
        wavfile.write(tmp_path / f"{nom}_systeme.wav", 16000, np.zeros(n, dtype=np.int16))
    return md


def _reunion_en_attente(tmp_path, nom="2026-03-03_09-00", avec_audio=True):
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion — {nom}\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    if avec_audio:
        n = 16000
        wavfile.write(tmp_path / f"{nom}_moi.wav", 16000, np.zeros(n, dtype=np.int16))
        wavfile.write(tmp_path / f"{nom}_systeme.wav", 16000, np.zeros(n, dtype=np.int16))
    return md


def _actions_reunion(vue: HistoryView, row: int = 0):
    index = vue._proxy_reunions.mapFromSource(vue._modele_reunions.index(row, 5))
    return vue._actions_pour_index(index, True)


def _spec(actions, icone):
    return next(a for a in actions if a.icone == icone)


# ── Colonne actions : disponibilité selon l'état ────────────────────────────────

def test_generer_grise_si_locuteurs_existent(qapp, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    chemin_locuteurs(md).write_text("loc", encoding="utf-8")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    generer = _spec(_actions_reunion(vue), "users")
    assert generer.actif is False
    assert "déjà générés" in generer.tooltip.lower()


def test_generer_grise_sans_audio(qapp, tmp_path):
    md = tmp_path / "2026-01-01_10-00.md"
    md.write_text("#", encoding="utf-8")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    actions = _actions_reunion(vue)
    assert _spec(actions, "users").actif is False
    assert _spec(actions, "microphone-slash").actif is False  # supprimer audio grisé aussi


def test_generer_actif_avec_audio_sans_locuteurs(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    actions = _actions_reunion(vue)
    assert _spec(actions, "users").actif is True
    assert _spec(actions, "microphone-slash").actif is True


def test_diarization_grise_si_non_configuree(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire(diar_prete=False))
    generer = _spec(_actions_reunion(vue), "users")
    assert generer.actif is False
    assert "non configurée" in generer.tooltip.lower()


def test_transcription_non_affectee_par_diarization_non_configuree(qapp, tmp_path):
    _reunion_en_attente(tmp_path)
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire(diar_prete=False))
    transcrire = _spec(_actions_reunion(vue), "file-text")
    assert transcrire.actif is True
    assert "transcrire" in transcrire.tooltip.lower()


def test_bouton_transcrire_grise_sans_audio(qapp, tmp_path):
    _reunion_en_attente(tmp_path, avec_audio=False)
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    transcrire = _spec(_actions_reunion(vue), "file-text")
    assert transcrire.actif is False
    assert "aucun audio" in transcrire.tooltip.lower()


def test_reunion_transcrite_montre_diarization_pas_transcrire(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    actions = _actions_reunion(vue)
    assert any(a.icone == "users" for a in actions)
    assert not any(a.icone == "file-text" for a in actions)


def test_ligne_en_cours_affiche_action_en_cours_desactivee(qapp, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire(job=md, type_job="diarization"))
    en_cours = _spec(_actions_reunion(vue), "clock-counter-clockwise")
    assert en_cours.actif is False
    assert "cours" in en_cours.tooltip.lower()


def test_journal_a_quatre_actions(qapp, tmp_path):
    (tmp_path / "2026-02-02.md").write_text("note", encoding="utf-8")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    index = vue._proxy_journal.mapFromSource(vue._modele_journal.index(0, 3))
    actions = vue._actions_pour_index(index, False)
    assert len(actions) == 4


def test_listing_exclut_locuteurs(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)
    chemin_locuteurs(tmp_path / "2026-01-01_10-00.md").write_text("loc", encoding="utf-8")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    assert vue._modele_reunions.rowCount() == 1


# ── Diarization / transcription déléguées ───────────────────────────────────────

def test_generer_delegue_au_gestionnaire(qapp, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaire()
    vue = HistoryView(_config(tmp_path), gestionnaire=g)
    vue._generer(md)
    assert g.lances == [md]


def test_generer_refuse_si_non_configuree(qapp, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaire(diar_prete=False)
    vue = HistoryView(_config(tmp_path), gestionnaire=g)
    vue._generer(md)
    assert g.lances == []


def test_generer_sans_audio_affiche_message(qapp, tmp_path, monkeypatch):
    md = tmp_path / "2026-01-01_10-00.md"
    md.write_text("#", encoding="utf-8")
    g = FauxGestionnaire()
    vue = HistoryView(_config(tmp_path), gestionnaire=g)
    appels = []
    monkeypatch.setattr(hv_module.QMessageBox, "information", lambda *a, **k: appels.append(a))
    vue._generer(md)
    assert appels
    assert g.lances == []


def test_transcrire_delegue_au_gestionnaire(qapp, tmp_path):
    md = _reunion_en_attente(tmp_path)
    g = FauxGestionnaire()
    vue = HistoryView(_config(tmp_path), gestionnaire=g)
    vue._transcrire(md)
    assert g.lances_transcription == [md]


# ── Suppressions ─────────────────────────────────────────────────────────────

def test_supprimer_audio_retire_les_pistes(qapp, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(hv_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    vue._supprimer_audio_un(md)
    assert not (tmp_path / "2026-01-01_10-00_moi.wav").exists()
    assert not (tmp_path / "2026-01-01_10-00_systeme.wav").exists()
    assert md.exists()


def test_tout_supprimer_retire_md_locuteurs_audio(qapp, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    loc = chemin_locuteurs(md)
    loc.write_text("loc", encoding="utf-8")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(hv_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    vue._tout_supprimer_un(md, True)
    assert not md.exists()
    assert not loc.exists()
    assert not (tmp_path / "2026-01-01_10-00_moi.wav").exists()


def test_suppression_de_masse_sur_selection(qapp, tmp_path, monkeypatch):
    a = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    b = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    vue._table_reunions.selectAll()
    monkeypatch.setattr(hv_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    vue._tout_supprimer(vue._table_reunions, True, a)
    assert not a.exists() and not b.exists()


# ── Sélection programmatique + rafraîchissement live ────────────────────────────

def test_selectionner_reunion_cible_la_bonne_ligne(qapp, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    cible = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    vue.selectionner_reunion(cible)
    assert vue._chemins_selectionnes(vue._table_reunions, vue._modele_reunions) == [cible]


def test_refresh_voit_nouvelle_reunion(qapp, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    vue = HistoryView(_config(tmp_path), gestionnaire=FauxGestionnaire())
    assert vue._modele_reunions.rowCount() == 1
    _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    vue.recharger_tout()
    assert vue._modele_reunions.rowCount() == 2


# ── Copie avec prompt actif ──────────────────────────────────────────────────

def _md_simple(tmp_path, nom="2026-01-01_10-00", corps="ligne de transcription"):
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion\n\n{corps}", encoding="utf-8")
    return md


def test_copier_prefixe_le_prompt_actif(qapp, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Fais un CR."}])
    cfg.set("prompt_actif", 0)
    pp = PressePapiersFake()
    vue = HistoryView(cfg, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    vue._copier(md, est_reunion=True)
    assert pp.dernier.startswith("Fais un CR.\n\n")
    assert "ligne de transcription" in pp.dernier


def test_copier_diarization_prefixe_aussi(qapp, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    chemin_locuteurs(md).write_text("# Locuteurs\n\nMoi : salut", encoding="utf-8")
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Résume."}])
    cfg.set("prompt_actif", 0)
    pp = PressePapiersFake()
    vue = HistoryView(cfg, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    vue._copier(md, est_reunion=True)
    assert pp.dernier.startswith("Résume.\n\n")
    assert "Moi : salut" in pp.dernier
