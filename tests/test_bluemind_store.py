from __future__ import annotations

from debrief_meet.core.bluemind.store import Evenement, StoreCalendrier


def _evt(uid="e1", cal_uid="cal:Default:u1", debut_ms=1000, fin_ms=2000, serie_uid=None, **kw):
    return Evenement(
        uid=uid, cal_uid=cal_uid, debut_ms=debut_ms, fin_ms=fin_ms,
        journee_entiere=kw.pop("journee_entiere", False),
        titre=kw.pop("titre", "Réunion"), lieu=kw.pop("lieu", ""),
        organisateur=kw.pop("organisateur", {"nom": "Alice", "email": "alice@ex.com"}),
        invites=kw.pop("invites", []),
        mon_part_status=kw.pop("mon_part_status", None),
        serie_uid=serie_uid or uid,
        json_complet=kw.pop("json_complet", {}),
    )


def test_meta_roundtrip(tmp_path):
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    assert store.get_meta("version") is None
    store.set_meta("version", "42")
    assert store.get_meta("version") == "42"
    store.set_meta("version", "43")
    assert store.get_meta("version") == "43"
    store.supprimer_meta("version")
    assert store.get_meta("version") is None


def test_upsert_puis_lecture(tmp_path):
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt(titre="Point projet")])
    evts = store.evenements_dans_plage(0, 5000)
    assert len(evts) == 1
    assert evts[0].titre == "Point projet"
    assert evts[0].organisateur["email"] == "alice@ex.com"


def test_upsert_idempotent_met_a_jour(tmp_path):
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt(titre="V1")])
    store.upsert_evenements([_evt(titre="V2")])
    evts = store.evenements_dans_plage(0, 5000)
    assert len(evts) == 1
    assert evts[0].titre == "V2"


def test_evenements_dans_plage_filtre_chevauchement(tmp_path):
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([
        _evt(uid="avant", debut_ms=0, fin_ms=100),
        _evt(uid="dedans", debut_ms=1000, fin_ms=2000),
        _evt(uid="apres", debut_ms=10_000, fin_ms=11_000),
    ])
    evts = store.evenements_dans_plage(900, 2100)
    assert {e.uid for e in evts} == {"dedans"}


def test_purger_hors_fenetre(tmp_path):
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([
        _evt(uid="vieux", debut_ms=0, fin_ms=100),
        _evt(uid="recent", debut_ms=5000, fin_ms=6000),
    ])
    supprimes = store.purger_hors_fenetre(1000, 10_000)
    assert supprimes == 1
    assert store.nombre_evenements() == 1
    assert store.evenements_dans_plage(0, 20_000)[0].uid == "recent"


def test_supprimer_par_serie(tmp_path):
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([
        _evt(uid="occ1", debut_ms=0, fin_ms=100, serie_uid="serie-A"),
        _evt(uid="occ2", debut_ms=200, fin_ms=300, serie_uid="serie-A"),
        _evt(uid="autre", debut_ms=400, fin_ms=500, serie_uid="serie-B"),
    ])
    n = store.supprimer_par_serie("cal:Default:u1", ["serie-A"])
    assert n == 2
    assert store.nombre_evenements() == 1


def test_tout_effacer(tmp_path):
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([_evt()])
    store.set_meta("version", "1")
    store.tout_effacer()
    assert store.nombre_evenements() == 0
    assert store.get_meta("version") is None


def test_schema_reouverture_idempotente(tmp_path):
    chemin = tmp_path / "bm.sqlite3"
    StoreCalendrier(chemin)
    store2 = StoreCalendrier(chemin)  # ne doit pas lever (CREATE TABLE IF NOT EXISTS)
    assert store2.nombre_evenements() == 0
