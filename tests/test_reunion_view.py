"""Tests de ReunionView (refonte design v2) — porte la couverture
comportementale réunion de l'ancienne `HistoryView` (v1, disparue,
cf. tests/test_history_view.py) + les nouveaux comportements v2 : barre
d'action (bouton bascule) et ligne « en cours » (CHANGELOG_v2 §2/§3).
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QObject, Qt, Signal
from scipy.io import wavfile

from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE, chemin_cr_mistral, chemin_locuteurs
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


class FauxGestionnaireCRMistral(QObject):
    """Miroir de FauxGestionnaire pour l'interco Mistral (docs/42)."""

    demarre = Signal(object)
    termine = Signal(object, object)
    echoue = Signal(object, str)

    def __init__(self, dispo=True, job=None):
        super().__init__()
        self._dispo = dispo
        self._job = job
        self.lances: list = []
        self.prompts: list = []

    def disponible(self):
        return self._dispo

    def job_en_cours(self):
        return self._job

    def lancer(self, chemin_md, prompt=None):
        self.lances.append(chemin_md)
        self.prompts.append(prompt)
        if self._job is not None:
            return False
        self._job = chemin_md
        return True


def _config(tmp_path):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path))
    cfg.set("dossier_journal", str(tmp_path))
    return cfg


def _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00", avec_systeme=True):
    dossier = tmp_path / nom
    dossier.mkdir(exist_ok=True)
    md = dossier / "transcription.md"
    md.write_text("# brouillon", encoding="utf-8")
    n = 16000
    wavfile.write(dossier / "moi.wav", 16000, np.zeros(n, dtype=np.int16))
    if avec_systeme:
        wavfile.write(dossier / "systeme.wav", 16000, np.zeros(n, dtype=np.int16))
    return md


def _reunion_en_attente(tmp_path, nom="2026-03-03_09-00-00", avec_audio=True):
    dossier = tmp_path / nom
    dossier.mkdir(exist_ok=True)
    md = dossier / "transcription.md"
    md.write_text(f"# Réunion — {nom}\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    if avec_audio:
        n = 16000
        wavfile.write(dossier / "moi.wav", 16000, np.zeros(n, dtype=np.int16))
        wavfile.write(dossier / "systeme.wav", 16000, np.zeros(n, dtype=np.int16))
    return md


def _ligne_actions(vue: ReunionView, row: int = 0):
    index = vue._proxy.mapFromSource(vue._modele.index(row, 5))
    return vue._actions_pour_index(index)


def _actions(vue: ReunionView, row: int = 0):
    """Items du menu ⋯ (exhaustif — contient toutes les actions de la ligne)."""
    return _ligne_actions(vue, row).menu


def _boutons(vue: ReunionView, row: int = 0):
    """Boutons dédiés de la colonne actions (Générer le CR ▾ + Copier le CR)."""
    return _ligne_actions(vue, row).boutons


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
    dossier = tmp_path / "2026-01-01_10-00-00"
    dossier.mkdir()
    md = dossier / "transcription.md"
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
    md = _reunion_avec_audio(tmp_path)
    chemin_locuteurs(md).write_text("loc", encoding="utf-8")
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
    dossier = tmp_path / "2026-01-01_10-00-00"
    dossier.mkdir()
    md = dossier / "transcription.md"
    md.write_text("#", encoding="utf-8")
    g = FauxGestionnaire()
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=g)
    appels = []
    monkeypatch.setattr(rv_module.dialogues, "avertir", lambda *a, **k: appels.append(a))
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
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._supprimer_audio_un(md)
    assert not md.with_name("moi.wav").exists()
    assert not md.with_name("systeme.wav").exists()
    assert md.exists()


