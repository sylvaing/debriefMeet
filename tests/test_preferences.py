"""Tests des Préférences — focalisés sur le réglage AEC (Phase A, étape 2)."""
from __future__ import annotations

from PySide6.QtGui import QKeySequence

from debrief_meet.core.config import Config
from debrief_meet.ui.preferences import FenetrePreferences
from tests.fakes.adapters import MoteurFake


def _config(tmp_path, **kv):
    cfg = Config(chemin=tmp_path / "config.json")
    for k, v in kv.items():
        cfg.set(k, v)
    return cfg


def test_case_aec_reflete_la_config(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path, aec_actif=False))
    assert fen._check_aec.isChecked() is False
    fen2 = FenetrePreferences(_config(tmp_path, aec_actif=True))
    assert fen2._check_aec.isChecked() is True


def test_appliquer_enregistre_aec_actif(qapp, tmp_path):
    cfg = _config(tmp_path, aec_actif=True)
    fen = FenetrePreferences(cfg)
    fen._check_aec.setChecked(False)
    fen._appliquer()
    assert cfg.get("aec_actif") is False
    # persistance : relu depuis le disque (charger() explicite, comme l'app)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("aec_actif") is False


def test_case_retention_reflete_la_config(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path, retention_audio=False))
    assert fen._check_retention.isChecked() is False
    fen2 = FenetrePreferences(_config(tmp_path, retention_audio=True))
    assert fen2._check_retention.isChecked() is True


def test_appliquer_enregistre_retention_audio(qapp, tmp_path):
    cfg = _config(tmp_path, retention_audio=True)
    fen = FenetrePreferences(cfg)
    fen._check_retention.setChecked(False)
    fen._appliquer()
    assert cfg.get("retention_audio") is False
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("retention_audio") is False


def test_case_transcription_live_reflete_la_config(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path, transcription_live=False))
    assert fen._check_transcription_live.isChecked() is False
    fen2 = FenetrePreferences(_config(tmp_path, transcription_live=True))
    assert fen2._check_transcription_live.isChecked() is True


def test_appliquer_enregistre_transcription_live(qapp, tmp_path):
    cfg = _config(tmp_path, transcription_live=True)
    fen = FenetrePreferences(cfg)
    fen._check_transcription_live.setChecked(False)
    fen._appliquer()
    assert cfg.get("transcription_live") is False
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("transcription_live") is False


# ── Onglet Prompts (doc 12) ──────────────────────────────────────────────────

def test_onglet_prompts_charge_la_config(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path))
    assert fen._liste_prompts.count() == 1
    assert fen._prompts[0]["titre"] == "CR simple"
    assert fen._prompt_actif == 0


def test_ajouter_prompt(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path))
    n = fen._liste_prompts.count()
    fen._prompt_ajouter()
    assert fen._liste_prompts.count() == n + 1
    assert fen._prompts[-1]["titre"] == "Nouveau prompt"


def test_supprimer_prompt_actif_le_desactive(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path))
    fen._liste_prompts.setCurrentRow(0)        # CR simple, actif
    fen._prompt_supprimer()
    assert fen._prompt_actif is None
    assert fen._liste_prompts.count() == 0


def test_toggle_actif(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path))
    fen._prompt_ajouter()
    fen._liste_prompts.setCurrentRow(1)
    fen._check_prompt_actif.setChecked(True)    # toggled → _prompt_actif_toggle
    assert fen._prompt_actif == 1


def test_appliquer_enregistre_prompts(qapp, tmp_path):
    cfg = _config(tmp_path)
    fen = FenetrePreferences(cfg)
    fen._prompt_ajouter()
    row = fen._liste_prompts.currentRow()
    fen._prompts[row]["titre"] = "Mon prompt"
    fen._prompts[row]["contenu"] = "Contenu X"
    fen._appliquer()
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert "Mon prompt" in [p["titre"] for p in relu.get("prompts")]
    assert any(p["contenu"] == "Contenu X" for p in relu.get("prompts"))


# ── Changement de modèle à chaud (téléchargement + rechargement, docs/15) ───────

def test_recharger_modele_defaut_recharge():
    """Le défaut d'interface (terminer + charger) suffit à basculer un MoteurFake."""
    m = MoteurFake()
    m.recharger_modele("medium")
    assert m.modele_charge == "medium"


def test_appliquer_modele_inchange_ne_recharge_pas(qapp, tmp_path):
    m = MoteurFake()
    fen = FenetrePreferences(_config(tmp_path, modele="large-v3"), moteur=m)
    fen._appliquer()                              # modèle inchangé
    assert fen._chargeur is None                  # aucun rechargement déclenché


