from __future__ import annotations

from datetime import datetime, timezone

import httpx
import respx

from debrief_meet.core.bluemind.client import ClientBlueMind
from debrief_meet.core.bluemind.store import StoreCalendrier
from debrief_meet.core.bluemind.sync import (
    SynchroCalendrier,
    evenement_depuis_json,
    executer_sync,
    mon_part_status,
)

URL = "https://bm.example.com/api"
EMAIL = "sylvain.garcia@bluemind.net"
CAL = "calendar:Default:u1"


def _main(summary="Point projet", organizer=None, attendees=None, rrule=None,
          precision="DateTime", debut="2026-07-08T14:00:00+02:00", fin="2026-07-08T15:00:00+02:00"):
    return {
        "dtstart": {"iso8601": debut, "timezone": "Europe/Paris", "precision": precision},
        "dtend": {"iso8601": fin, "timezone": "Europe/Paris", "precision": precision},
        "summary": summary,
        "location": "",
        "organizer": organizer or {"mailto": EMAIL, "commonName": "Sylvain Garcia"},
        "attendees": attendees or [],
        "rrule": rrule,
    }


# ── Parsing pur ──────────────────────────────────────────────────────────────

def test_evenement_depuis_json_bien_forme():
    item = {"uid": "evt-1", "value": {"main": _main(attendees=[
        {"mailto": "jean@ex.com", "commonName": "Jean Dupont", "partStatus": "Accepted", "role": "RequiredParticipant"},
    ])}}
    evt = evenement_depuis_json(item, CAL, EMAIL)
    assert evt is not None
    assert evt.titre == "Point projet"
    assert evt.organisateur["email"] == EMAIL.lower()
    assert evt.invites[0]["nom"] == "Jean Dupont"
    assert evt.mon_part_status == "Accepted"  # organisateur == moi


def test_evenement_depuis_json_champs_manquants():
    assert evenement_depuis_json({"uid": "e1", "value": {"main": {}}}, CAL, EMAIL) is None
    assert evenement_depuis_json({"value": {"main": _main()}}, CAL, EMAIL) is None  # pas d'uid


def test_ressource_bluemind_video_exclue_des_invites():
    """Ressource de visio auto-ajoutée par BlueMind — pas un participant humain
    (signalé par Sylvain, 2026-07-09, ~18 % des réunions de son calendrier réel)."""
    item = {"uid": "evt-1", "value": {"main": _main(attendees=[
        {"mailto": "jean@ex.com", "commonName": "Jean Dupont", "partStatus": "Accepted"},
        {"cutype": "Resource", "commonName": "BlueMind.Video",
         "mailto": "2ddcfd8c-1ad7-4b8c-a774-0ac1718f510f@bluemind.net", "partStatus": "NeedsAction"},
    ])}}
    evt = evenement_depuis_json(item, CAL, EMAIL)
    assert [i["nom"] for i in evt.invites] == ["Jean Dupont"]


def test_journee_entiere_precision_date():
    item = {"uid": "e1", "value": {"main": _main(precision="Date", debut="2026-07-08", fin="2026-07-09")}}
    evt = evenement_depuis_json(item, CAL, EMAIL)
    assert evt.journee_entiere is True


def test_mon_part_status_invite_trouve():
    assert mon_part_status(EMAIL, {}, [{"email": EMAIL.lower(), "part_status": "Declined"}]) == "Declined"


def test_mon_part_status_organisateur():
    assert mon_part_status(EMAIL, {"email": EMAIL.lower()}, []) == "Accepted"


def test_mon_part_status_absent():
    assert mon_part_status(EMAIL, {"email": "autre@ex.com"}, []) is None


# ── Sync complète (identité + _search + expansion + remplacement) ────────────
# Depuis docs/40 §5.2 : plus de chemin incrémental (changeset) — il ne développait
# pas les séries récurrentes et les rendait invisibles à l'association. Chaque synchro
# est une resync complète avec expansion (cf. test_bluemind_recurrence.py).

@respx.mock
def test_premiere_sync_complete(tmp_path):
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {"displayName": "Sylvain"}}))
    respx.post(f"{URL}/calendars/_search").mock(
        return_value=httpx.Response(200, json={"values": [
            {"uid": "evt-1", "value": {"main": _main()}},
        ]}))

    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    client = ClientBlueMind(URL, "token")
    resultat = executer_sync(client, store, EMAIL, 90, 30, maintenant=datetime(2026, 7, 8, 12, tzinfo=timezone.utc))

    assert resultat.methode == "recherche_complete"
    assert resultat.ajoutes_ou_maj == 1
    assert store.nombre_evenements() == 1


@respx.mock
def test_identite_mise_en_cache(tmp_path):
    route = respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {}}))
    respx.post(f"{URL}/calendars/_search").mock(return_value=httpx.Response(200, json={"values": []}))

    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    client = ClientBlueMind(URL, "token")
    executer_sync(client, store, EMAIL, 90, 30)
    executer_sync(client, store, EMAIL, 90, 30)
    assert route.call_count == 1  # 2e appel : identité lue depuis le cache (store.meta)


