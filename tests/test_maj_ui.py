"""docs/53 §3 — UI de la mise à jour : badge de la toolbar, notification tray
(gardée par `notifications`, différée hors IDLE), section Préférences, et le clic
qui lance la procédure (`ui/maj_actions.gerer_clic_maj`)."""
from __future__ import annotations

import pytest

from debrief_meet import __version__
from debrief_meet.core import mise_a_jour as maj
from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.core.verificateur_maj import VerificateurMaj
from debrief_meet.ui import maj_actions
from debrief_meet.ui.fenetre_principale import FenetrePrincipale
from debrief_meet.ui.preferences_view import PreferencesView
from debrief_meet.ui.tray import IconeTray


def _config(tmp_path):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path / "r"))
    cfg.set("dossier_journal", str(tmp_path / "j"))
    return cfg


@pytest.fixture
def machine(qapp):
    return MachineEtats()


@pytest.fixture
def fen(qapp, machine, tmp_path):
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    yield fenetre
    fenetre._recording_controller._timer.stop()


# ── Badge toolbar ────────────────────────────────────────────────────────────

def test_badge_cache_par_defaut(fen):
    assert not fen.maj_badge_visible()
    assert fen._label_version.text() == __version__


def test_badge_visible_avec_la_version_puis_retire(fen):
    fen.definir_maj_disponible("0.9.0")
    assert fen.maj_badge_visible()
    assert "0.9.0" in fen._badge_maj.text() and fen._badge_maj.isEnabled()
    fen.definir_maj_disponible(None)
    assert not fen.maj_badge_visible()
    fen.definir_maj_disponible("")
    assert not fen.maj_badge_visible()


def test_badge_progression_non_cliquable(fen):
    fen.definir_maj_disponible("0.9.0")
    fen.definir_maj_progression(42)
    assert fen.maj_badge_visible() and "42 %" in fen._badge_maj.text()
    assert not fen._badge_maj.isEnabled()


def test_clic_sur_le_badge_emet_maj_cliquee(fen, qtbot):
    fen.definir_maj_disponible("0.9.0")
    with qtbot.waitSignal(fen.maj_cliquee, timeout=1000):
        fen._badge_maj.click()


def test_badge_est_un_bouton_style(fen):
    """Même leçon que les boutons anonymes des assistants (2026-09-02) : un badge
    sans nom de style se peindrait comme du texte, indiscernable d'un libellé."""
    assert fen._badge_maj.objectName() == "majBadge"
    assert not fen._badge_maj.icon().isNull()


# ── Tray ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def tray(qapp, machine, fen, tmp_path):
    return IconeTray(machine, fen._preferences_view._config, fenetre_principale=fen)


def _messages(monkeypatch, tray):
    recus = []
    monkeypatch.setattr(tray, "showMessage", lambda *a, **k: recus.append(a))
    return recus


def test_notification_maj_emise_et_routee_vers_la_fenetre(tray, fen, monkeypatch):
    recus = _messages(monkeypatch, tray)
    tray.notifier_maj_disponible("0.9.0", "https://x")
    assert len(recus) == 1 and "0.9.0" in recus[0][1]
    assert tray._derniere_notif[0] == "maj"
    fen.hide()
    tray._on_notification_cliquee()
    assert fen.isVisible()


def test_notification_maj_gardee_par_notifications(tray, monkeypatch):
    recus = _messages(monkeypatch, tray)
    tray._config.set("notifications", False)
    tray.notifier_maj_disponible("0.9.0")
    assert recus == [] and tray._derniere_notif is None


def test_notification_maj_differee_pendant_un_enregistrement(tray, machine, monkeypatch):
    recus = _messages(monkeypatch, tray)
    assert machine.toggle_reunion() and machine.mode is Mode.REUNION
    tray.notifier_maj_disponible("0.9.0", "https://x")
    assert recus == [], "jamais de notification en réunion"
    assert tray._maj_en_attente == ("0.9.0", "https://x")
    assert machine.toggle_reunion() and machine.mode is Mode.IDLE
    assert len(recus) == 1 and "0.9.0" in recus[0][1]
    assert tray._maj_en_attente is None


# ── Préférences › Général ────────────────────────────────────────────────────

class _FauxVerificateur(VerificateurMaj):
    def __init__(self, config):
        super().__init__(config)
        self.appels = 0
        self.reponse = True

    def verifier(self) -> bool:
        self.appels += 1
        return self.reponse


def test_preferences_case_opt_out_ecrit_la_config(qapp, tmp_path):
    cfg = _config(tmp_path)
    vue = PreferencesView(cfg)
    assert vue._check_maj.isChecked()
    vue._check_maj.setChecked(False)
    assert cfg.get("maj_verifier_auto") is False
    assert "false" in (tmp_path / "config.json").read_text().replace(" ", "")


def test_preferences_sans_verificateur_bouton_inactif(qapp, tmp_path):
    vue = PreferencesView(_config(tmp_path))
    assert not vue._btn_maj.isEnabled()
    assert __version__ in vue._label_maj_statut.text()