def test_tout_supprimer_retire_md_locuteurs_audio(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    loc = chemin_locuteurs(md)
    loc.write_text("loc", encoding="utf-8")
    moi = md.with_name("moi.wav")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._tout_supprimer_un(md)
    assert not md.exists()
    assert not loc.exists()
    assert not moi.exists()
    assert not md.parent.exists()   # le dossier entier de la réunion a disparu (docs/43 §8)


def test_tout_supprimer_retire_aussi_le_cr_mistral(qapp, machine, tmp_path, monkeypatch):
    """Le CR Mistral (`*_CR.md`, docs/42) est un dérivé de la réunion — il doit
    disparaître avec elle, comme le débrief locuteurs."""
    md = _reunion_avec_audio(tmp_path)
    cr = chemin_cr_mistral(md)
    cr.write_text("# CR — Sujet — 2026-01-01", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._tout_supprimer_un(md)
    assert not md.exists()
    assert not cr.exists()


def test_tout_supprimer_retire_aussi_le_sidecar_bluemind(qapp, machine, tmp_path, monkeypatch):
    """Le sidecar d'association BlueMind (`*.bluemind.json`, docs/40) est un dérivé
    de la réunion — il doit disparaître avec elle."""
    from debrief_meet.core.bluemind import association as bluemind_association
    md = _reunion_avec_audio(tmp_path)
    sidecar = bluemind_association.chemin_sidecar(md)
    sidecar.write_text('{"event_uid": "x", "cal_uid": "y"}', encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._tout_supprimer_un(md)
    assert not md.exists()
    assert not sidecar.exists()


def test_suppression_de_masse_sur_selection(qapp, machine, tmp_path, monkeypatch):
    a = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    b = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue._table.selectAll()
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._tout_supprimer(a)
    assert not a.exists() and not b.exists()


# ── Sélection programmatique + rafraîchissement live ────────────────────────────

def test_selectionner_reunion_cible_la_bonne_ligne(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    cible = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue.selectionner_reunion(cible)
    assert vue._chemins_selectionnes() == [cible]


def test_refresh_voit_nouvelle_reunion(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert vue._modele.rowCount() == 1
    _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00-00")
    vue.recharger()
    assert vue._modele.rowCount() == 2


# ── Copie brute (plus jamais de préfixe prompt/lexique, 2026-08-21) ──────────

def _md_simple(tmp_path, nom="2026-01-01_10-00-00", corps="ligne de transcription"):
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion\n\n{corps}", encoding="utf-8")
    return md


def test_copier_reste_brut_meme_avec_prompt_actif(qapp, machine, tmp_path):
    """Prompt actif ET lexique actif (défauts) : la copie reste le contenu tel quel."""
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Fais un CR."}])
    cfg.set("prompt_actif", 0)
    pp = PressePapiersFake()
    vue = ReunionView(cfg, machine, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    vue._copier(md)
    assert pp.dernier == md.read_text(encoding="utf-8")
    assert "Fais un CR." not in pp.dernier
    assert "Corrections de transcription" not in pp.dernier


def test_copier_prefere_la_version_diarizee_brute(qapp, machine, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    chemin_locuteurs(md).write_text("# Locuteurs\n\nMoi : salut", encoding="utf-8")
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Résume."}])
    cfg.set("prompt_actif", 0)
    pp = PressePapiersFake()
    vue = ReunionView(cfg, machine, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    vue._copier(md)
    assert pp.dernier == "# Locuteurs\n\nMoi : salut"


# ── CR Mistral (docs/42) ─────────────────────────────────────────────────────

def test_cr_mistral_absent_sans_gestionnaire(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    actions = _actions(vue)
    assert not any(a.icone == "notebook" for a in actions)


def test_cr_mistral_grise_si_indisponible(qapp, machine, tmp_path):
    # Grisé (et non masqué) : la fonction reste découvrable, l'infobulle renvoie
    # vers les Préférences — même état sur le bouton dédié et dans le menu ⋯.
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral(dispo=False))
    cr = _spec(_actions(vue), "notebook")
    assert cr.actif is False
    assert "non configuré" in cr.tooltip.lower()
    bouton = _spec(_boutons(vue), "notebook")
    assert bouton.actif is False
    assert bouton.tooltip == cr.tooltip


def test_cr_mistral_actif_avec_transcript_local(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)   # .md non placeholder = transcript local exploitable
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    cr = _spec(_actions(vue), "notebook")
    assert cr.actif is True


def test_cr_mistral_actif_avec_audio_sans_transcript(qapp, machine, tmp_path):
    _reunion_en_attente(tmp_path)   # placeholder (enregistrement seul) mais audio présent
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    cr = _spec(_actions(vue), "notebook")
    assert cr.actif is True         # repli Voxtral possible (§1)


def test_cr_mistral_grise_sans_rien_a_exploiter(qapp, machine, tmp_path):
    _reunion_en_attente(tmp_path, avec_audio=False)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    cr = _spec(_actions(vue), "notebook")
    assert cr.actif is False
    assert "aucune transcription" in cr.tooltip.lower()


def test_cr_mistral_en_cours(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral(job=md))
    en_cours = _spec(_actions(vue), "clock-counter-clockwise")
    assert en_cours.actif is False
    assert "cr en cours" in en_cours.tooltip.lower()


def test_cr_mistral_grise_si_autre_job_diarization_tourne(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00-00")
    autre = tmp_path / "2026-01-01_10-00.md"
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(job=autre),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    cr = _spec(_actions(vue, row=0), "notebook")
    assert cr.actif is False
    assert "cours" in cr.tooltip.lower()


def test_generer_cr_mistral_delegue_au_gestionnaire(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    cfg.set("mistral_confidentialite_acceptee", True)   # évite la boîte de confirmation
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    vue._generer_cr_mistral(md)
    assert g.lances == [md]


def test_generer_cr_mistral_demande_confirmation_au_premier_envoi(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    assert cfg.get("mistral_confidentialite_acceptee") is False
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: False)
    vue._generer_cr_mistral(md)
    assert g.lances == []                                # refusé → pas lancé
    assert cfg.get("mistral_confidentialite_acceptee") is False


def test_generer_cr_mistral_confirmation_acceptee_memorisee(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._generer_cr_mistral(md)
    assert g.lances == [md]
    assert cfg.get("mistral_confidentialite_acceptee") is True


def test_generer_cr_mistral_refuse_si_indisponible(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral(dispo=False)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    vue._generer_cr_mistral(md)
    assert g.lances == []


# ── Boutons dédiés : Générer le CR ▾ + Copier le CR ──────────────────────────────

def test_boutons_dedies_generer_cr_et_copier_cr(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    boutons = _boutons(vue)
    assert [b.icone for b in boutons] == ["notebook", "copy", "file-arrow-up"]
    generer, copier, _fichier = boutons
    assert generer.actif is True
    assert copier.actif is False                    # pas de CR généré → grisé
    assert "aucun cr" in copier.tooltip.lower()


def test_boutons_sans_gestionnaire_cr_seul_copier_reste(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert [b.icone for b in _boutons(vue)] == ["copy", "file-arrow-up"]


def test_bouton_copier_cr_actif_avec_cr(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    chemin_cr_mistral(md).write_text("# CR", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    copier = _spec(_boutons(vue), "copy")
    assert copier.actif is True
    assert copier.tooltip == "Copier le CR"


def test_menu_contient_copier_le_cr_quand_disponible(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert not any(a.tooltip == "Copier le CR" for a in _actions(vue))
    chemin_cr_mistral(md).write_text("# CR", encoding="utf-8")
    vue.recharger()
    assert any(a.tooltip == "Copier le CR" for a in _actions(vue))


def test_menu_commence_par_copier_la_transcription(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert _actions(vue)[0].tooltip == "Copier la transcription"
    assert _actions(vue)[1].tooltip == "Copier le fichier de la transcription"


# ── Copier le fichier de la transcription ────────────────────────────────────

def test_copier_fichier_pose_transcription_md(qapp, machine, tmp_path):
    """Toujours `transcription.md` lui-même — jamais la version diarizée."""
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    chemin_locuteurs(md).write_text("# Locuteurs\n\nMoi : salut", encoding="utf-8")
    pp = PressePapiersFake()
    vue = ReunionView(_config(tmp_path), machine, presse_papiers=pp,
                      gestionnaire=FauxGestionnaire())
    vue._copier_fichier(md)
    assert pp.fichiers_copies == [md]
    assert pp.historique == []      # référence de fichier, pas de texte


def test_copier_fichier_ignore_un_chemin_absent(qapp, machine, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    pp = PressePapiersFake()
    vue = ReunionView(_config(tmp_path), machine, presse_papiers=pp,
                      gestionnaire=FauxGestionnaire())
    vue._copier_fichier(tmp_path / "absent.md")
    assert pp.fichiers_copies == []


def test_bouton_copier_fichier_present_meme_en_attente(qapp, machine, tmp_path):
    """La transcription.md existe dès le démarrage : le bouton est toujours actif."""
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    bouton = _spec(_boutons(vue), "file-arrow-up")
    assert bouton.actif is True
    assert bouton.tooltip == "Copier le fichier de la transcription"


def test_copier_cr_copie_le_contenu_brut_sans_prefixe(qapp, machine, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _reunion_avec_audio(tmp_path)
    chemin_cr_mistral(md).write_text("# CR — Point\n\ncontenu", encoding="utf-8")
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Fais un CR."}])
    cfg.set("prompt_actif", 0)                       # le prompt actif ne doit PAS préfixer
    pp = PressePapiersFake()
    vue = ReunionView(cfg, machine, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    vue._copier_cr(md)
    assert pp.dernier == "# CR — Point\n\ncontenu"


# ── Flèche du bouton Générer le CR : choix ponctuel du prompt ─────────────────────

def test_fleche_absente_avec_un_seul_prompt(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "CR simple", "contenu": "Simple."}])
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    generer = _spec(_boutons(vue), "notebook")
    assert generer.menu_deroulant is None            # 1 seul prompt → pas de flèche


def test_fleche_liste_les_prompts_et_lance_avec_le_prompt_choisi(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "CR simple", "contenu": "Simple."},
                        {"titre": "CR détaillé", "contenu": "Détaillé."}])
    cfg.set("prompt_actif", 0)
    cfg.set("mistral_confidentialite_acceptee", True)
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    generer = _spec(_boutons(vue), "notebook")
    assert [a.tooltip for a in generer.menu_deroulant] == ["CR simple", "CR détaillé"]

    generer.menu_deroulant[1].on_click()
    assert g.lances == [md]
    assert g.prompts == ["Détaillé."]                # contenu du prompt choisi, ponctuel
    assert cfg.get("prompt_actif") == 0              # le prompt actif ne change pas


def test_fleche_ignore_les_prompts_vides(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P1", "contenu": "Un."},
                        {"titre": "Vide", "contenu": "   "}])
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(),
                      gestionnaire_cr_mistral=FauxGestionnaireCRMistral())
    generer = _spec(_boutons(vue), "notebook")
    assert generer.menu_deroulant is None            # 1 seul prompt exploitable → pas de flèche


def test_clic_principal_lance_avec_le_prompt_actif(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    cfg.set("mistral_confidentialite_acceptee", True)
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    _spec(_boutons(vue), "notebook").on_click()
    assert g.lances == [md]
    assert g.prompts == [None]                       # None → prompt actif (pipeline)


# ── Régénération : confirmation de remplacement quand un CR existe ────────────────

def test_regenerer_cr_existant_demande_confirmation(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    chemin_cr_mistral(md).write_text("# CR", encoding="utf-8")
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    cfg.set("mistral_confidentialite_acceptee", True)
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    titres = []

    def _confirmer(*_a, **k):
        titres.append(k.get("titre", ""))
        return True

    monkeypatch.setattr(rv_module.dialogues, "confirmer", _confirmer)
    vue._generer_cr_mistral(md)
    assert any("remplacer" in t.lower() for t in titres)
    assert g.lances == [md]


def test_regenerer_cr_refuse_ne_lance_rien(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    chemin_cr_mistral(md).write_text("# CR", encoding="utf-8")
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    cfg.set("mistral_confidentialite_acceptee", True)
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: False)
    vue._generer_cr_mistral(md)
    assert g.lances == []


def test_pas_de_confirmation_de_remplacement_sans_cr(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral()
    cfg = _config(tmp_path)
    cfg.set("mistral_confidentialite_acceptee", True)
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    appels = []
    monkeypatch.setattr(rv_module.dialogues, "confirmer",
                        lambda *a, **k: appels.append(k) or True)
    vue._generer_cr_mistral(md)
    assert appels == []                              # ni remplacement ni confidentialité (acceptée)
    assert g.lances == [md]


def test_cr_mistral_termine_propose_ouvrir(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    sortie = md.with_name("CR.md")
    sortie.write_text("# CR", encoding="utf-8")
    g = FauxGestionnaireCRMistral()
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    vue.show()
    ouverts = []
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    monkeypatch.setattr(vue, "_ouvrir", lambda c: ouverts.append(c))
    vue._sur_cr_mistral_termine(md, sortie)
    assert ouverts == [sortie]
    # Le CR généré ne doit PAS apparaître comme une ligne fantôme dans l'Historique
    # (sans date/durée, impossible à associer ou diariser) — cf. core/fichiers.py
    # lister_enregistrements, qui l'exclut comme les fichiers _locuteurs.md.
    assert vue._modele.rowCount() == 1


def test_cr_mistral_echoue_affiche_message(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaireCRMistral()
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), gestionnaire_cr_mistral=g)
    vue.show()
    appels = []
    monkeypatch.setattr(rv_module.dialogues, "avertir", lambda *a, **k: appels.append(a))
    vue._sur_cr_mistral_echoue(md, "clé invalide")
    assert appels


# ── Proposition d'association BlueMind avant le CR (docs/42 + docs/40 §6) ───────

class FauxDialogAssociation:
    """Substitut de `DialogAssociationBluemind` : `issue` décide de la sortie simulée
    (« associer » / « ignorer » / « annuler ») sans ouvrir de fenêtre."""

    from PySide6.QtWidgets import QDialog as _QDialog
    DialogCode = _QDialog.DialogCode
    instances: list = []

    issue = "associer"
    nouveau_chemin = None            # chemin renvoyé après « associer » (renommage simulé)

    def __init__(self, chemin_md, evenements, parent=None, contexte_cr=False):
        self.chemin_md_initial = chemin_md
        self.evenements = evenements
        self.contexte_cr = contexte_cr
        FauxDialogAssociation.instances.append(self)

    @property
    def chemin_md(self):
        return FauxDialogAssociation.nouveau_chemin or self.chemin_md_initial

    @property
    def association_ignoree(self):
        return FauxDialogAssociation.issue == "ignorer"

    def exec(self):
        if FauxDialogAssociation.issue == "annuler":
            return self.DialogCode.Rejected
        return self.DialogCode.Accepted


@pytest.fixture
def faux_dialog_association(monkeypatch):
    """Remplace le dialogue F1 (import tardif → résolu à l'appel) et remet à zéro l'état
    de classe entre les tests."""
    FauxDialogAssociation.instances = []
    FauxDialogAssociation.issue = "associer"
    FauxDialogAssociation.nouveau_chemin = None
    monkeypatch.setattr("debrief_meet.ui.bluemind_association.DialogAssociationBluemind",
                        FauxDialogAssociation)
    return FauxDialogAssociation


def _vue_cr_avec_bluemind(tmp_path, machine, store=None, synchro=None):
    """Vue prête pour le flux CR : confidentialité déjà acceptée (isole la proposition)."""
    cfg = _config(tmp_path)
    cfg.set("mistral_confidentialite_acceptee", True)
    g = FauxGestionnaireCRMistral()
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(), store_bluemind=store,
                      gestionnaire_cr_mistral=g, synchro_bluemind=synchro)
    return vue, g


def _store_correspondant(tmp_path, nom="2026-01-01_10-00-00"):
    from datetime import datetime
    debut = datetime(2026, 1, 1, 10, 0)
    return _store_avec_evenement(
        tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)


def test_cr_sans_store_bluemind_ne_propose_rien(qapp, machine, tmp_path, faux_dialog_association):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine)          # store_bluemind=None
    vue._generer_cr_mistral(md)
    assert faux_dialog_association.instances == []
    assert g.lances == [md]


def test_cr_sans_correspondance_ne_propose_rien(qapp, machine, tmp_path, faux_dialog_association):
    from datetime import datetime
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    loin = datetime(2026, 6, 1, 10, 0)
    store = _store_avec_evenement(
        tmp_path, int(loin.timestamp() * 1000), int(loin.timestamp() * 1000) + 1800_000)
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=store)
    vue._generer_cr_mistral(md)
    assert faux_dialog_association.instances == []
    assert g.lances == [md]


def test_cr_deja_associee_ne_propose_rien(qapp, machine, tmp_path, faux_dialog_association):
    from debrief_meet.core.bluemind.association import Association, ecrire
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    ecrire(md, Association(event_uid="e1", cal_uid="cal", titre="Point projet X",
                           debut="2026-01-01T10:00:00", invites=[]))
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path))
    vue._generer_cr_mistral(md)
    assert faux_dialog_association.instances == []
    assert g.lances == [md]


def test_cr_propose_lassociation_si_correspondance(qapp, machine, tmp_path, faux_dialog_association):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path))
    vue._generer_cr_mistral(md)
    assert len(faux_dialog_association.instances) == 1
    dlg = faux_dialog_association.instances[0]
    assert dlg.contexte_cr is True                 # variante à 3 boutons
    assert [e.uid for e in dlg.evenements] == ["evt-1"]
    assert g.lances == [md]


def test_cr_lance_sur_le_nouveau_chemin_apres_renommage(qapp, machine, tmp_path,
                                                        faux_dialog_association):
    """« Associer » applique le titre → le dossier est renommé : le job doit porter sur le
    nouveau chemin, sinon il travaillerait sur un dossier disparu (docs/43 §6.1)."""
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    nouveau_dossier = tmp_path / "2026-01-01_10-00-00_Point-projet-X"
    md.parent.rename(nouveau_dossier)
    faux_dialog_association.nouveau_chemin = nouveau_dossier / "transcription.md"
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path))
    vue._generer_cr_mistral(md)
    assert g.lances == [nouveau_dossier / "transcription.md"]


def test_cr_repli_sur_le_chemin_dorigine_si_nouveau_absent(qapp, machine, tmp_path,
                                                           faux_dialog_association):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    faux_dialog_association.nouveau_chemin = tmp_path / "jamais-cree" / "transcription.md"
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path))
    vue._generer_cr_mistral(md)
    assert g.lances == [md]


def test_cr_sans_association_lance_quand_meme(qapp, machine, tmp_path, faux_dialog_association):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    faux_dialog_association.issue = "ignorer"
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path))
    vue._generer_cr_mistral(md)
    assert g.lances == [md]


def test_cr_annule_ne_lance_rien(qapp, machine, tmp_path, faux_dialog_association):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    faux_dialog_association.issue = "annuler"
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path))
    vue._generer_cr_mistral(md)
    assert g.lances == []


def test_association_proposee_avant_la_confidentialite(qapp, machine, tmp_path, monkeypatch,
                                                       faux_dialog_association):
    """Ordre voulu : l'association change ce qui part chez Mistral, donc elle passe avant
    la confirmation d'envoi du premier usage."""
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    cfg = _config(tmp_path)                       # confidentialité PAS encore acceptée
    g = FauxGestionnaireCRMistral()
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(),
                      store_bluemind=_store_correspondant(tmp_path), gestionnaire_cr_mistral=g)
    ordre = []
    monkeypatch.setattr(rv_module.dialogues, "confirmer",
                        lambda *a, **k: (ordre.append("confidentialite"), True)[1])
    exec_initial = FauxDialogAssociation.exec
    monkeypatch.setattr(FauxDialogAssociation, "exec",
                        lambda self: (ordre.append("association"), exec_initial(self))[1])
    vue._generer_cr_mistral(md)
    assert ordre == ["association", "confidentialite"]
    assert g.lances == [md]


def test_confidentialite_refusee_apres_association_ne_lance_rien(qapp, machine, tmp_path,
                                                                 monkeypatch,
                                                                 faux_dialog_association):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    cfg = _config(tmp_path)
    g = FauxGestionnaireCRMistral()
    vue = ReunionView(cfg, machine, gestionnaire=FauxGestionnaire(),
                      store_bluemind=_store_correspondant(tmp_path), gestionnaire_cr_mistral=g)
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: False)
    vue._generer_cr_mistral(md)
    assert len(faux_dialog_association.instances) == 1   # l'association a bien été proposée
    assert g.lances == []


def test_cr_reentrance_bloquee_pendant_la_proposition(qapp, machine, tmp_path, monkeypatch,
                                                      faux_dialog_association):
    """Le dialogue (et l'attente de sync) laissent tourner l'event loop : un 2ᵉ clic ne
    doit pas rentrer une deuxième fois dans le flux."""
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path))
    imbrique = []

    def exec_qui_reclique(self):
        vue._generer_cr_mistral(md)               # simule le second clic
        imbrique.append(len(faux_dialog_association.instances))
        return self.DialogCode.Accepted

    monkeypatch.setattr(FauxDialogAssociation, "exec", exec_qui_reclique)
    vue._generer_cr_mistral(md)
    assert imbrique == [1]                        # aucun dialogue supplémentaire
    assert g.lances == [md]                       # un seul lancement


