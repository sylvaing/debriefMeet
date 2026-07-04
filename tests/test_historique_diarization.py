"""Tests UI — Historique refondu + GestionnaireDiarization.

Fakes injectés : aucun pyannote/mlx réel. Le `GestionnaireDiarization` utilise un vrai
QThread mais avec des fakes instantanés (qtbot.waitSignal). Les tests de la fenêtre
emploient un `FauxGestionnaire` synchrone pour éviter tout thread. Fixture `qapp`/`qtbot`.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QMessageBox, QToolButton
from scipy.io import wavfile

from debrief_meet.core import diarization
from debrief_meet.core.config import Config
from debrief_meet.core.fichiers import chemin_locuteurs
from debrief_meet.platform.interfaces import ResultatTranscription, Segment
from debrief_meet.ui import historique as hist
from debrief_meet.ui.gestionnaire_diarization import (
    GestionnaireDiarization,
    _WorkerDiarization,
)
from debrief_meet.ui.historique import FenetreHistorique


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FauxMoteur:
    def transcrire(self, audio, langue=None):
        return ResultatTranscription("bonjour", "fr", [Segment(0.0, 1.0, "bonjour")])

    def terminer(self) -> None:
        pass


class FauxDiar(diarization.MoteurDiarization):
    def diariser(self, audio_16k):
        return [(0.0, 1.0, "SPK0")]


class FauxGestionnaire(QObject):
    """Gestionnaire synchrone pour tester la fenêtre sans thread."""
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


def _boutons(fen, liste, ligne_index=0):
    """QToolButtons de la colonne d'actions d'une ligne, dans l'ordre d'affichage."""
    item = liste.item(ligne_index)
    widget = liste.itemWidget(item)
    return widget.findChildren(QToolButton)


# ── _WorkerDiarization (appelé en direct) ──────────────────────────────────────

def test_worker_emet_terminee(tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    monkeypatch.setattr(diarization, "DiarizationPyannote", FauxDiar)
    recu = []
    worker = _WorkerDiarization(md, FauxMoteur(), langue="fr")
    worker.terminee.connect(lambda p: recu.append(p))
    worker.executer()
    assert len(recu) == 1
    assert recu[0].name == "2026-01-01_10-00_locuteurs.md"
    assert recu[0].exists()


def test_worker_emet_erreur_sans_audio(tmp_path, monkeypatch):
    md = tmp_path / "vide.md"
    md.write_text("#", encoding="utf-8")
    monkeypatch.setattr(diarization, "DiarizationPyannote", FauxDiar)
    erreurs = []
    worker = _WorkerDiarization(md, FauxMoteur(), langue=None)
    worker.erreur.connect(lambda m: erreurs.append(m))
    worker.executer()
    assert len(erreurs) == 1


# ── GestionnaireDiarization (thread réel, fakes instantanés) ────────────────────

def test_gestionnaire_indisponible_sans_moteur(qapp, tmp_path):
    g = GestionnaireDiarization(None, _config(tmp_path))
    assert g.disponible() is False
    assert g.lancer(tmp_path / "x.md") is False


def test_gestionnaire_lance_et_termine(qapp, qtbot, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    monkeypatch.setattr(diarization, "DiarizationPyannote", FauxDiar)
    g = GestionnaireDiarization(FauxMoteur(), _config(tmp_path))

    with qtbot.waitSignal(g.termine, timeout=5000) as bloc:
        assert g.lancer(md) is True
        assert g.job_en_cours() == md          # job marqué pendant l'exécution
    md_recu, sortie = bloc.args
    assert md_recu == md
    assert sortie.name == "2026-01-01_10-00_locuteurs.md"
    assert g.job_en_cours() is None            # libéré à la fin
    assert g.dernier_termine() == md
    # `termine` est émis AVANT que le QThread ne soit réellement fini (quit() est
    # asynchrone) : attendre sa fin effective, sinon `g` (local) est détruit par le
    # GC pendant que le thread s'éteint → access violation sur Windows (VM).
    qtbot.waitUntil(lambda: g._thread is not None and g._thread.isFinished(), timeout=5000)


def test_diarization_prete_exige_moteur_et_modele(qapp, tmp_path, monkeypatch):
    from debrief_meet.core import diarization
    g = GestionnaireDiarization(FauxMoteur(), _config(tmp_path))
    monkeypatch.setattr(diarization, "configuree", lambda: True)
    assert g.diarization_prete() is True
    monkeypatch.setattr(diarization, "configuree", lambda: False)   # modèle non téléchargé
    assert g.diarization_prete() is False


def test_diarization_prete_faux_sans_moteur(qapp, tmp_path):
    g = GestionnaireDiarization(None, _config(tmp_path))
    assert g.diarization_prete() is False


def test_gestionnaire_un_seul_job(qapp, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    monkeypatch.setattr(diarization, "DiarizationPyannote", FauxDiar)
    g = GestionnaireDiarization(FauxMoteur(), _config(tmp_path))
    assert g.lancer(md) is True
    assert g.lancer(md) is False               # refuse tant que le 1er tourne
    g.terminer()


# ── Fenêtre : colonne d'actions + grisage ───────────────────────────────────────

def test_listing_exclut_locuteurs(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)
    chemin_locuteurs(tmp_path / "2026-01-01_10-00.md").write_text("loc")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    assert fen._liste_reunions.count() == 1     # le _locuteurs n'apparaît pas


def test_generer_grise_si_locuteurs_existent(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)
    chemin_locuteurs(tmp_path / "2026-01-01_10-00.md").write_text("loc")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    btns = _boutons(fen, fen._liste_reunions)
    # ordre réunion : [copier, generer, ouvrir, reveler, suppr_audio, tout_suppr]
    assert btns[1].isEnabled() is False         # #2 grisé (déjà générés)


def test_generer_grise_sans_audio(qapp, tmp_path):
    md = tmp_path / "2026-01-01_10-00.md"
    md.write_text("#", encoding="utf-8")         # pas d'audio
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    btns = _boutons(fen, fen._liste_reunions)
    assert btns[1].isEnabled() is False          # #2 grisé (pas d'audio)
    assert btns[4].isEnabled() is False          # #5 supprimer audio grisé aussi


def test_generer_actif_avec_audio_sans_locuteurs(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    btns = _boutons(fen, fen._liste_reunions)
    assert btns[1].isEnabled() is True
    assert btns[4].isEnabled() is True           # audio présent → suppr audio actif


def test_diarization_grise_si_non_configuree(qapp, tmp_path):
    """Modèle pyannote non téléchargé → bouton diarization grisé + tooltip dédié (docs/13)."""
    _reunion_avec_audio(tmp_path)
    fen = FenetreHistorique(_config(tmp_path),
                            gestionnaire=FauxGestionnaire(diar_prete=False))
    btns = _boutons(fen, fen._liste_reunions)
    assert btns[1].isEnabled() is False
    assert "non configurée" in btns[1].toolTip().lower()


def test_transcription_non_affectee_par_diarization_non_configuree(qapp, tmp_path):
    """La transcription différée ne dépend QUE du moteur, pas du modèle pyannote."""
    _reunion_en_attente(tmp_path)
    fen = FenetreHistorique(_config(tmp_path),
                            gestionnaire=FauxGestionnaire(diar_prete=False))
    btns = _boutons(fen, fen._liste_reunions)
    assert btns[1].isEnabled() is True              # bouton « Transcrire » actif quand même
    assert "transcrire" in btns[1].toolTip().lower()


def test_generer_refuse_si_non_configuree(qapp, tmp_path):
    """_generer ne lance rien si la diarization n'est pas prête (garde-fou)."""
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaire(diar_prete=False)
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=g)
    fen._generer(md)
    assert g.lances == []


