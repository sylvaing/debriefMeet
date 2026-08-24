from __future__ import annotations

import pytest

from PySide6.QtWidgets import QSystemTrayIcon

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats, Mode
from debrief_meet.ui.fenetre_principale import PAGE_PREFERENCES, PAGE_REUNION, FenetrePrincipale
from debrief_meet.ui.tray import IconeTray


def _config(tmp_path):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("dossier_reunions", str(tmp_path / "r"))
    cfg.set("dossier_journal", str(tmp_path / "j"))
    return cfg


def test_ouvrir_preferences_bascule_la_fenetre_principale(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray._ouvrir_preferences()
    assert fenetre._pages.currentIndex() == PAGE_PREFERENCES


def test_notification_cliquee_ouvre_la_page_reunion(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    fenetre.afficher_preferences()
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray._on_notification_cliquee()
    assert fenetre._pages.currentIndex() == PAGE_REUNION


# ── F3 — notification de début de réunion (docs/40 §8) ─────────────────────────

def _evt(uid="e1", titre="Point projet X"):
    import time as _time

    from debrief_meet.core.bluemind.store import Evenement
    debut_ms = int(_time.time() * 1000) + 120_000  # dans 2 min — notif non expirée
    return Evenement(uid=uid, cal_uid="cal", debut_ms=debut_ms, fin_ms=debut_ms + 3_600_000,
                      journee_entiere=False, titre=titre, lieu="",
                      organisateur={"nom": "Sylvain", "email": "s@ex.com"}, invites=[])


def test_notifier_reunion_due_memorise_derniere_notif(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray.notifier_reunion_due(_evt())
    assert tray._derniere_notif[0] == "reunion"


def test_clic_sur_notif_reunion_demarre_la_reunion(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    evt = _evt()
    tray.notifier_reunion_due(evt)
    tray._on_notification_cliquee()
    assert machine.est_actif is True
    # Sans orchestrateur réel câblé dans ce test, `reunion_demarree` n'est jamais émis :
    # l'événement en attente reste mémorisé jusqu'à `_sur_reunion_demarree` (cf. test dédié).
    assert tray._evenement_pre_associe is evt


def test_clic_sur_notif_reunion_expiree_ne_demarre_pas(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray.notifier_reunion_due(_evt())
    tray._derniere_notif = ("reunion", tray._derniere_notif[1], 0.0)  # déjà expirée
    tray._on_notification_cliquee()
    assert machine.est_actif is False


def test_clic_sur_notif_reunion_pendant_mode_actif_ne_demarre_pas(qapp, tmp_path):
    machine = MachineEtats()
    machine.toggle_dictee()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray.notifier_reunion_due(_evt())
    tray._on_notification_cliquee()
    assert machine.mode.name == "DICTEE"  # inchangé, pas basculé vers réunion


def test_autre_notification_ecrase_la_precedente(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray.notifier_reunion_due(_evt())
    tray.notifier_micro_perdu("Micro perdu")
    tray._on_notification_cliquee()
    assert machine.est_actif is False  # la notif réunion a été écrasée


def test_sur_reunion_demarree_associe_le_fichier(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    dossier = tmp_path / "2026-07-08_14-00-00"
    dossier.mkdir()
    md = dossier / "transcription.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n", encoding="utf-8")

    tray._evenement_pre_associe = _evt()
    tray._sur_reunion_demarree(md)

    from debrief_meet.core.bluemind.association import lire
    # Le dossier a été renommé (titre appliqué, docs/43 §6.1) — relire au nouveau chemin.
    nouveau_md = dossier.with_name("2026-07-08_14-00-00_Point-projet-X") / "transcription.md"
    asso = lire(nouveau_md)
    assert asso is not None
    assert asso.event_uid == "e1"
    assert tray._evenement_pre_associe is None


def test_sur_reunion_demarree_sans_evenement_en_attente_no_op(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion\n", encoding="utf-8")
    tray._sur_reunion_demarree(md)  # pas de clic notif préalable
    from debrief_meet.core.bluemind.association import existe
    assert existe(md) is False


def test_menu_a_les_actions_attendues_dans_l_ordre(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    libelles = [a.text() for a in tray._menu.actions() if a.text()]
    assert libelles == [
        "Démarrer Dictée", "Démarrer Réunion", "Démarrer Journal",
        "Ouvrir debriefMeet", "Préférences…",
        "Exporter le diagnostic…", "Quitter",
    ]


def test_ouvrir_debriefmeet_est_l_action_par_defaut(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    assert tray._menu.defaultAction().text() == "Ouvrir debriefMeet"


def test_pas_de_menu_contextuel_qt_attache(qapp, tmp_path, monkeypatch):
    """Ne pas utiliser `setContextMenu()` **hors Linux** — sur macOS ça ouvrirait le
    menu au clic gauche aussi (cf. commentaire de `_construire_menu`). La règle est
    inversée sous Linux, où l'attache est la seule façon d'avoir un menu : forcé ici
    plutôt que laissé au hasard de la plateforme d'exécution, pour que le test dise
    la même chose sur le Mac et sur la gate LXC."""
    from debrief_meet.ui import tray as mod

    monkeypatch.setattr(mod, "_LINUX", False)
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    assert tray.contextMenu() is None


def test_clic_gauche_ouvre_la_fenetre(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    fenetre.afficher_preferences()
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    tray._on_activation(QSystemTrayIcon.ActivationReason.Trigger)
    assert fenetre.isVisible()
    # n'a pas changé d'onglet (contrairement à _ouvrir_preferences)
    assert fenetre._pages.currentIndex() == PAGE_PREFERENCES


def test_clic_droit_affiche_le_menu(qapp, tmp_path, monkeypatch):
    """Popup manuel : le chemin macOS/Windows. Sous Linux le menu est attaché et
    l'hôte l'affiche lui-même (cf. `test_clic_droit_ne_double_pas_le_menu_sous_linux`)."""
    from debrief_meet.ui import tray as mod

    monkeypatch.setattr(mod, "_LINUX", False)
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    appels = []
    monkeypatch.setattr(tray._menu, "popup", lambda pos: appels.append(pos))
    tray._on_activation(QSystemTrayIcon.ActivationReason.Context)
    assert len(appels) == 1


# ── Mode distant (docs/45) ───────────────────────────────────────────────────

def test_distant_menu_sans_dictee_ni_journal(qapp, tmp_path, mode_distant):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    try:
        tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
        libelles = [a.text() for a in tray._menu.actions() if a.text()]
        assert libelles == [
            "Démarrer Réunion", "Ouvrir debriefMeet", "Préférences…",
            "Exporter le diagnostic…", "Quitter",
        ]
        assert set(tray._actions_modes) == {Mode.REUNION}
    finally:
        fenetre._recording_controller._timer.stop()


def test_distant_actualiser_libelles_survit_a_un_mode_absent(qapp, tmp_path, mode_distant):
    """Un `--toggle` d'un raccourci bureau resté d'une install complète amène
    Mode.DICTEE : la table 4×6 d'origine lèverait KeyError ici."""
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    try:
        tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
        tray._actualiser_libelles(Mode.DICTEE)
        assert tray._actions_modes[Mode.REUNION].text() == "Démarrer Réunion"
        assert not tray._actions_modes[Mode.REUNION].isEnabled()
    finally:
        fenetre._recording_controller._timer.stop()


# ── Intégration GNOME : le menu doit être ATTACHÉ sous Linux ──────────────────

def test_menu_attache_sous_linux(qapp, tmp_path, monkeypatch):
    """Sous Linux le tray passe par StatusNotifierItem : l'hôte n'appelle jamais
    `Activate`, il affiche le menu attaché. Sans `setContextMenu()`, ni le clic
    gauche ni le clic droit ne font quoi que ce soit — l'utilisateur n'a accès à
    AUCUNE action (constaté sur le poste du premier utilisateur Linux)."""
    from debrief_meet.ui import tray as mod

    monkeypatch.setattr(mod, "_LINUX", True)
    machine = MachineEtats()
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    tray = IconeTray(machine, _config(tmp_path), fenetre_principale=fenetre)

    assert tray.contextMenu() is tray._menu


def test_menu_non_attache_ailleurs(qapp, tmp_path, monkeypatch):
    """macOS : un menu attaché s'ouvrirait au clic gauche ET droit — il reste donc
    affiché à la main. Ce test verrouille les deux moitiés de la règle."""
    from debrief_meet.ui import tray as mod

    monkeypatch.setattr(mod, "_LINUX", False)
    machine = MachineEtats()
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    tray = IconeTray(machine, _config(tmp_path), fenetre_principale=fenetre)

    assert tray.contextMenu() is None


def test_clic_droit_ne_double_pas_le_menu_sous_linux(qapp, tmp_path, monkeypatch):
    """Le menu étant attaché, un popup manuel en ouvrirait un SECOND par-dessus."""
    from debrief_meet.ui import tray as mod

    monkeypatch.setattr(mod, "_LINUX", True)
    machine = MachineEtats()
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    tray = IconeTray(machine, _config(tmp_path), fenetre_principale=fenetre)

    popups: list[object] = []
    monkeypatch.setattr(tray._menu, "popup", lambda pos: popups.append(pos))
    tray._on_activation(QSystemTrayIcon.ActivationReason.Context)

    assert popups == []


# ── « Quitter » : l'EFFET de l'activation, pas le libellé ─────────────────────
#
# Les deux tests d'ordre du menu ci-dessus n'assertaient que la présence du texte
# « Quitter » : ils restaient verts alors que l'item était inerte sous Linux, chez
# l'utilisateur, faute de porte de sortie (`setQuitOnLastWindowClosed(False)`).

def _tray_quit_espionne(qapp, tmp_path, monkeypatch, *, linux: bool):
    """Tray construit avec `QApplication.quit` espionné.

    Le remplacement doit précéder la construction : `connect()` capture le callable
    au moment du câblage, un patch posé après n'intercepterait rien."""
    from debrief_meet.ui import tray as mod

    monkeypatch.setattr(mod, "_LINUX", linux)
    appels: list[bool] = []
    monkeypatch.setattr(mod.QApplication, "quit", lambda *a: appels.append(True))
    machine = MachineEtats()
    fenetre = FenetrePrincipale(machine, _config(tmp_path))
    tray = IconeTray(machine, _config(tmp_path), fenetre_principale=fenetre)
    return tray, appels


def _action_quitter(tray):
    return next(a for a in tray._menu.actions() if a.text() == "Quitter")


def _relacher_clic_gauche(widget) -> None:
    """Le vrai chemin souris : `mouseReleaseEvent`, pas l'émission du signal."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    widget.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(1, 1), Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def test_quitter_sous_linux_est_une_action_simple_qui_quitte(qapp, tmp_path, monkeypatch):
    """Sous Linux le menu est exporté via DBusMenu, qui ne transporte que
    libellé/icône/état : un `QWidgetAction` n'y a aucune représentation. L'item
    s'affichait par son seul `setText()` et l'hôte l'activait via `triggered` —
    signal auquel rien n'était branché, d'où un « Quitter » sans effet."""
    from PySide6.QtWidgets import QWidgetAction

    tray, appels = _tray_quit_espionne(qapp, tmp_path, monkeypatch, linux=True)
    action = _action_quitter(tray)

    assert not isinstance(action, QWidgetAction)
    action.trigger()  # ce que fait l'hôte StatusNotifierItem
    assert appels == [True]


def test_quitter_hors_linux_garde_le_widget_rouge_et_quitte_au_clic(qapp, tmp_path, monkeypatch):
    """macOS/Windows : Qt rend le menu lui-même, le widget rouge est conservé —
    et son clic doit toujours quitter."""
    from PySide6.QtWidgets import QWidgetAction

    tray, appels = _tray_quit_espionne(qapp, tmp_path, monkeypatch, linux=False)
    action = _action_quitter(tray)

    assert isinstance(action, QWidgetAction)
    _relacher_clic_gauche(action.defaultWidget())
    assert appels == [True]


def test_quitter_hors_linux_quitte_aussi_par_activation_clavier(qapp, tmp_path, monkeypatch):
    """Filet de sécurité : `QWidgetAction` n'émet pas `triggered` au clic sur son
    widget, mais toute autre activation (clavier, `trigger()`, hôte externe) passe
    par là et n'aboutissait nulle part."""
    tray, appels = _tray_quit_espionne(qapp, tmp_path, monkeypatch, linux=False)

    _action_quitter(tray).trigger()

    assert appels == [True]


def test_quitter_ne_quitte_pas_deux_fois_au_clic(qapp, tmp_path, monkeypatch):
    """Le câblage double (`cliquee` + `triggered`) ne doit pas produire deux sorties
    sur le chemin souris — `QWidgetAction` ne déclenche pas `triggered` quand on
    clique son widget."""
    tray, appels = _tray_quit_espionne(qapp, tmp_path, monkeypatch, linux=False)

    _relacher_clic_gauche(_action_quitter(tray).defaultWidget())

    assert len(appels) == 1
