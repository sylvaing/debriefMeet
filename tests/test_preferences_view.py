"""Tests de PreferencesView (refonte design, autosave) — porte la couverture
comportementale clé de tests/test_preferences.py (FenetrePreferences) sur la
nouvelle vue. L'ancienne fenêtre n'est pas touchée ici (retirée à l'Étape 4).
"""
from __future__ import annotations

import pytest

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

def test_neuf_sections(qapp, tmp_path):
    """8 sections historiques + « Remote IA » (interco Mistral, docs/42 §9.1)."""
    vue = PreferencesView(_config(tmp_path))
    assert vue._pages.count() == 9
    assert vue._nav.count() == 9


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
    vue._edits_raccourcis["raccourci_dictee"].setKeySequence(QKeySequence.fromString("Ctrl+Alt+X"))
    assert cfg.get("raccourci_dictee") == "Ctrl+Alt+X"


def test_raccourci_doublon_refuse_et_revert(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pv_module.dialogues, "avertir", lambda *a, **k: None)
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    valeur_avant = cfg.get("raccourci_dictee")
    vue._edits_raccourcis["raccourci_dictee"].setKeySequence(
        QKeySequence.fromString(cfg.get("raccourci_reunion")))
    assert cfg.get("raccourci_dictee") == valeur_avant