def test_journal_colonne_reduite(qapp, tmp_path):
    (tmp_path / "2026-02-02.md").write_text("note")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    btns = _boutons(fen, fen._liste_journal)
    # journal = [copier, ouvrir, reveler, tout_supprimer] → 4 boutons
    assert len(btns) == 4


def test_ligne_en_cours_affiche_wip(qapp, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire(job=md))
    btns = _boutons(fen, fen._liste_reunions)
    assert btns[1].isEnabled() is False          # WIP : non cliquable
    assert "cours" in btns[1].toolTip().lower()


# ── _generer délègue au gestionnaire ────────────────────────────────────────────

def test_generer_delegue_au_gestionnaire(qapp, tmp_path):
    md = _reunion_avec_audio(tmp_path)
    g = FauxGestionnaire()
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=g)
    fen._generer(md)
    assert g.lances == [md]


def test_generer_sans_audio_affiche_message(qapp, tmp_path, monkeypatch):
    md = tmp_path / "2026-01-01_10-00.md"
    md.write_text("#", encoding="utf-8")
    g = FauxGestionnaire()
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=g)
    appels = []
    monkeypatch.setattr(hist.QMessageBox, "information", lambda *a, **k: appels.append(a))
    fen._generer(md)
    assert appels                                # message affiché
    assert g.lances == []                        # aucun job lancé


