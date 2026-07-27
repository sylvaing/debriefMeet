"""Expansion des séries récurrentes BlueMind en occurrences concrètes (docs/40 §5.2).

Le serveur (`calendars/_search`) renvoie une série comme **un unique VEvent maître**
(`rrule` + `exdate` + `occurrences` d'exception), et **jamais** les occurrences
développées — contrairement à ce que supposait `sync.evenement_depuis_json`, qui ne
retenait que `main.dtstart` (la date de *départ* de la série). Résultat constaté le
2026-07-27 : une réunion hebdomadaire (« point commerce Bastien », tous les lundis) était
enregistrée à sa seule date d'origine (2025-09-08), donc purgée hors fenêtre, donc
jamais proposée à l'association. On développe donc la série **côté client** avec
`dateutil`, dans la fenêtre de synchro, en respectant fuseaux, `exdate` (occurrences
annulées) et `occurrences` (instances déplacées/modifiées/annulées).

Comparaisons faites en **epoch ms** (jamais par égalité de `datetime` tz-aware, pour ne
pas dépendre d'une équivalence de `tzinfo` entre l'iso8601 du serveur et le fuseau
d'ancrage) : c'est robuste et aligné sur le stockage (`store.debut_ms`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import (
    DAILY,
    FR,
    MO,
    MONTHLY,
    SA,
    SU,
    TH,
    TU,
    WE,
    WEEKLY,
    YEARLY,
    rrule,
)

from debrief_meet.core.bluemind.store import Evenement
from debrief_meet.core.bluemind.sync import (
    _bmdatetime_vers_dt,
    _epoch_ms,
    _est_journee_entiere,
    _est_ressource_video,
    _parse_personne,
    mon_part_status,
)

_FREQ = {"DAILY": DAILY, "WEEKLY": WEEKLY, "MONTHLY": MONTHLY, "YEARLY": YEARLY}
_JOURS = {"MO": MO, "TU": TU, "WE": WE, "TH": TH, "FR": FR, "SA": SA, "SU": SU}

# Correspondance nom BlueMind (rrule) -> mot-clé dateutil, pour les champs « by… ».
_BY = (
    ("byMonthDay", "bymonthday"), ("byMonth", "bymonth"), ("byYearDay", "byyearday"),
    ("byWeekNo", "byweekno"), ("bySetPos", "bysetpos"),
    ("byHour", "byhour"), ("byMinute", "byminute"), ("bySecond", "bysecond"),
)


def est_serie(item: dict) -> bool:
    """Vrai si l'item `_search` porte une récurrence à développer (`rrule`), ou des
    exceptions (`occurrences`/`exdate`) même sans `rrule` restante."""
    valeur = item.get("value", item)
    main = valeur.get("main", valeur)
    return bool(main.get("rrule") or valeur.get("occurrences") or main.get("exdate"))


def _ancre_zone(bmdt: dict) -> datetime:
    """Ancre de la `rrule` : heure **murale** rattachée à la vraie zone nommée
    (`Europe/Paris`…), pas à l'offset figé de l'iso8601. Indispensable pour le DST —
    ancrer sur `+02:00` figé décalerait toutes les occurrences d'hiver d'une heure (et
    ferait échouer l'exclusion des `exdate` d'hiver). Repli sur `_bmdatetime_vers_dt`
    (offset figé) si la zone est absente/inconnue."""
    dt = datetime.fromisoformat(bmdt["iso8601"])
    tzname = bmdt.get("timezone")
    if tzname:
        try:
            return dt.replace(tzinfo=None).replace(tzinfo=ZoneInfo(tzname))
        except Exception:  # noqa: BLE001 — zone inconnue : repli offset figé
            pass
    return _bmdatetime_vers_dt(bmdt)


def _weekday(brut: dict):
    """`{"day": "MO", "offset": 0}` -> `MO` (ou `MO(offset)` pour « 3e lundi », etc.)."""
    base = _JOURS.get((brut.get("day") or "").upper())
    if base is None:
        return None
    offset = brut.get("offset") or 0
    return base(offset) if offset else base


def _construire_rrule(main: dict, dtstart: datetime) -> rrule | None:
    """Traduit la `rrule` structurée BlueMind en `dateutil.rrule` ancrée sur `dtstart`.
    Retourne None si la fréquence est absente/inconnue (on ne développe alors rien)."""
    rr = main.get("rrule") or {}
    freq = _FREQ.get((rr.get("frequency") or "").upper())
    if freq is None:
        return None
    kwargs: dict = {"dtstart": dtstart, "interval": rr.get("interval") or 1}
    if rr.get("count"):
        kwargs["count"] = rr["count"]
    if rr.get("until"):
        try:
            kwargs["until"] = _bmdatetime_vers_dt(rr["until"])
        except (KeyError, ValueError, TypeError):
            pass
    if rr.get("byDay"):
        jours = [j for j in (_weekday(d) for d in rr["byDay"]) if j is not None]
        if jours:
            kwargs["byweekday"] = jours
    for cle_bm, cle_du in _BY:
        if rr.get(cle_bm):
            kwargs[cle_du] = rr[cle_bm]
    return rrule(freq, **kwargs)


def _evenement_occurrence(
    uid: str, cal_uid: str, email: str, source_main: dict,
    debut: datetime, fin: datetime, serie_item: dict,
) -> Evenement:
    """Construit l'`Evenement` d'une occurrence. `source_main` = le VEvent maître (pour
    une occurrence « normale ») ou l'exception (`occurrences[i]`, pour une instance
    déplacée/modifiée) — c'est lui qui porte titre/lieu/invités effectifs de l'instance."""
    org_brut = source_main.get("organizer") or {}
    organisateur = _parse_personne(org_brut) if org_brut else {}
    invites = [_parse_personne(a) for a in (source_main.get("attendees") or []) if not _est_ressource_video(a)]
    return Evenement(
        uid=uid,
        cal_uid=cal_uid,
        debut_ms=_epoch_ms(debut),
        fin_ms=_epoch_ms(fin),
        journee_entiere=_est_journee_entiere(source_main.get("dtstart") or {}),
        titre=source_main.get("summary") or "",
        lieu=source_main.get("location") or "",
        organisateur=organisateur,
        invites=invites,
        mon_part_status=mon_part_status(email, organisateur, invites),
        serie_uid=uid,
        json_complet=serie_item,
    )


def expanser_serie(
    item: dict, cal_uid: str, email: str,
    fenetre_debut: datetime, fenetre_fin: datetime,
) -> list[Evenement]:
    """Développe une série en occurrences concrètes chevauchant `[fenetre_debut, fenetre_fin]`.

    - occurrences de la `rrule`, hors `exdate` (annulations) et hors slots remplacés par
      une exception ;
    - + les exceptions (`occurrences`) déplacées/modifiées dont l'instance tombe dans la
      fenêtre (une exception `status == "Cancelled"` n'émet rien).

    Ne lève jamais : un item malformé renvoie `[]` (Voxtral/matching ne verra rien,
    plutôt que de planter la synchro)."""
    valeur = item.get("value", item)
    main = valeur.get("main", valeur)
    uid = item.get("uid")
    dtstart_bm, dtend_bm = main.get("dtstart"), main.get("dtend")
    if not uid or not dtstart_bm or not dtend_bm:
        return []
    try:
        duree = _bmdatetime_vers_dt(dtend_bm) - _bmdatetime_vers_dt(dtstart_bm)
        ancre = _ancre_zone(dtstart_bm)  # heure murale + vraie zone (DST correct)
    except (KeyError, ValueError, TypeError):
        return []
    if duree < timedelta(0):
        duree = timedelta(0)

    exceptions = valeur.get("occurrences") or []
    remplaces_ms: dict[int, dict] = {}
    for exc in exceptions:
        rec = exc.get("recurid")
        if not rec:
            continue
        try:
            remplaces_ms[_epoch_ms(_bmdatetime_vers_dt(rec))] = exc
        except (KeyError, ValueError, TypeError):
            pass

    exclus_ms: set[int] = set()
    for ex in main.get("exdate") or []:
        try:
            exclus_ms.add(_epoch_ms(_bmdatetime_vers_dt(ex)))
        except (KeyError, ValueError, TypeError):
            pass

    evenements: list[Evenement] = []

    regle = _construire_rrule(main, ancre)
    if regle is not None:
        # marge d'une durée d'événement pour capter une occurrence commençant juste avant
        # la fenêtre mais la chevauchant encore.
        for dt in regle.between(fenetre_debut - duree, fenetre_fin, inc=True):
            slot_ms = _epoch_ms(dt)
            if slot_ms in exclus_ms or slot_ms in remplaces_ms:
                continue  # annulée, ou remplacée par une exception (émise ci-dessous)
            evenements.append(_evenement_occurrence(uid, cal_uid, email, main, dt, dt + duree, item))

    # Exceptions déplacées/modifiées (l'instance vit à SON propre dtstart, pas au recurid).
    for exc in exceptions:
        if (exc.get("status") or "").lower() == "cancelled":
            continue
        ods, ode = exc.get("dtstart"), exc.get("dtend")
        if not ods or not ode:
            continue
        try:
            o_debut = _bmdatetime_vers_dt(ods)
            o_fin = _bmdatetime_vers_dt(ode)
        except (KeyError, ValueError, TypeError):
            continue
        if fenetre_debut - duree <= o_debut <= fenetre_fin:
            evenements.append(_evenement_occurrence(uid, cal_uid, email, exc, o_debut, o_fin, item))

    return evenements
