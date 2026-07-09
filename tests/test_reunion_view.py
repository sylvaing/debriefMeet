"""Tests de ReunionView (refonte design v2) — porte la couverture
comportementale réunion de l'ancienne `HistoryView` (v1, disparue,
cf. tests/test_history_view.py) + les nouveaux comportements v2 : barre
d'action (bouton bascule) et ligne « en cours » (CHANGELOG_v2 §2/§3).
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox
from scipy.io import wavfile

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE, chemin_locuteurs
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui import reunion_view as rv_module
from debrief_meet.ui.reunion_view import ReunionView
from debrief_meet.ui.status_pill import HistoryState


@pytest.fixture
def machine(qapp):
    return MachineEtats()


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


def _actions(vue: ReunionView, row: int = 0):
    index = vue._proxy.mapFromSource(vue._modele.index(row, 5))
    return vue._actions_pour_index(index)


def _spec(actions, icone):
    return next(a for a in actions if a.icone == icone)


# ── Colonne actions : disponibilité selon l'état ────────────────────────────────

def test_generer_grise_si_locuteurs_existent(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    chemin_locuteurs(md).write_text("loc", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    generer = _spec(_actions(vue), "users")
    assert generer.actif is False
    assert "déjà générés" in generer.tooltip.lower()


def test_generer_grise_sans_audio(qapp, machine, tmp_path):
    md = tmp_path / "2026-01-01_10-00.md"
    md.write_text("#", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    actions = _actions(vue)
    assert _spec(actions, "users").actif is False
    assert _spec(actions, "microphone-slash").actif is False  # supprimer audio grisé aussi


def test_generer_actif_avec_audio_sans_locuteurs(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    actions = _actions(vue)
    assert _spec(actions, "users").actif is True
    assert _spec(actions, "microphone-slash").actif is True


def test_diarization_grise_si_non_configuree(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(diar_prete=False))
    generer = _spec(_actions(vue), "users")
    assert generer.actif is False
    assert "non configurée" in generer.tooltip.lower()


def test_transcription_non_affectee_par_diarization_non_configuree(qapp, machine, tmp_path):
    _reunion_en_attente(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(diar_prete=False))
    transcrire = _spec(_actions(vue), "file-text")
    assert transcrire.actif is True
    assert "transcrire" in transcrire.tooltip.lower()


def test_bouton_transcrire_grise_sans_audio(qapp, machine, tmp_path):
    _reunion_en_attente(tmp_path, avec_audio=False)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    transcrire = _spec(_actions(vue), "file-text")
    assert transcrire.actif is False
    assert "aucun audio" in transcrire.tooltip.lower()


def test_reunion_transcrite_montre_diarization_pas_transcrire(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    actions = _actions(vue)
    assert any(a.icone == "users" for a in actions)
    assert not any(a.icone == "file-text" for a in actions)


def test_action_en_cours_diarization_desactive_le_bouton(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(job=md, type_job="diarization"))
    en_cours = _spec(_actions(vue), "clock-counter-clockwise")
    assert en_cours.actif is False
    assert "cours" in en_cours.tooltip.lower()


def test_listing_exclut_locuteurs(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    chemin_locuteurs(tmp_path / "2026-01-01_10-00.md").write_text("loc", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert vue._modele.rowCount() == 1


# ── Diarization / transcription déléguées ───────────────────────────────────────

def test_generer_delegue_au_gestionnaire(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaire()
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=g)
    vue._generer(md)
    assert g.lances == [md]


def test_generer_refuse_si_non_configuree(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaire(diar_prete=False)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=g)
    vue._generer(md)
    assert g.lances == []


def test_generer_sans_audio_affiche_message(qapp, machine, tmp_path, monkeypatch):
    md = tmp_path / "2026-01-01_10-00.md"
    md.write_text("#", encoding="utf-8")
    g = FauxGestionnaire()
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=g)
    appels = []
    monkeypatch.setattr(rv_module.QMessageBox, "information", lambda *a, **k: appels.append(a))
    vue._generer(md)
    assert appels
    assert g.lances == []


def test_transcrire_delegue_au_gestionnaire(qapp, machine, tmp_path):
    md = _reunion_en_attente(tmp_path)
    g = FauxGestionnaire()
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=g)
    vue._transcrire(md)
    assert g.lances_transcription == [md]


# ── Suppressions ─────────────────────────────────────────────────────────────

def test_supprimer_audio_retire_les_pistes(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(rv_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    vue._supprimer_audio_un(md)
    assert not (tmp_path / "2026-01-01_10-00_moi.wav").exists()
    assert not (tmp_path / "2026-01-01_10-00_systeme.wav").exists()
    assert md.exists()


def test_tout_supprimer_retire_md_locuteurs_audio(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    loc = chemin_locuteurs(md)
    loc.write_text("loc", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(rv_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    vue._tout_supprimer_un(md)
    assert not md.exists()
    assert not loc.exists()
    assert not (tmp_path / "2026-01-01_10-00_moi.wav").exists()


def test_suppression_de_masse_sur_selection(qapp, machine, tmp_path, monkeypatch):
    a = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    b = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue._table.selectAll()
    monkeypatch.setattr(rv_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    vue._tout_supprimer(a)
    assert not a.exists() and not b.exists()


# ── Sélection programmatique + rafraîchissement live ────────────────────────────

def test_selectionner_reunion_cible_la_bonne_ligne(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    cible = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue.selectionner_reunion(cible)
    assert vue._chemins_selectionnes() == [cible]


def test_refresh_voit_nouvelle_reunion(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert vue._modele.rowCount() == 1
    _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    vue.recharger()
    assert vue._modele.rowCount() == 2


# ── Copie avec prompt actif ──────────────────────────────────────────────────

def _md_simple(tmp_path, nom="2026-01-01_10-00", corps="ligne de transcription"):
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion\n\n{corps}", encoding="utf-8")
    return md


def test_copier_prefixe_le_prompt_actif(qapp, machine, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Fais un CR."}])
    cfg.set("prompt_actif", 0)
    pp = PressePapiersFake()
    vue = ReunionView(cfg, machine, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    vue._copier(md)
    assert pp.dernier.startswith("Fais un CR.\n\n")
    assert "ligne de transcription" in pp.dernier


def test_copier_diarization_prefixe_aussi(qapp, machine, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    chemin_locuteurs(md).write_text("# Locuteurs\n\nMoi : salut", encoding="utf-8")
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Résume."}])
    cfg.set("prompt_actif", 0)
    pp = PressePapiersFake()
    vue = ReunionView(cfg, machine, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    vue._copier(md)
    assert pp.dernier.startswith("Résume.\n\n")
    assert "Moi : salut" in pp.dernier


# ── Barre d'action (bouton bascule) ──────────────────────────────────────────

def test_bouton_bascule_declenche_toggle_reunion(qapp, machine, tmp_path):
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue._action_bar._bouton.click()
    assert machine.mode == Mode.REUNION


def test_bouton_grise_si_autre_type_actif(qapp, machine, tmp_path):
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    machine.toggle_dictee()
    vue.definir_etat_enregistrement(machine.mode, machine.elapsed_seconds())
    assert not vue._action_bar._bouton.isEnabled()


# ── Ligne « en cours » (CHANGELOG_v2 §3) ─────────────────────────────────────

def test_ligne_en_cours_inseree_en_tete(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert vue._modele.rowCount() == 1
    vue.definir_etat_enregistrement(Mode.REUNION, 5)
    assert vue._modele.rowCount() == 2
    idx_etat = vue._modele.index(0, 4)
    assert vue._modele.data(idx_etat, Qt.ItemDataRole.UserRole) == HistoryState.EN_COURS
    idx_titre = vue._modele.index(0, 1)
    assert vue._modele.data(idx_titre) == "Réunion en cours"


def test_ligne_en_cours_pas_d_actions(qapp, machine, tmp_path):
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue.definir_etat_enregistrement(Mode.REUNION, 5)
    assert _actions(vue) == []


def test_ligne_en_cours_disparait_a_l_arret(qapp, machine, tmp_path):
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue.definir_etat_enregistrement(Mode.REUNION, 5)
    assert vue._modele.rowCount() == 1
    vue.definir_etat_enregistrement(Mode.IDLE, 0)
    assert vue._modele.rowCount() == 0


def test_ligne_en_cours_absente_pour_autre_type(qapp, machine, tmp_path):
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue.definir_etat_enregistrement(Mode.DICTEE, 5)
    assert vue._modele.rowCount() == 0


# ── Interco BlueMind — F1 (docs/40 §6) ──────────────────────────────────────

def _store_avec_evenement(tmp_path, debut_ms, fin_ms, titre="Point projet X"):
    from debrief_meet.core.bluemind.store import Evenement, StoreCalendrier
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([Evenement(
        uid="evt-1", cal_uid="cal:Default:u1", debut_ms=debut_ms, fin_ms=fin_ms,
        journee_entiere=False, titre=titre, lieu="",
        organisateur={"nom": "Sylvain Garcia", "email": "sylvain@ex.com"},
        invites=[{"nom": "Jean Dupont", "email": "jean@ex.com", "part_status": "Accepted"}],
    )])
    return store


def test_sans_store_bluemind_pas_daction(qapp, machine, tmp_path):
    from datetime import datetime
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    debut = datetime(2026, 1, 1, 10, 0)
    _store_avec_evenement(tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())  # pas de store_bluemind
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_BLUEMIND_ASSOCIER not in icones


def test_action_associer_presente_si_correspondance(qapp, machine, tmp_path):
    from datetime import datetime
    nom = "2026-01-01_10-00"
    _reunion_avec_audio(tmp_path, nom=nom)
    debut = datetime(2026, 1, 1, 10, 0)
    store = _store_avec_evenement(tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    spec = _spec(_actions(vue), rv_module._ICONE_BLUEMIND_ASSOCIER)
    assert spec.actif is True


def test_action_absente_sans_correspondance(qapp, machine, tmp_path):
    from datetime import datetime
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    debut = datetime(2026, 6, 1, 10, 0)  # loin de la réunion
    store = _store_avec_evenement(tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_BLUEMIND_ASSOCIER not in icones


def test_nommer_locuteurs_present_si_locuteurs_md(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    chemin_locuteurs(md).write_text("# X\n\n**Moi** [00:00] bonjour\n", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    spec = _spec(_actions(vue), rv_module._ICONE_NOMMER_LOCUTEURS)
    assert spec.actif is True


def test_nommer_locuteurs_absent_sans_locuteurs_md(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_NOMMER_LOCUTEURS not in icones


def test_nommer_locuteurs_disponible_sans_store_bluemind(qapp, machine, tmp_path):
    """F2 n'est pas gatée par la config BlueMind (§7) — utilisable en saisie libre."""
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    chemin_locuteurs(md).write_text("# X\n\n**Moi** [00:00] bonjour\n", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())  # store_bluemind=None
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_NOMMER_LOCUTEURS in icones


def test_action_indique_deja_associe(qapp, machine, tmp_path):
    from debrief_meet.core.bluemind.association import Association, ecrire
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    ecrire(md, Association(event_uid="e1", cal_uid="cal", titre="Point projet X",
                            debut="2026-01-01T10:00:00", invites=[]))
    store = _store_avec_evenement(tmp_path, 0, 1)  # peu importe, déjà associé
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    spec = _spec(_actions(vue), rv_module._ICONE_BLUEMIND_ASSOCIE)
    assert spec.actif is False
    assert "Point projet X" in spec.tooltip