def test_cr_force_une_sync_avant_la_detection(qapp, machine, tmp_path, monkeypatch,
                                              faux_dialog_association):
    """La détection ne doit pas manquer un événement créé depuis la dernière synchro."""
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path),
                                   synchro=object())
    appels = []
    monkeypatch.setattr(rv_module, "attendre_sync",
                        lambda synchro, parent: (appels.append(synchro), True)[1])
    vue._generer_cr_mistral(md)
    assert len(appels) == 1
    assert g.lances == [md]


def test_pas_de_sync_si_reunion_deja_associee(qapp, machine, tmp_path, monkeypatch,
                                              faux_dialog_association):
    """Rien à proposer → aucune attente réseau imposée à l'utilisateur."""
    from debrief_meet.core.bluemind.association import Association, ecrire
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    ecrire(md, Association(event_uid="e1", cal_uid="cal", titre="T",
                           debut="2026-01-01T10:00:00", invites=[]))
    vue, g = _vue_cr_avec_bluemind(tmp_path, machine, store=_store_correspondant(tmp_path),
                                   synchro=object())
    appels = []
    monkeypatch.setattr(rv_module, "attendre_sync",
                        lambda synchro, parent: (appels.append(synchro), True)[1])
    vue._generer_cr_mistral(md)
    assert appels == []
    assert g.lances == [md]