def test_raccourci_sans_modificateur_refuse(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(pv_module.dialogues, "avertir", lambda *a, **k: None)
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    valeur_avant = cfg.get("raccourci_dictee")
    vue._edits_raccourcis["raccourci_dictee"].setKeySequence(QKeySequence.fromString("D"))
    assert cfg.get("raccourci_dictee") == valeur_avant


def test_raccourci_vide_desactive(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edits_raccourcis["raccourci_dictee"].setKeySequence(QKeySequence())
    assert cfg.get("raccourci_dictee") == ""


def test_reinitialiser_restaure_les_defauts(qapp, tmp_path):
    from debrief_meet.core.raccourcis import ACTIONS
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    vue._edits_raccourcis["raccourci_dictee"].setKeySequence(QKeySequence.fromString("Ctrl+Alt+X"))
    vue._reinitialiser_raccourcis()
    defauts = {cle: defaut for cle, defaut, _n in ACTIONS}
    assert cfg.get("raccourci_dictee") == defauts["raccourci_dictee"]


def test_appliquer_avertit_si_raccourci_refuse(qapp, tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    appels = []
    monkeypatch.setattr(pv_module.dialogues, "avertir", lambda *a, **k: appels.append(a))
    vue = PreferencesView(cfg, reappliquer_raccourcis=lambda: ["Ctrl+Alt+X"])
    vue._edits_raccourcis["raccourci_dictee"].setKeySequence(QKeySequence.fromString("Ctrl+Alt+X"))
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
    cfg = _config(tmp_path)
    appels = []
    vue = PreferencesView(cfg, bluemind_reinitialiser_sync=lambda: appels.append(1))
    monkeypatch.setattr(pv_module.dialogues, "confirmer", lambda *a, **k: False)
    vue._reinitialiser_sync_bluemind()
    assert appels == []
    monkeypatch.setattr(pv_module.dialogues, "confirmer", lambda *a, **k: True)
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


# ── Journalisation : export des logs (docs/44) ───────────────────────────────

def _boutons_logs(vue) -> list[str]:
    from PySide6.QtWidgets import QPushButton
    page = vue._pages.widget(vue._nav.count() - 1).widget()   # dernière section
    return [b.text() for b in page.findChildren(QPushButton)]


def test_section_logs_a_les_trois_boutons(qapp, tmp_path):
    vue = PreferencesView(_config(tmp_path))
    assert _boutons_logs(vue) == [
        "Ouvrir le fichier de log", "Exporter les logs (.zip)…", "Vider le log"]


def test_emplacement_des_logs_resolu_et_pas_code_en_dur(qapp, tmp_path):
    """`~/Library/Logs/debriefMeet/` était affiché en dur — faux sur Windows."""
    from PySide6.QtWidgets import QLabel
    from debrief_meet.core.logs import chemin_log

    vue = PreferencesView(_config(tmp_path))
    page = vue._pages.widget(vue._nav.count() - 1).widget()
    textes = "\n".join(l.text() for l in page.findChildren(QLabel))
    assert str(chemin_log().parent) in textes
    assert "~/Library/Logs" not in textes


def test_bouton_export_delegue_au_helper_partage(qapp, tmp_path, monkeypatch):
    appels = []
    monkeypatch.setattr("debrief_meet.ui.export_diagnostic.exporter_et_informer",
                        lambda parent: appels.append(parent))
    vue = PreferencesView(_config(tmp_path))
    vue._btn_exporter_logs.click()
    assert appels == [vue]


# ── Mode distant (docs/45) ───────────────────────────────────────────────────

def _titres_sections(vue) -> list[str]:
    return [vue._nav.item(i).text() for i in range(vue._nav.count())]


def test_distant_pas_de_section_modele(qapp, tmp_path, mode_distant):
    vue = PreferencesView(_config(tmp_path))
    titres = _titres_sections(vue)
    assert "Modèle" not in titres
    assert "Remote IA" in titres          # c'est elle qui porte la transcription en distant
    assert vue._pages.count() == vue._nav.count() == len(titres)


def test_sections_derivees_et_index_alignes(qapp, tmp_path):
    """Nav et pile remplies dans la même boucle : plus de tuples parallèles."""
    vue = PreferencesView(_config(tmp_path))
    assert vue._pages.count() == vue._nav.count() == len(vue._sections())
    vue._nav.setCurrentRow(vue._nav.count() - 1)
    assert vue._pages.currentIndex() == vue._nav.count() - 1


def test_distant_audio_sans_case_menteuse(qapp, tmp_path, mode_distant):
    """`transcription_live` et `retention_audio` sont forcés par l'orchestrateur en
    distant : afficher les cases serait un contrôle qui ment."""
    vue = PreferencesView(_config(tmp_path))
    assert not hasattr(vue, "_check_transcription_live")
    assert not hasattr(vue, "_check_retention")
    assert vue._check_aec is not None      # l'AEC reste (décision docs/44)


def test_distant_audio_explique_la_retention_obligatoire(qapp, tmp_path, mode_distant):
    from PySide6.QtWidgets import QLabel
    vue = PreferencesView(_config(tmp_path))
    page = vue._pages.widget(_titres_sections(vue).index("Audio")).widget()
    textes = "\n".join(l.text() for l in page.findChildren(QLabel))
    assert "toujours conservé" in textes


def test_distant_un_seul_editeur_de_raccourci(qapp, tmp_path, mode_distant):
    """`_reinitialiser_raccourcis` indexait un dict de 3 éditeurs codé en dur →
    KeyError en mode distant."""
    vue = PreferencesView(_config(tmp_path))
    assert list(vue._edits_raccourcis) == ["raccourci_reunion"]
    vue._reinitialiser_raccourcis()       # ne doit pas lever


# ── Sélecteur de micro : libellés distinguables (docs/44 §8.7) ────────────────

def test_selecteur_micro_distingue_les_api_audio(qapp, tmp_path, monkeypatch):
    """Le même casque Bluetooth apparaissait 3 fois à l'identique (MME, DirectSound,
    WASAPI) — choix impossible pour l'utilisatrice, constaté le 2026-08-04."""
    import sounddevice as sd

    peripheriques = [
        {"name": "Headset (casque Bluetooth)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Headset (casque Bluetooth)", "max_input_channels": 2, "hostapi": 1},
        {"name": "Haut-parleurs", "max_input_channels": 0, "hostapi": 1},   # sortie : exclue
    ]
    apis = [{"name": "MME"}, {"name": "Windows WASAPI"}]
    monkeypatch.setattr(sd, "query_devices", lambda i=None: peripheriques[i] if i is not None else peripheriques)
    monkeypatch.setattr(sd, "query_hostapis", lambda i=None: apis[i] if i is not None else apis)

    vue = PreferencesView(_config(tmp_path))
    libelles = [vue._combo_micro.itemText(i) for i in range(vue._combo_micro.count())]

    assert "Headset (casque Bluetooth) — MME" in libelles
    assert "Headset (casque Bluetooth) — Windows WASAPI" in libelles
    assert not any("Haut-parleurs" in l for l in libelles), "une sortie ne doit pas être listée"
    assert len(set(libelles)) == len(libelles), "aucun libellé ne doit être ambigu"


def test_selecteur_micro_survit_a_une_api_illisible(qapp, tmp_path, monkeypatch):
    """Le suffixe est décoratif : son échec ne doit pas vider le sélecteur."""
    import sounddevice as sd

    monkeypatch.setattr(sd, "query_devices",
                        lambda i=None: [{"name": "Micro", "max_input_channels": 1, "hostapi": 0}]
                        if i is None else {"name": "Micro", "max_input_channels": 1, "hostapi": 0})
    monkeypatch.setattr(sd, "query_hostapis", lambda i=None: (_ for _ in ()).throw(RuntimeError("boum")))

    vue = PreferencesView(_config(tmp_path))
    libelles = [vue._combo_micro.itemText(i) for i in range(vue._combo_micro.count())]
    assert "Micro" in libelles


def test_defaut_indique_le_peripherique_resolu(qapp, tmp_path, monkeypatch):
    """« par défaut » ne disait pas ce qu'il résolvait — c'est ce qui a masqué le fait
    qu'un micro interne était enregistré alors qu'un casque était branché."""
    import sounddevice as sd

    monkeypatch.setattr(sd, "query_devices",
                        lambda i=None: {"name": "Microphone Array (Realtek)", "max_input_channels": 4, "hostapi": 0}
                        if i is not None else [])
    monkeypatch.setattr(sd, "query_hostapis", lambda i=None: {"name": "MME"})
    monkeypatch.setattr(sd.default, "device", [3, 4], raising=False)

    vue = PreferencesView(_config(tmp_path))
    assert "Microphone Array (Realtek)" in vue._combo_micro.itemText(0)
