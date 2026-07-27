"""Tests unitaires — expansion des séries récurrentes BlueMind (docs/40 §5.2).

Sans réseau : on fabrique des items `_search` synthétiques et on vérifie les
occurrences développées. Régression du 2026-07-27 (« point commerce Bastien »,
hebdomadaire, invisible à l'association)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from debrief_meet.core.bluemind.recurrence import est_serie, expanser_serie

EMAIL = "sylvain.garcia@bluemind.net"
CAL = "calendar:Default:u1"
PARIS = ZoneInfo("Europe/Paris")

# Fenêtre de synchro : tout juin 2026.
FEN_DEBUT = datetime(2026, 6, 1, tzinfo=timezone.utc)
FEN_FIN = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _bm(iso, tz="Europe/Paris", precision="DateTime"):
    return {"iso8601": iso, "timezone": tz, "precision": precision}


def _item(rrule=None, exdate=None, occurrences=None,
          debut="2026-06-01T09:30:00+02:00", fin="2026-06-01T10:00:00+02:00",
          summary="Hebdo", uid="s1", attendees=None, precision="DateTime"):
    main = {
        "dtstart": _bm(debut, precision=precision),
        "dtend": _bm(fin, precision=precision),
        "summary": summary, "location": "",
        "organizer": {"mailto": EMAIL, "commonName": "Moi"},
        "attendees": attendees or [], "rrule": rrule,
    }
    if exdate:
        main["exdate"] = exdate
    return {"uid": uid, "value": {"main": main, "occurrences": occurrences or []}}


def _expanser(item):
    return expanser_serie(item, CAL, EMAIL, FEN_DEBUT, FEN_FIN)


def _jours(evenements):
    return sorted(datetime.fromtimestamp(e.debut_ms / 1000, PARIS).strftime("%Y-%m-%d") for e in evenements)


_WEEKLY_MO = {"frequency": "WEEKLY", "interval": 1, "byDay": [{"day": "MO", "offset": 0}]}


# ── est_serie ──────────────────────────────────────────────────────────────────

def test_est_serie_selon_rrule_occurrences_exdate():
    assert est_serie(_item(rrule=_WEEKLY_MO)) is True
    assert est_serie(_item(occurrences=[{"recurid": _bm("2026-06-08T09:30:00+02:00")}])) is True
    assert est_serie(_item(exdate=[_bm("2026-06-08T09:30:00+02:00")])) is True
    assert est_serie(_item()) is False


# ── Cas nominal : hebdomadaire ───────────────────────────────────────────────

def test_hebdomadaire_developpe_tous_les_lundis_de_la_fenetre():
    evs = _expanser(_item(rrule=_WEEKLY_MO))
    # lundis de juin 2026 : 01, 08, 15, 22, 29
    assert _jours(evs) == ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"]
    assert all(e.titre == "Hebdo" for e in evs)
    assert all(e.serie_uid == "s1" and e.uid == "s1" for e in evs)
    assert all(e.journee_entiere is False for e in evs)
    # heure murale conservée (09:30 Paris)
    assert {datetime.fromtimestamp(e.debut_ms / 1000, PARIS).strftime("%H:%M") for e in evs} == {"09:30"}


def test_occurrences_partagent_uid_distinguees_par_debut():
    evs = _expanser(_item(rrule=_WEEKLY_MO))
    cles = {(e.uid, e.debut_ms) for e in evs}
    assert len(cles) == len(evs)  # PK (uid, cal_uid, debut_ms) : pas de collision


# ── exdate : occurrence annulée ──────────────────────────────────────────────

def test_exdate_exclut_l_occurrence():
    evs = _expanser(_item(rrule=_WEEKLY_MO, exdate=[_bm("2026-06-15T09:30:00+02:00")]))
    assert "2026-06-15" not in _jours(evs)
    assert len(evs) == 4


# ── occurrences (exceptions) : déplacée / annulée / invités propres ──────────

def test_exception_deplacee_emise_a_son_propre_horaire():
    exc = {
        "recurid": _bm("2026-06-15T09:30:00+02:00"),
        "dtstart": _bm("2026-06-15T14:00:00+02:00"),
        "dtend": _bm("2026-06-15T15:00:00+02:00"),
        "summary": "Hebdo (décalé)", "status": "Confirmed",
        "organizer": {"mailto": EMAIL}, "attendees": [],
    }
    evs = _expanser(_item(rrule=_WEEKLY_MO, occurrences=[exc]))
    assert _jours(evs) == ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"]
    le_15 = [e for e in evs if datetime.fromtimestamp(e.debut_ms / 1000, PARIS).strftime("%Y-%m-%d") == "2026-06-15"]
    assert len(le_15) == 1
    assert datetime.fromtimestamp(le_15[0].debut_ms / 1000, PARIS).strftime("%H:%M") == "14:00"
    assert le_15[0].titre == "Hebdo (décalé)"


def test_exception_annulee_supprime_l_occurrence():
    exc = {
        "recurid": _bm("2026-06-15T09:30:00+02:00"),
        "dtstart": _bm("2026-06-15T09:30:00+02:00"),
        "dtend": _bm("2026-06-15T10:00:00+02:00"),
        "status": "Cancelled",
    }
    evs = _expanser(_item(rrule=_WEEKLY_MO, occurrences=[exc]))
    assert "2026-06-15" not in _jours(evs)
    assert len(evs) == 4


def test_exception_porte_ses_propres_invites():
    exc = {
        "recurid": _bm("2026-06-15T09:30:00+02:00"),
        "dtstart": _bm("2026-06-15T09:30:00+02:00"),
        "dtend": _bm("2026-06-15T10:00:00+02:00"),
        "summary": "Hebdo", "status": "Confirmed",
        "organizer": {"mailto": EMAIL},
        "attendees": [{"mailto": "bastien@ex.com", "commonName": "Bastien", "partStatus": "Accepted"}],
    }
    evs = _expanser(_item(rrule=_WEEKLY_MO, occurrences=[exc]))
    le_15 = [e for e in evs if datetime.fromtimestamp(e.debut_ms / 1000, PARIS).strftime("%Y-%m-%d") == "2026-06-15"][0]
    assert [i["nom"] for i in le_15.invites] == ["Bastien"]


# ── Bornes : count / until ───────────────────────────────────────────────────

def test_count_borne_le_nombre_d_occurrences():
    evs = _expanser(_item(rrule={**_WEEKLY_MO, "count": 2}))
    assert _jours(evs) == ["2026-06-01", "2026-06-08"]


def test_until_borne_la_serie():
    evs = _expanser(_item(rrule={**_WEEKLY_MO, "until": _bm("2026-06-15T09:30:00+02:00")}))
    assert _jours(evs) == ["2026-06-01", "2026-06-08", "2026-06-15"]


# ── Mensuel avec offset (3e lundi) ───────────────────────────────────────────

def test_mensuel_troisieme_lundi():
    rrule = {"frequency": "MONTHLY", "interval": 1, "byDay": [{"day": "MO", "offset": 3}]}
    evs = _expanser(_item(rrule=rrule))
    assert _jours(evs) == ["2026-06-15"]  # 3e lundi de juin 2026


# ── Journée entière annuelle (anniversaire) ──────────────────────────────────

def test_annuel_journee_entiere():
    evs = _expanser(_item(
        rrule={"frequency": "YEARLY", "interval": 1},
        debut="2026-06-10", fin="2026-06-11", summary="Anniversaire", precision="Date"))
    assert len(evs) == 1
    assert evs[0].journee_entiere is True


# ── DST : heure murale conservée à cheval sur le changement d'heure ──────────

def test_dst_conserve_l_heure_murale():
    evs = expanser_serie(
        _item(rrule={"frequency": "WEEKLY", "interval": 1, "byDay": [{"day": "TU", "offset": 0}]},
              debut="2026-10-13T09:30:00+02:00", fin="2026-10-13T10:00:00+02:00"),
        CAL, EMAIL, datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 15, tzinfo=timezone.utc))
    heures = {datetime.fromtimestamp(e.debut_ms / 1000, PARIS).strftime("%H:%M") for e in evs}
    assert heures == {"09:30"}  # +02 avant le 25/10, +01 après, mais toujours 09:30 mural


# ── Robustesse ───────────────────────────────────────────────────────────────

def test_item_malforme_renvoie_liste_vide():
    assert expanser_serie({"uid": "x", "value": {"main": {}}}, CAL, EMAIL, FEN_DEBUT, FEN_FIN) == []
    assert expanser_serie({"value": {"main": {"dtstart": _bm("2026-06-01T09:30:00+02:00"),
                                              "dtend": _bm("2026-06-01T10:00:00+02:00"), "rrule": _WEEKLY_MO}}},
                          CAL, EMAIL, FEN_DEBUT, FEN_FIN) == []  # pas d'uid


def test_frequence_inconnue_ne_developpe_pas_mais_emet_les_exceptions():
    exc = {
        "recurid": _bm("2026-06-15T09:30:00+02:00"),
        "dtstart": _bm("2026-06-15T09:30:00+02:00"),
        "dtend": _bm("2026-06-15T10:00:00+02:00"),
        "summary": "Exception seule", "status": "Confirmed",
    }
    evs = expanser_serie(_item(rrule={"frequency": "HOURLY"}, occurrences=[exc]),
                         CAL, EMAIL, FEN_DEBUT, FEN_FIN)
    assert _jours(evs) == ["2026-06-15"]
    assert evs[0].titre == "Exception seule"