# ── « Ouvrir le CR » (action présente seulement si le CR existe) ────────────────

def _action_par_tooltip(actions, tooltip):
    return next((a for a in actions if a.tooltip == tooltip), None)


def test_ouvrir_cr_absent_sans_fichier_cr(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert _action_par_tooltip(_actions(vue), "Ouvrir le CR") is None


def test_ouvrir_cr_present_et_ouvre_le_cr(qapp, machine, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    chemin_cr_mistral(md).write_text("# CR\n\nrésumé", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    action = _action_par_tooltip(_actions(vue), "Ouvrir le CR")
    assert action is not None and action.actif is True
    ouverts = []
    monkeypatch.setattr(vue, "_ouvrir", lambda c: ouverts.append(c))
    action.on_click()
    assert ouverts == [chemin_cr_mistral(md)]


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
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
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


def test_reunion_active_pas_de_ligne_en_double(qapp, machine, tmp_path):
    """Régression : pendant l'enregistrement, le `transcription.md` de la réunion
    active existe déjà sur disque — il ne doit PAS s'afficher en plus de la ligne
    « en cours » (doublon constaté en test manuel le 2026-07-27)."""
    active = _reunion_avec_audio(tmp_path, nom="2026-07-27_19-02-11")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert vue._modele.rowCount() == 1              # avant démarrage : ligne normale

    vue.definir_reunion_active(active)              # signal reunion_demarree
    vue.definir_etat_enregistrement(Mode.REUNION, 9)

    assert vue._modele.rowCount() == 1              # « en cours » seule, pas de doublon
    assert vue._modele.data(vue._modele.index(0, 1)) == "Réunion en cours"


def test_reunion_active_reapparait_a_l_arret(qapp, machine, tmp_path):
    active = _reunion_avec_audio(tmp_path, nom="2026-07-27_19-02-11")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    vue.definir_reunion_active(active)
    vue.definir_etat_enregistrement(Mode.REUNION, 9)
    assert vue._modele.rowCount() == 1

    # Fin d'enregistrement : `machine.mode_change` → IDLE remet l'état au repos.
    vue._sur_mode_change_surveillance(Mode.IDLE)
    vue.definir_etat_enregistrement(Mode.IDLE, 0)

    assert vue._modele.rowCount() == 1
    assert vue._modele.chemin_a_la_ligne(0) == active   # redevenue une ligne normale


def test_reunion_active_n_exclut_pas_les_autres(qapp, machine, tmp_path):
    autre = _reunion_avec_audio(tmp_path, nom="2026-07-26_10-00-00")
    active = _reunion_avec_audio(tmp_path, nom="2026-07-27_19-02-11")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())

    vue.definir_reunion_active(active)
    vue.definir_etat_enregistrement(Mode.REUNION, 9)

    # « en cours » + l'autre réunion (l'active est exclue, pas les voisines)
    assert vue._modele.rowCount() == 2
    assert vue._modele.chemin_a_la_ligne(1) == autre


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
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    debut = datetime(2026, 1, 1, 10, 0)
    _store_avec_evenement(tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())  # pas de store_bluemind
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_BLUEMIND_ASSOCIER not in icones


def test_action_associer_presente_si_correspondance(qapp, machine, tmp_path):
    from datetime import datetime
    nom = "2026-01-01_10-00-00"
    _reunion_avec_audio(tmp_path, nom=nom)
    debut = datetime(2026, 1, 1, 10, 0)
    store = _store_avec_evenement(tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    spec = _spec(_actions(vue), rv_module._ICONE_BLUEMIND_ASSOCIER)
    assert spec.actif is True


def test_colonne_calendrier_cliquable_tant_que_non_associee(qapp, machine, tmp_path):
    """Tant que la réunion n'est pas associée, l'icône calendrier reste un raccourci
    cliquable vers l'association — en plus de l'item du menu ⋯ (exhaustif)."""
    from datetime import datetime
    nom = "2026-01-01_10-00-00"
    _reunion_avec_audio(tmp_path, nom=nom)
    debut = datetime(2026, 1, 1, 10, 0)
    store = _store_avec_evenement(tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    index = vue._proxy.mapFromSource(vue._modele.index(0, 5))
    spec = vue._calendrier_pour_index(index)
    assert spec.icone == "calendar-plus"
    assert spec.cliquable is True
    assert spec.on_click is not None


def test_action_absente_sans_correspondance(qapp, machine, tmp_path):
    from datetime import datetime
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    debut = datetime(2026, 6, 1, 10, 0)  # loin de la réunion
    store = _store_avec_evenement(tmp_path, int(debut.timestamp() * 1000), int(debut.timestamp() * 1000) + 1800_000)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_BLUEMIND_ASSOCIER not in icones


def test_nommer_locuteurs_present_si_locuteurs_md(qapp, machine, tmp_path):
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    chemin_locuteurs(md).write_text("# X\n\n**Moi** [00:00] bonjour\n", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    spec = _spec(_actions(vue), rv_module._ICONE_NOMMER_LOCUTEURS)
    assert spec.actif is True


def test_nommer_locuteurs_absent_sans_locuteurs_md(qapp, machine, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_NOMMER_LOCUTEURS not in icones


def test_nommer_locuteurs_disponible_sans_store_bluemind(qapp, machine, tmp_path):
    """F2 n'est pas gatée par la config BlueMind (§7) — utilisable en saisie libre."""
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    chemin_locuteurs(md).write_text("# X\n\n**Moi** [00:00] bonjour\n", encoding="utf-8")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())  # store_bluemind=None
    icones = [a.icone for a in _actions(vue)]
    assert rv_module._ICONE_NOMMER_LOCUTEURS in icones


def test_action_indique_deja_associe(qapp, machine, tmp_path, monkeypatch):
    """Une fois associé, l'item du menu ⋯ reste présent et **actif** : il ouvre le
    détail de l'événement (même dialogue que l'icône verte de la colonne)."""
    from debrief_meet.core.bluemind.association import Association, ecrire
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    ecrire(md, Association(event_uid="e1", cal_uid="cal", titre="Point projet X",
                            debut="2026-01-01T10:00:00", invites=[]))
    store = _store_avec_evenement(tmp_path, 0, 1)  # peu importe, déjà associé
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    spec = _spec(_actions(vue), rv_module._ICONE_BLUEMIND_ASSOCIE)
    assert spec.actif is True
    assert "Point projet X" in spec.tooltip

    ouverts = []
    monkeypatch.setattr(vue, "_details_bluemind", lambda asso: ouverts.append(asso))
    spec.on_click()
    assert len(ouverts) == 1
    assert ouverts[0].titre == "Point projet X"


def test_colonne_calendrier_associee_cliquable_vers_le_detail(qapp, machine, tmp_path, monkeypatch):
    """L'icône verte « associé » n'est plus passive : cliquer ouvre le détail de
    l'événement (titre, date, participants retenus/écartés)."""
    from debrief_meet.core.bluemind.association import Association, InviteAssocie, ecrire
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    ecrire(md, Association(
        event_uid="e1", cal_uid="cal", titre="Point projet X", debut="2026-01-01T10:00:00",
        invites=[InviteAssocie(nom="Jean Dupont", email="jean@ex.com",
                               part_status="Accepted", organisateur=False, coche=True)]))
    store = _store_avec_evenement(tmp_path, 0, 1)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    index = vue._proxy.mapFromSource(vue._modele.index(0, 5))
    spec = vue._calendrier_pour_index(index)
    assert spec.icone == "calendar-check"
    assert spec.cliquable is True
    assert "voir le détail" in spec.tooltip

    ouverts = []
    monkeypatch.setattr(vue, "_details_bluemind", lambda asso: ouverts.append(asso))
    spec.on_click()
    assert [i.nom for i in ouverts[0].invites] == ["Jean Dupont"]


def test_colonne_calendrier_sidecar_illisible_reste_passive(qapp, machine, tmp_path):
    """Sidecar `bluemind.json` corrompu : la réunion reste « associée » (icône verte)
    mais il n'y a aucun détail à montrer — l'icône redevient passive."""
    from debrief_meet.core.bluemind.association import chemin_sidecar
    md = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    chemin_sidecar(md).write_text("{pas du json", encoding="utf-8")
    store = _store_avec_evenement(tmp_path, 0, 1)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire(), store_bluemind=store)
    index = vue._proxy.mapFromSource(vue._modele.index(0, 5))
    spec = vue._calendrier_pour_index(index)
    assert spec.icone == "calendar-check"
    assert spec.cliquable is False
    assert spec.on_click is None


# ── Actions en masse (§8.6.4) ────────────────────────────────────────────────

def test_bulk_bar_visible_a_partir_de_deux_lignes(qapp, machine, tmp_path):
    from PySide6.QtCore import QItemSelectionModel
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert vue._action_bar._bulk.isHidden()
    sm = vue._table.selectionModel()
    for r in range(2):
        sm.select(vue._proxy.index(r, 0),
                  QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    assert not vue._action_bar._bulk.isHidden()


def test_bulk_supprimer_efface_la_selection(qapp, machine, tmp_path, monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    a = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    b = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    sm = vue._table.selectionModel()
    for r in range(2):
        sm.select(vue._proxy.index(r, 0),
                  QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._action_bar.demande_supprimer_masse.emit()
    assert not a.exists() and not b.exists()
    assert vue._action_bar._bulk.isHidden()   # sélection vidée après recharge


def test_bulk_ignorer_audio_sur_selection(qapp, machine, tmp_path, monkeypatch):
    from PySide6.QtCore import QItemSelectionModel
    a = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00-00")
    b = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00-00")
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    sm = vue._table.selectionModel()
    for r in range(2):
        sm.select(vue._proxy.index(r, 0),
                  QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    monkeypatch.setattr(rv_module.dialogues, "confirmer", lambda *a, **k: True)
    vue._action_bar.demande_ignorer_audio_masse.emit()
    # audio supprimé, .md conservés
    assert a.exists() and b.exists()
    assert not a.with_name("moi.wav").exists()
    assert not b.with_name("moi.wav").exists()


# ── Mode distant (docs/45) ───────────────────────────────────────────────────

def _icones(actions) -> list[str]:
    return [a.icone for a in actions]


def test_distant_pas_d_action_locuteurs_sur_une_reunion_transcrite(
        qapp, machine, tmp_path, mode_distant):
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    assert "users" not in _icones(_actions(vue))


def test_distant_pas_d_action_transcrire_sur_une_reunion_en_attente(
        qapp, machine, tmp_path, mode_distant):
    """Sans ce gate, CHAQUE ligne afficherait une icône grisée « Moteur de
    transcription indisponible » : en distant toute réunion est « en attente » jusqu'à
    ce que Mistral écrive le transcript."""
    _reunion_en_attente(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    icones = _icones(_actions(vue))
    assert "text-aa" not in icones
    assert "users" not in icones


def test_distant_conserve_les_actions_communes(qapp, machine, tmp_path, mode_distant):
    """Le gate ne doit toucher que ces deux actions."""
    _reunion_avec_audio(tmp_path)
    vue = ReunionView(_config(tmp_path), machine, gestionnaire=FauxGestionnaire())
    icones = _icones(_actions(vue))
    for attendue in ("copy", "arrow-square-out", "folder", "microphone-slash", "trash"):
        assert attendue in icones, f"action commune perdue : {attendue}"