def test_appliquer_modele_change_telecharge_et_recharge(qapp, qtbot, tmp_path):
    m = MoteurFake()                              # "medium" pas dans modeles_telecharges → DL
    fen = FenetrePreferences(_config(tmp_path, modele="large-v3"), moteur=m)
    fen._combo_modele.setCurrentIndex(fen._combo_modele.findData("medium"))
    fen._appliquer()
    assert fen._chargeur is not None
    # Attendre la fin réelle du thread : pompe les événements (livre le quit en attente)
    # et garantit qu'aucun thread ne tourne encore au teardown.
    qtbot.waitUntil(lambda: not fen._thread_modele.isRunning(), timeout=5000)
    assert m.modele_charge == "medium"            # rechargé à chaud
    assert "medium" in m.modeles_telecharges      # téléchargé car absent du cache


# ── Journalisation : logs à chaud + mode debug (docs/27 correctif 3) ───────────

def test_case_debug_reflete_la_config(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path, logs_debug=True))
    assert fen._check_debug.isChecked() is True
    fen2 = FenetrePreferences(_config(tmp_path, logs_debug=False))
    assert fen2._check_debug.isChecked() is False


def test_appliquer_logs_appelle_configurer_logs_a_chaud(qapp, tmp_path, monkeypatch):
    """La sauvegarde des Préférences reconfigure les logs immédiatement, sans
    redémarrer l'app (le bug qui a rendu le diagnostic du 2026-07-02 impossible)."""
    import debrief_meet.ui.preferences as prefs_module

    appels = []
    monkeypatch.setattr(prefs_module, "configurer_logs",
                        lambda actifs, debug: appels.append((actifs, debug)))

    cfg = _config(tmp_path, logs_actifs=False, logs_debug=False)
    fen = FenetrePreferences(cfg)
    fen._check_logs.setChecked(True)
    fen._check_debug.setChecked(True)
    fen._appliquer()

    assert appels == [(True, True)]
    assert cfg.get("logs_actifs") is True
    assert cfg.get("logs_debug") is True


# ── Onglet Raccourcis (docs/28) ─────────────────────────────────────────────

def test_raccourcis_charges_depuis_la_config(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path, raccourci_dictee="Ctrl+Alt+F"))
    texte = fen._edit_raccourci_dictee.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
    assert texte == "Ctrl+Alt+F"


def test_valider_raccourcis_refuse_doublon_entre_deux_champs(qapp, tmp_path, monkeypatch):
    avertissements = []
    monkeypatch.setattr("debrief_meet.ui.preferences.QMessageBox.warning",
                        lambda *a, **k: avertissements.append(a) or None)
    fen = FenetrePreferences(_config(tmp_path))
    fen._edit_raccourci_dictee.setKeySequence(QKeySequence("Ctrl+Alt+Meta+D"))
    fen._edit_raccourci_reunion.setKeySequence(QKeySequence("Ctrl+Alt+Meta+D"))
    assert fen._valider_raccourcis() is None
    assert avertissements


def test_valider_raccourcis_refuse_combinaison_sans_modificateur(qapp, tmp_path, monkeypatch):
    avertissements = []
    monkeypatch.setattr("debrief_meet.ui.preferences.QMessageBox.warning",
                        lambda *a, **k: avertissements.append(a) or None)
    fen = FenetrePreferences(_config(tmp_path))
    fen._edit_raccourci_dictee.setKeySequence(QKeySequence("D"))
    assert fen._valider_raccourcis() is None
    assert avertissements


def test_valider_raccourcis_champ_vide_accepte(qapp, tmp_path):
    fen = FenetrePreferences(_config(tmp_path))
    fen._edit_raccourci_journal.setKeySequence(QKeySequence())
    resultat = fen._valider_raccourcis()
    assert resultat is not None
    assert resultat["raccourci_journal"] == ""


def test_appliquer_enregistre_raccourci_vide(qapp, tmp_path):
    cfg = _config(tmp_path)
    fen = FenetrePreferences(cfg)
    fen._edit_raccourci_journal.setKeySequence(QKeySequence())
    fen._appliquer()
    assert cfg.get("raccourci_journal") == ""


def test_appliquer_appelle_reappliquer_raccourcis(qapp, tmp_path):
    appels = []
    fen = FenetrePreferences(_config(tmp_path), reappliquer_raccourcis=lambda: appels.append(1) or [])
    fen._appliquer()
    assert appels == [1]


def test_appliquer_avertit_si_raccourci_refuse(qapp, tmp_path, monkeypatch):
    avertissements = []
    monkeypatch.setattr("debrief_meet.ui.preferences.QMessageBox.warning",
                        lambda *a, **k: avertissements.append(a) or None)
    fen = FenetrePreferences(_config(tmp_path),
                            reappliquer_raccourcis=lambda: ["Meta+Alt+Ctrl+D"])
    fen._appliquer()
    assert avertissements