@respx.mock
def test_sync_complete_developpe_les_recurrences(tmp_path):
    """Une série hebdomadaire renvoyée par `_search` est développée en occurrences
    concrètes dans la fenêtre (régression « point commerce Bastien », docs/40 §5.2)."""
    serie = _main(summary="Point hebdo", debut="2026-06-01T09:30:00+02:00",
                  fin="2026-06-01T10:00:00+02:00",
                  rrule={"frequency": "WEEKLY", "interval": 1, "byDay": [{"day": "MO", "offset": 0}]})
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {}}))
    respx.post(f"{URL}/calendars/_search").mock(
        return_value=httpx.Response(200, json={"values": [{"uid": "evt-hebdo", "value": {"main": serie}}]}))

    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    client = ClientBlueMind(URL, "token")
    resultat = executer_sync(client, store, EMAIL, 7, 28, maintenant=datetime(2026, 6, 8, 12, tzinfo=timezone.utc))

    assert resultat.methode == "recherche_complete"
    # 1 item _search -> plusieurs occurrences (lundis de la fenêtre)
    assert resultat.ajoutes_ou_maj >= 4
    assert store.nombre_evenements() >= 4


@respx.mock
def test_sync_complete_retire_les_evenements_obsoletes(tmp_path):
    """Sans changeset, la resync complète doit refléter les suppressions serveur :
    un événement présent en réplique mais absent du `_search` disparaît (remplacement)."""
    from debrief_meet.core.bluemind.store import Evenement

    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {}}))
    respx.post(f"{URL}/calendars/_search").mock(return_value=httpx.Response(200, json={"values": []}))

    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([Evenement(
        uid="vieux", cal_uid=CAL, debut_ms=0, fin_ms=100, journee_entiere=False,
        titre="Vieux", lieu="")])

    client = ClientBlueMind(URL, "token")
    executer_sync(client, store, EMAIL, 90, 30, maintenant=datetime(2026, 7, 8, tzinfo=timezone.utc))
    assert store.nombre_evenements() == 0


# ── SynchroCalendrier (QObject/QThread) ──────────────────────────────────────

def _config_bluemind(tmp_path, configuree=True):
    from debrief_meet.core.config import Config
    cfg = Config(chemin=tmp_path / "config.json")
    if configuree:
        cfg.set("bluemind_url", URL)
        cfg.set("bluemind_email", EMAIL)
        cfg.set("bluemind_token", "token")
    return cfg


def test_non_configuree_ne_demarre_rien(qapp, tmp_path):
    cfg = _config_bluemind(tmp_path, configuree=False)
    sync = SynchroCalendrier(cfg, store=StoreCalendrier(tmp_path / "bm.sqlite3"))
    assert sync.synchroniser_si_necessaire() is False


@respx.mock
def test_verrou_ignore_declenchement_concurrent(qapp, tmp_path):
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {}}))
    respx.post(f"{URL}/calendars/_search").mock(return_value=httpx.Response(200, json={"values": []}))

    cfg = _config_bluemind(tmp_path)
    sync = SynchroCalendrier(cfg, store=StoreCalendrier(tmp_path / "bm.sqlite3"))
    assert sync.synchroniser_si_necessaire() is True
    assert sync.synchroniser_si_necessaire() is False  # verrou : déjà en cours
    sync.terminer()


@respx.mock
def test_synchroniser_emet_terminee(qapp, tmp_path, qtbot):
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {}}))
    respx.post(f"{URL}/calendars/_search").mock(return_value=httpx.Response(200, json={"values": []}))

    cfg = _config_bluemind(tmp_path)
    sync = SynchroCalendrier(cfg, store=StoreCalendrier(tmp_path / "bm.sqlite3"))
    recus = []
    sync.terminee.connect(lambda n: recus.append(n))
    sync.synchroniser_si_necessaire()
    qtbot.waitUntil(lambda: len(recus) == 1, timeout=3000)
    sync.terminer()


@respx.mock
def test_echec_reseau_emet_echouee_sans_lever(qapp, tmp_path, qtbot):
    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(return_value=httpx.Response(500))
    respx.post(f"{URL}/directory/bluemind.net/_search").mock(return_value=httpx.Response(500))

    cfg = _config_bluemind(tmp_path)
    sync = SynchroCalendrier(cfg, store=StoreCalendrier(tmp_path / "bm.sqlite3"))
    erreurs = []
    sync.echouee.connect(lambda m: erreurs.append(m))
    sync.synchroniser_si_necessaire()
    qtbot.waitUntil(lambda: len(erreurs) == 1, timeout=3000)
    sync.terminer()


@respx.mock
def test_reinitialiser_vide_puis_relance(qapp, tmp_path, qtbot):
    from debrief_meet.core.bluemind.store import Evenement

    respx.get(f"{URL}/users/bluemind.net/byEmail/{EMAIL}").mock(
        return_value=httpx.Response(200, json={"uid": "u1", "value": {}}))
    respx.post(f"{URL}/calendars/_search").mock(return_value=httpx.Response(200, json={"values": []}))

    cfg = _config_bluemind(tmp_path)
    store = StoreCalendrier(tmp_path / "bm.sqlite3")
    store.upsert_evenements([Evenement(
        uid="x", cal_uid=CAL, debut_ms=0, fin_ms=100, journee_entiere=False, titre="X", lieu="")])
    store.set_meta("identite_email", "ancien@ex.com")

    sync = SynchroCalendrier(cfg, store=store)
    sync.reinitialiser()
    assert store.get_meta("identite_email") != "ancien@ex.com" or store.nombre_evenements() == 0
    qtbot.waitUntil(lambda: not sync.en_cours(), timeout=3000)
    sync.terminer()


def test_terminer_sans_thread_ne_leve_pas(qapp, tmp_path):
    cfg = _config_bluemind(tmp_path, configuree=False)
    sync = SynchroCalendrier(cfg, store=StoreCalendrier(tmp_path / "bm.sqlite3"))
    sync.terminer()  # ne doit pas lever