def test_preferences_verifier_maintenant_trois_sorties(qapp, tmp_path):
    cfg = _config(tmp_path)
    verif = _FauxVerificateur(cfg)
    vue = PreferencesView(cfg, verificateur_maj=verif)
    vue._btn_maj.click()
    assert verif.appels == 1 and "en cours" in vue._label_maj_statut.text()
    verif.verification_terminee.emit(None)
    assert vue._label_maj_statut.text() == f"✓ À jour ({__version__})"
    verif.verification_terminee.emit("0.9.0")
    assert "0.9.0" in vue._label_maj_statut.text() and "badge" in vue._label_maj_statut.text()
    verif.verification_echouee.emit("DNS")
    assert vue._label_maj_statut.text() == "Échec : DNS"
    verif.reponse = False
    vue._btn_maj.click()
    assert "déjà en cours" in vue._label_maj_statut.text()


def test_dix_sections_toujours(qapp, tmp_path):
    vue = PreferencesView(_config(tmp_path))
    assert vue._pages.count() == 10


# ── Clic → procédure (maj_actions) ───────────────────────────────────────────

class _Verif:
    """Double minimal de VerificateurMaj pour `gerer_clic_maj`."""
    def __init__(self, version="0.9.0", occupe=False, en_cours=False, issue="lance"):
        self._version, self._occupe, self._en_cours, self._issue = version, occupe, en_cours, issue
        self.appels = []

    def version_disponible(self):
        return self._version

    def est_occupe(self):
        return self._occupe

    def en_cours(self):
        return self._en_cours

    def notes_url(self):
        return "https://x/notes"

    def telecharger_et_installer(self):
        self.appels.append("telecharger")
        return self._issue


@pytest.fixture
def dialogues_espions(monkeypatch):
    espion = {"confirmer": [], "avertir": [], "reponse": True, "urls": []}
    monkeypatch.setattr(maj_actions.dialogues, "confirmer",
                        lambda parent, **k: espion["confirmer"].append(k) or espion["reponse"])
    monkeypatch.setattr(maj_actions.dialogues, "avertir", lambda parent, **k: espion["avertir"].append(k))
    monkeypatch.setattr(maj_actions.QDesktopServices, "openUrl", lambda u: espion["urls"].append(u.toString()))
    return espion


@pytest.fixture
def installable(monkeypatch):
    monkeypatch.setattr(maj, "installation_possible", lambda: True)


def test_clic_badge_perime_le_retire(fen, dialogues_espions):
    fen.definir_maj_disponible("0.9.0")
    assert maj_actions.gerer_clic_maj(fen, _Verif(version="")) == "aucune"
    assert not fen.maj_badge_visible()


def test_clic_pendant_un_travail_avertit_sans_telecharger(fen, dialogues_espions, installable):
    v = _Verif(occupe=True)
    assert maj_actions.gerer_clic_maj(fen, v) == "occupe"
    assert v.appels == [] and len(dialogues_espions["avertir"]) == 1
    assert dialogues_espions["confirmer"] == []


def test_clic_manuel_ouvre_la_page_de_release(fen, dialogues_espions, monkeypatch):
    monkeypatch.setattr(maj, "installation_possible", lambda: False)
    v = _Verif()
    assert maj_actions.gerer_clic_maj(fen, v) == "manuel"
    assert dialogues_espions["urls"] == ["https://x/notes"] and v.appels == []


def test_clic_confirme_puis_telecharge(fen, dialogues_espions, installable):
    v = _Verif()
    assert maj_actions.gerer_clic_maj(fen, v) == "lance"
    assert v.appels == ["telecharger"]
    (confirmation,) = dialogues_espions["confirmer"]
    assert "0.9.0" in confirmation["titre"] and confirmation["label_action"] == "Installer et redémarrer"
    assert fen.maj_badge_visible() and not fen._badge_maj.isEnabled()   # jauge à 0 %


def test_clic_refuse_ne_telecharge_pas(fen, dialogues_espions, installable):
    dialogues_espions["reponse"] = False
    v = _Verif()
    assert maj_actions.gerer_clic_maj(fen, v) == "annule"
    assert v.appels == []


def test_clic_en_cours_ne_redemande_pas(fen, dialogues_espions, installable):
    assert maj_actions.gerer_clic_maj(fen, _Verif(en_cours=True)) == "en_cours"
    assert dialogues_espions["confirmer"] == []


def test_brancher_pose_le_badge_depuis_la_config_et_quitte_apres_telechargement(
        qapp, machine, fen, tray, dialogues_espions, monkeypatch, tmp_path):
    cfg = fen._preferences_view._config
    cfg.set("maj_version_disponible", "999.0.0")
    verif = VerificateurMaj(cfg)
    quitte = []

    class _App:   # jamais `qapp.quit` patché sur l'instance : ça masquerait la méthode de classe pour les autres tests
        def quit(self):
            quitte.append(True)
    maj_actions.brancher(fen, tray, verif, _App())
    assert fen.maj_badge_visible() and "999.0.0" in fen._badge_maj.text()
    verif.telechargement_progresse.emit(77)
    assert "77 %" in fen._badge_maj.text()
    verif.telechargement_termine.emit(tmp_path / "x.zip")
    assert quitte == [True]
    verif.telechargement_echoue.emit("réseau")
    assert len(dialogues_espions["avertir"]) == 1 and fen._badge_maj.isEnabled()
    verif.verification_terminee.emit(None)
    assert not fen.maj_badge_visible()
