from __future__ import annotations

from datetime import datetime, timedelta

from debrief_meet.core.bluemind.store import Evenement, StoreCalendrier
from debrief_meet.core.config import Config
from debrief_meet.core.planificateur_reunions import PlanificateurReunions

EMAIL = "sylvain.garcia@bluemind.net"


def _config(tmp_path, **overrides):
    cfg = Config(chemin=tmp_path / "config.json")
    cfg.set("bluemind_email", EMAIL)
    for cle, valeur in overrides.items():
        cfg.set(cle, valeur)
    return cfg


def _evt(uid, debut, fin_min=30, journee_entiere=False, invites=None, mon_part_status=None):
    return Evenement(
        uid=uid, cal_uid="cal:Default:u1",
        debut_ms=int(debut.timestamp() * 1000), fin_ms=int(debut.timestamp() * 1000) + fin_min * 60_000,
        journee_entiere=journee_entiere, titre="Point projet X", lieu="",
        organisateur={"nom": "Sylvain Garcia", "email": EMAIL},
        invites=invites if invites is not None else [{"email": "jean@ex.com", "part_status": "Accepted"}],
        mon_part_status=mon_part_status,
    )


def test_notifie_evenement_du(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4))])
    plan = PlanificateurReunions(_config(tmp_path), store)
    dus = plan.tick(maintenant)
    assert [e.uid for e in dus] == ["e1"]


def test_ne_notifie_pas_deux_fois(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4))])
    plan = PlanificateurReunions(_config(tmp_path), store)
    assert len(plan.tick(maintenant)) == 1
    assert len(plan.tick(maintenant + timedelta(seconds=30))) == 0


def test_pas_encore_l_heure(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 0)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=30))])  # avance par défaut = 5 min
    plan = PlanificateurReunions(_config(tmp_path), store)
    assert plan.tick(maintenant) == []


def test_grace_retard_app_lancee_en_retard(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 14, 10)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", datetime(2026, 7, 8, 14, 0))])  # commencé depuis 10 min
    plan = PlanificateurReunions(_config(tmp_path), store)
    assert plan.tick(maintenant) == []


def test_filtre_solo_exclu_par_defaut(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4), invites=[])])
    plan = PlanificateurReunions(_config(tmp_path), store)
    assert plan.tick(maintenant) == []


def test_filtre_solo_inclus_si_active(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4), invites=[])])
    plan = PlanificateurReunions(_config(tmp_path, bluemind_notif_inclure_solo=True), store)
    assert len(plan.tick(maintenant)) == 1


def test_filtre_refuse_exclu_par_defaut(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4), mon_part_status="Declined")])
    plan = PlanificateurReunions(_config(tmp_path), store)
    assert plan.tick(maintenant) == []


def test_filtre_refuse_inclus_si_active(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4), mon_part_status="Declined")])
    plan = PlanificateurReunions(_config(tmp_path, bluemind_notif_inclure_refuses=True), store)
    assert len(plan.tick(maintenant)) == 1


def test_filtre_journee_entiere_exclu_par_defaut(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant, journee_entiere=True)])
    plan = PlanificateurReunions(_config(tmp_path), store)
    assert plan.tick(maintenant) == []


def test_notifications_globales_desactivees(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4))])
    plan = PlanificateurReunions(_config(tmp_path, notifications=False), store)
    assert plan.tick(maintenant) == []


def test_notif_reunions_desactivee(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4))])
    plan = PlanificateurReunions(_config(tmp_path, bluemind_notif_reunions=False), store)
    assert plan.tick(maintenant) == []


def test_signal_reunion_due_emis(qapp, tmp_path):
    maintenant = datetime(2026, 7, 8, 13, 56)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt("e1", maintenant + timedelta(minutes=4))])
    plan = PlanificateurReunions(_config(tmp_path), store)
    recus = []
    plan.reunion_due.connect(lambda evt: recus.append(evt))
    plan.tick(maintenant)
    assert len(recus) == 1
    assert recus[0].uid == "e1"
