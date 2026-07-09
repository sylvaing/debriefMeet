from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon

from debrief_meet.core.config import Config
from debrief_meet.core.modes import MachineEtats
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
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion — 2026-07-08 14:00\n")

    tray._evenement_pre_associe = _evt()
    tray._sur_reunion_demarree(md)

    from debrief_meet.core.bluemind.association import lire
    asso = lire(md)
    assert asso is not None
    assert asso.event_uid == "e1"
    assert tray._evenement_pre_associe is None


def test_sur_reunion_demarree_sans_evenement_en_attente_no_op(qapp, tmp_path):
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    md = tmp_path / "2026-07-08_14-00.md"
    md.write_text("# Réunion\n")
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


def test_pas_de_menu_contextuel_qt_attache(qapp, tmp_path):
    """Ne pas utiliser `setContextMenu()` — sur macOS ça ouvrirait le menu au clic
    gauche aussi (cf. commentaire de `_construire_menu`)."""
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
    machine = MachineEtats()
    cfg = _config(tmp_path)
    fenetre = FenetrePrincipale(machine, cfg)
    tray = IconeTray(machine, cfg, fenetre_principale=fenetre)
    appels = []
    monkeypatch.setattr(tray._menu, "popup", lambda pos: appels.append(pos))
    tray._on_activation(QSystemTrayIcon.ActivationReason.Context)
    assert len(appels) == 1
