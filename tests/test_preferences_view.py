"""Tests de PreferencesView (refonte design, autosave) — porte la couverture
comportementale clé de tests/test_preferences.py (FenetrePreferences) sur la
nouvelle vue. L'ancienne fenêtre n'est pas touchée ici (retirée à l'Étape 4).
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence

import debrief_meet.ui.preferences_view as pv_module
from debrief_meet.core.config import Config
from debrief_meet.ui.preferences_view import PreferencesView
from tests.fakes.adapters import MoteurFake


def _config(tmp_path):
    return Config(chemin=tmp_path / "config.json")


def _flush(vue: PreferencesView) -> None:
    """Force l'écriture disque des champs texte débounçés, sans dormir."""
    vue._timer_autosave.stop()
    vue._config.sauvegarder()


# ── Sections & navigation ────────────────────────────────────────────────────

def test_huit_sections(qapp, tmp_path):
    vue = PreferencesView(_config(tmp_path))
    assert vue._pages.count() == 8
    assert vue._nav.count() == 8


def test_navigation_change_la_page_active(qapp, tmp_path):
    vue = PreferencesView(_config(tmp_path))
    vue._nav.setCurrentRow(3)
    assert vue._pages.currentIndex() == 3


def test_barre_autosave_presente(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel
    vue = PreferencesView(_config(tmp_path))
    barres = [w for w in vue.findChildren(QLabel) if w.objectName() == "autosaveBar"]
    assert len(barres) == 1
    assert "automatiquement" in barres[0].text().lower()


# ── Autosave : chaque champ persiste sans bouton Appliquer ──────────────────────

def test_case_notifications_persiste_immediatement(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._check_notifs.setChecked(False)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("notifications") is False


def test_spin_intervalle_persiste_immediatement(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._spin_intervalle.setValue(99)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("intervalle_reunion") == 99


def test_case_aec_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._check_aec.setChecked(False)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("aec_actif") is False


def test_dossier_edite_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edit_dossier_reunions.setText(str(tmp_path / "ailleurs"))
    vue._edit_dossier_reunions.editingFinished.emit()
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("dossier_reunions") == str(tmp_path / "ailleurs")


# ── Raccourcis : validation en direct ────────────────────────────────────────

def test_raccourci_valide_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edit_raccourci_dictee.setKeySequence(QKeySequence.fromString("Ctrl+Alt+X"))
    assert cfg.get("raccourci_dictee") == "Ctrl+Alt+X"


def test_raccourci_doublon_refuse_et_revert(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pv_module.QMessageBox, "warning", lambda *a, **k: None)
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    valeur_avant = cfg.get("raccourci_dictee")
    vue._edit_raccourci_dictee.setKeySequence(
        QKeySequence.fromString(cfg.get("raccourci_reunion")))
    assert cfg.get("raccourci_dictee") == valeur_avant


def test_raccourci_sans_modificateur_refuse(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pv_module.QMessageBox, "warning", lambda *a, **k: None)
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    valeur_avant = cfg.get("raccourci_dictee")
    vue._edit_raccourci_dictee.setKeySequence(QKeySequence.fromString("D"))
    assert cfg.get("raccourci_dictee") == valeur_avant


def test_raccourci_vide_desactive(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edit_raccourci_dictee.setKeySequence(QKeySequence())
    assert cfg.get("raccourci_dictee") == ""


def test_reinitialiser_restaure_les_defauts(qapp, tmp_path):
    from debrief_meet.core.raccourcis import ACTIONS
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edit_raccourci_dictee.setKeySequence(QKeySequence.fromString("Ctrl+Alt+X"))
    vue._reinitialiser_raccourcis()
    defauts = {cle: defaut for cle, defaut, _n in ACTIONS}
    assert cfg.get("raccourci_dictee") == defauts["raccourci_dictee"]


def test_appliquer_avertit_si_raccourci_refuse(qapp, tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    appels = []
    monkeypatch.setattr(pv_module.QMessageBox, "warning", lambda *a, **k: appels.append(a))
    vue = PreferencesView(cfg, reappliquer_raccourcis=lambda: ["Ctrl+Alt+X"])
    vue._edit_raccourci_dictee.setKeySequence(QKeySequence.fromString("Ctrl+Alt+X"))
    assert appels


# ── Prompts ──────────────────────────────────────────────────────────────────

def test_onglet_prompts_charge_la_config(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P1", "contenu": "c1"}])
    cfg.set("prompt_actif", 0)
    vue = PreferencesView(cfg)
    assert vue._liste_prompts.count() == 1
    assert vue._check_prompt_actif.isChecked() is True


def test_ajouter_prompt_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("prompts", [])
    vue = PreferencesView(cfg)
    vue._prompt_ajouter()
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert len(relu.get("prompts")) == 1


def test_editer_titre_prompt_persiste_apres_flush(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "Ancien", "contenu": ""}])
    vue = PreferencesView(cfg)
    vue._liste_prompts.setCurrentRow(0)
    vue._edit_prompt_titre.setText("Nouveau")
    vue._prompt_titre_change("Nouveau")
    assert cfg.get("prompts")[0]["titre"] == "Nouveau"  # en mémoire, immédiat
    _flush(vue)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("prompts")[0]["titre"] == "Nouveau"


def test_supprimer_prompt_actif_le_desactive(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P1", "contenu": ""}])
    cfg.set("prompt_actif", 0)
    vue = PreferencesView(cfg)
    vue._prompt_supprimer()
    assert cfg.get("prompt_actif") is None


def test_toggle_prompt_actif_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("prompts", [{"titre": "P1", "contenu": ""}])
    cfg.set("prompt_actif", None)
    vue = PreferencesView(cfg)
    vue._liste_prompts.setCurrentRow(0)
    vue._check_prompt_actif.setChecked(True)
    assert cfg.get("prompt_actif") == 0


# ── Modèle ───────────────────────────────────────────────────────────────────

def test_changer_modele_sans_moteur_persiste_sans_recharger(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    idx = vue._combo_modele.findData("large-v3")
    vue._combo_modele.setCurrentIndex(idx)
    assert cfg.get("modele") == "large-v3"


def test_changer_modele_avec_moteur_declenche_le_dialogue(qapp, tmp_path, qtbot):
    cfg = _config(tmp_path)
    moteur = MoteurFake()
    vue = PreferencesView(cfg, moteur=moteur)
    idx = vue._combo_modele.findData("large-v3")
    vue._combo_modele.setCurrentIndex(idx)
    qtbot.waitUntil(lambda: vue._dlg_modele is not None, timeout=2000)
    qtbot.waitUntil(lambda: vue._thread_modele is not None and vue._thread_modele.isFinished(), timeout=5000)
    assert cfg.get("modele") == "large-v3"


# ── Journalisation ───────────────────────────────────────────────────────────

def test_case_debug_persiste(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._check_debug.setChecked(True)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("logs_debug") is True


# ── BlueMind (docs/40 §4) ────────────────────────────────────────────────────

def test_champs_bluemind_persistent(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edit_bm_url.setText("https://bm.exemple.com/api")
    vue._edit_bm_url.editingFinished.emit()
    vue._edit_bm_email.setText("sylvain@exemple.com")
    vue._edit_bm_email.editingFinished.emit()
    vue._edit_bm_token.setText("s3cr3t")
    vue._edit_bm_token.editingFinished.emit()
    vue._check_bm_tls.setChecked(False)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("bluemind_url") == "https://bm.exemple.com/api"
    assert relu.get("bluemind_email") == "sylvain@exemple.com"
    assert relu.get("bluemind_token") == "s3cr3t"
    assert relu.get("bluemind_verifier_tls") is False


def test_notifications_bluemind_persistent(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._check_bm_notif.setChecked(False)
    vue._spin_bm_avance.setValue(10)
    vue._check_bm_solo.setChecked(True)
    vue._check_bm_refuses.setChecked(True)
    vue._check_bm_journee.setChecked(True)
    relu = Config(chemin=tmp_path / "config.json")
    relu.charger()
    assert relu.get("bluemind_notif_reunions") is False
    assert relu.get("bluemind_notif_avance_min") == 10
    assert relu.get("bluemind_notif_inclure_solo") is True
    assert relu.get("bluemind_notif_inclure_refuses") is True
    assert relu.get("bluemind_notif_inclure_journee") is True


def test_changement_url_declenche_reset_sync(qapp, tmp_path):
    cfg = _config(tmp_path)
    appels = []
    vue = PreferencesView(cfg, bluemind_reinitialiser_sync=lambda: appels.append(1))
    vue._edit_bm_url.setText("https://bm.exemple.com/api")
    vue._edit_bm_url.editingFinished.emit()
    assert appels == [1]


def test_changement_email_declenche_reset_sync(qapp, tmp_path):
    cfg = _config(tmp_path)
    appels = []
    vue = PreferencesView(cfg, bluemind_reinitialiser_sync=lambda: appels.append(1))
    vue._edit_bm_email.setText("autre@exemple.com")
    vue._edit_bm_email.editingFinished.emit()
    assert appels == [1]


def test_changement_token_ne_declenche_pas_reset_sync(qapp, tmp_path):
    cfg = _config(tmp_path)
    appels = []
    vue = PreferencesView(cfg, bluemind_reinitialiser_sync=lambda: appels.append(1))
    vue._edit_bm_token.setText("nouvelle-cle")
    vue._edit_bm_token.editingFinished.emit()
    assert appels == []


def test_meme_valeur_url_ne_redeclenche_pas_reset(qapp, tmp_path):
    cfg = _config(tmp_path)
    cfg.set("bluemind_url", "https://bm.exemple.com/api")
    appels = []
    vue = PreferencesView(cfg, bluemind_reinitialiser_sync=lambda: appels.append(1))
    vue._edit_bm_url.setText("https://bm.exemple.com/api")
    vue._edit_bm_url.editingFinished.emit()
    assert appels == []


def test_bouton_reset_demande_confirmation(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    cfg = _config(tmp_path)
    appels = []
    vue = PreferencesView(cfg, bluemind_reinitialiser_sync=lambda: appels.append(1))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    vue._reinitialiser_sync_bluemind()
    assert appels == []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    vue._reinitialiser_sync_bluemind()
    assert appels == [1]


def test_tester_connexion_reussie(qapp, tmp_path, qtbot, respx_mock):
    import httpx
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edit_bm_url.setText("https://bm.exemple.com/api")
    vue._edit_bm_email.setText("sylvain@exemple.com")
    vue._edit_bm_token.setText("token")
    respx_mock.get("https://bm.exemple.com/api/users/exemple.com/byEmail/sylvain@exemple.com").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {"displayName": "Sylvain Garcia"}}))
    vue._tester_connexion_bluemind()
    qtbot.waitUntil(lambda: "Connecté" in vue._label_bm_statut.text(), timeout=3000)
    assert "Sylvain Garcia" in vue._label_bm_statut.text()


def test_tester_connexion_echec(qapp, tmp_path, qtbot, respx_mock):
    import httpx
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edit_bm_url.setText("https://bm.exemple.com/api")
    vue._edit_bm_email.setText("sylvain@exemple.com")
    vue._edit_bm_token.setText("mauvaise-cle")
    respx_mock.get("https://bm.exemple.com/api/users/exemple.com/byEmail/sylvain@exemple.com").mock(
        return_value=httpx.Response(401))
    respx_mock.post("https://bm.exemple.com/api/directory/exemple.com/_search").mock(
        return_value=httpx.Response(200, json={"values": []}))
    vue._tester_connexion_bluemind()
    qtbot.waitUntil(lambda: "Échec" in vue._label_bm_statut.text(), timeout=3000)


def test_tester_connexion_champs_vides_pas_de_reseau(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._tester_connexion_bluemind()
    assert vue._thread_test_bm is None
    assert "requis" in vue._label_bm_statut.text()