# ── Suppressions ────────────────────────────────────────────────────────────────

def test_supprimer_audio_retire_les_pistes(qapp, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(hist.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    fen._supprimer_audio(fen._liste_reunions, md)
    assert not (tmp_path / "2026-01-01_10-00_moi.wav").exists()
    assert not (tmp_path / "2026-01-01_10-00_systeme.wav").exists()
    assert md.exists()                           # le débrief reste


def test_tout_supprimer_retire_md_locuteurs_audio(qapp, tmp_path, monkeypatch):
    md = _reunion_avec_audio(tmp_path)
    loc = chemin_locuteurs(md)
    loc.write_text("loc")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    monkeypatch.setattr(hist.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    fen._tout_supprimer(fen._liste_reunions, md)
    assert not md.exists()
    assert not loc.exists()
    assert not (tmp_path / "2026-01-01_10-00_moi.wav").exists()


def test_suppression_de_masse_sur_selection(qapp, tmp_path, monkeypatch):
    a = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    b = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    fen._liste_reunions.selectAll()              # 2 lignes sélectionnées
    monkeypatch.setattr(hist.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    # clic #6 sur une ligne incluse dans la sélection → toute la sélection
    fen._tout_supprimer(fen._liste_reunions, a)
    assert not a.exists() and not b.exists()


# ── Sélection programmatique (clic notification) ────────────────────────────────

def test_selectionner_reunion_cible_la_bonne_ligne(qapp, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    cible = _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    fen.selectionner_reunion(cible)
    assert fen._chemins_selectionnes(fen._liste_reunions) == [cible]


# ── Rafraîchissement live ────────────────────────────────────────────────────────

def test_refresh_preserve_selection(qapp, tmp_path):
    a = _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    fen._liste_reunions.item(0).setSelected(True)
    fen._charger_liste(fen._liste_reunions, est_reunion=True)   # rechargement
    assert fen._chemins_selectionnes(fen._liste_reunions) == [a]


def test_refresh_voit_nouvelle_reunion(qapp, tmp_path):
    _reunion_avec_audio(tmp_path, nom="2026-01-01_10-00")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    assert fen._liste_reunions.count() == 1
    _reunion_avec_audio(tmp_path, nom="2026-01-02_11-00")        # nouvelle réunion
    fen._recharger_tout()
    assert fen._liste_reunions.count() == 2


# ── Transcription différée (mode audio seul, docs/10) ───────────────────────────

def _reunion_en_attente(tmp_path, nom="2026-03-03_09-00", avec_audio=True):
    """Réunion « audio seul » : placeholder marqué + pistes audio."""
    from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion — {nom}\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    if avec_audio:
        n = 16000
        wavfile.write(tmp_path / f"{nom}_moi.wav", 16000, np.zeros(n, dtype=np.int16))
        wavfile.write(tmp_path / f"{nom}_systeme.wav", 16000, np.zeros(n, dtype=np.int16))
    return md


def test_bouton_transcrire_present_si_en_attente(qapp, tmp_path):
    _reunion_en_attente(tmp_path)
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    btns = _boutons(fen, fen._liste_reunions)
    # #2 est le bouton « Transcrire » (et non « Générer les locuteurs »).
    assert btns[1].isEnabled() is True
    assert "transcrire" in btns[1].toolTip().lower()


def test_bouton_transcrire_grise_sans_audio(qapp, tmp_path):
    _reunion_en_attente(tmp_path, avec_audio=False)
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    btns = _boutons(fen, fen._liste_reunions)
    assert btns[1].isEnabled() is False
    assert "aucun audio" in btns[1].toolTip().lower()


def test_reunion_transcrite_montre_diarization_pas_transcrire(qapp, tmp_path):
    _reunion_avec_audio(tmp_path)   # .md "# brouillon" (pas en attente)
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    btns = _boutons(fen, fen._liste_reunions)
    assert "locuteurs" in btns[1].toolTip().lower()   # bouton diarization, pas transcrire


def test_transcrire_delegue_au_gestionnaire(qapp, tmp_path):
    md = _reunion_en_attente(tmp_path)
    g = FauxGestionnaire()
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=g)
    fen._transcrire(md)
    assert g.lances_transcription == [md]


def test_transcrire_sans_audio_affiche_message(qapp, tmp_path, monkeypatch):
    md = _reunion_en_attente(tmp_path, avec_audio=False)
    g = FauxGestionnaire()
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=g)
    appels = []
    monkeypatch.setattr(hist.QMessageBox, "information", lambda *a, **k: appels.append(a))
    fen._transcrire(md)
    assert appels
    assert g.lances_transcription == []


def test_gestionnaire_lance_transcription(qapp, qtbot, tmp_path):
    md = _reunion_en_attente(tmp_path)
    g = GestionnaireDiarization(FauxMoteur(), _config(tmp_path))

    with qtbot.waitSignal(g.termine, timeout=5000) as bloc:
        assert g.lancer_transcription(md) is True
        assert g.type_job_en_cours() == "transcription"
    md_recu, sortie = bloc.args
    assert md_recu == md
    contenu = md.read_text(encoding="utf-8")
    assert "bonjour" in contenu                      # transcription écrite
    assert "non générée" not in contenu              # placeholder remplacé
    assert g.job_en_cours() is None
    # Cf. test_gestionnaire_lance_et_termine : attendre la fin réelle du QThread.
    qtbot.waitUntil(lambda: g._thread is not None and g._thread.isFinished(), timeout=5000)


# ── Spinner animé du bouton « en cours » (doc 11) ───────────────────────────────

def test_bouton_en_cours_diarization_est_anime(qapp, tmp_path):
    from PySide6.QtCore import QTimer
    md = _reunion_avec_audio(tmp_path)
    fen = FenetreHistorique(_config(tmp_path),
                            gestionnaire=FauxGestionnaire(job=md, type_job="diarization"))
    btns = _boutons(fen, fen._liste_reunions)
    wip = btns[1]
    assert wip.isEnabled() is False
    assert "cours" in wip.toolTip().lower()
    timer = wip.findChild(QTimer)            # animation installée
    assert timer is not None
    assert timer.isActive()


def test_bouton_en_cours_transcription_est_anime(qapp, tmp_path):
    from PySide6.QtCore import QTimer
    md = _reunion_en_attente(tmp_path)
    fen = FenetreHistorique(_config(tmp_path),
                            gestionnaire=FauxGestionnaire(job=md, type_job="transcription"))
    btns = _boutons(fen, fen._liste_reunions)
    wip = btns[1]
    assert wip.isEnabled() is False
    assert "transcription en cours" in wip.toolTip().lower()
    timer = wip.findChild(QTimer)
    assert timer is not None and timer.isActive()


def test_bouton_anime_change_d_icone_au_tick(qapp, qtbot, tmp_path):
    """L'icône est régénérée par le timer (rotation) → le spinner « tourne »."""
    md = _reunion_avec_audio(tmp_path)
    fen = FenetreHistorique(_config(tmp_path),
                            gestionnaire=FauxGestionnaire(job=md, type_job="diarization"))
    wip = _boutons(fen, fen._liste_reunions)[1]
    avant = wip.icon().cacheKey()
    qtbot.wait(120)                          # laisse passer au moins un tick (80 ms)
    assert wip.icon().cacheKey() != avant


# ── Copie avec prompt actif (doc 12) ────────────────────────────────────────────

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
    fen = FenetreHistorique(cfg, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    fen._copier(md, est_reunion=True)
    assert pp.dernier.startswith("Fais un CR.\n\n")
    assert "ligne de transcription" in pp.dernier


def test_copier_sans_prompt_actif_reste_brut(qapp, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    cfg = _config(tmp_path)
    cfg.set("prompt_actif", None)
    pp = PressePapiersFake()
    fen = FenetreHistorique(cfg, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    fen._copier(md, est_reunion=True)
    assert pp.dernier == md.read_text(encoding="utf-8")


def test_copier_diarization_prefixe_aussi(qapp, tmp_path):
    from tests.fakes.adapters import PressePapiersFake
    md = _md_simple(tmp_path)
    chemin_locuteurs(md).write_text("# Locuteurs\n\nMoi : salut", encoding="utf-8")
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P", "contenu": "Résume."}])
    cfg.set("prompt_actif", 0)
    pp = PressePapiersFake()
    fen = FenetreHistorique(cfg, presse_papiers=pp, gestionnaire=FauxGestionnaire())
    fen._copier(md, est_reunion=True)
    assert pp.dernier.startswith("Résume.\n\n")
    assert "Moi : salut" in pp.dernier        # c'est bien le débrief locuteurs qui est copié


# ── Titre éditable + durée dans la ligne (docs/14) ──────────────────────────────

def _md_reunion(tmp_path, nom, contenu):
    md = tmp_path / f"{nom}.md"
    md.write_text(contenu, encoding="utf-8")
    return md


def _champ_titre(fen, liste, i=0):
    w = liste.itemWidget(liste.item(i))
    return w.findChild(hist._ChampTitre)


def test_titre_custom_affiche(qapp, tmp_path):
    _md_reunion(tmp_path, "2026-06-29_10-02", "# Budget Q3\n\ncorps")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    assert _champ_titre(fen, fen._liste_reunions)._label.text() == "Budget Q3"


def test_sans_titre_affiche_date_heure(qapp, tmp_path):
    _md_reunion(tmp_path, "2026-06-29_10-02", "# Réunion — 2026-06-29 10:02\n\ncorps")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    assert _champ_titre(fen, fen._liste_reunions)._label.text() == "29/06/2026 10:02"


def test_duree_affichee_dans_la_ligne(qapp, tmp_path):
    _md_reunion(tmp_path, "2026-06-29_10-02",
                "# Réunion — 2026-06-29 10:02\n<!-- duree_s: 1920 -->\n\ncorps")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    w = fen._liste_reunions.itemWidget(fen._liste_reunions.item(0))
    textes = [lab.text() for lab in w.findChildren(QLabel)]
    assert any("32 min" in t for t in textes)      # 1920 s = 32 min


def test_renommer_ecrit_le_titre(qapp, tmp_path):
    from debrief_meet.core.fichiers import titre_reunion
    md = _md_reunion(tmp_path, "2026-06-29_10-02", "# Réunion — 2026-06-29 10:02\n\ncorps")
    fen = FenetreHistorique(_config(tmp_path), gestionnaire=FauxGestionnaire())
    fen._renommer(md, "Budget Q3")
    assert titre_reunion(md) == "Budget Q3"


def test_champ_titre_commit_appelle_callback(qapp):
    recu = []
    champ = hist._ChampTitre("Affiché", "ancien", on_commit=recu.append)
    champ._editer()
    champ._edit.setText("nouveau")
    champ._valider()
    assert recu == ["nouveau"]


def test_champ_titre_sans_changement_ne_commit_pas(qapp):
    recu = []
    champ = hist._ChampTitre("Affiché", "ancien", on_commit=recu.append)
    champ._editer()
    champ._valider()                               # texte inchangé
    assert recu == []


def test_champ_titre_annule_ne_commit_pas(qapp):
    recu = []
    champ = hist._ChampTitre("Affiché", "ancien", on_commit=recu.append)
    champ._editer()
    champ._edit.setText("nouveau")
    champ._annuler()                               # Échap
    assert recu == []
