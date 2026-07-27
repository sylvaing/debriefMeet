"""Synchronisation du calendrier BlueMind → réplique locale (docs/40 §5).

`SynchroCalendrier` est le point d'entrée Qt (comme `OrchestrateurReunion` dans
`core/reunion.py` — la couche `core/` importe librement `PySide6.QtCore`, seuls les
modules OS-spécifiques sont interdits, cf. CLAUDE.md « règle d'or »). Le worker réseau
tourne dans un QThread, protégé par `proteger_thread`/`arreter_thread` (docs/26) : une
sync ne doit jamais retarder la fermeture de l'app.

Stratégie réseau (§3, §5) : changeset incrémental si une version est déjà connue et
que le serveur la supporte ; **plan B** (re-`_search` complet de la fenêtre) sinon —
déclenché automatiquement dès que l'incrémental échoue ou rencontre une récurrence non
triviale (rrule/occurrences). C'est un choix assumé du document de spec : la correction
prime sur l'efficacité réseau en v1.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from PySide6.QtCore import QObject, QThread, Signal, Slot

from debrief_meet.core.arret_threads import arreter_thread, proteger_thread
from debrief_meet.core.bluemind.client import ClientBlueMind, ErreurBlueMind
from debrief_meet.core.bluemind.identite import IdentiteResolue, resoudre_identite
from debrief_meet.core.bluemind.store import Evenement, StoreCalendrier

if TYPE_CHECKING:
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)

_STATUTS_PART = {
    "Accepted": "accepté",
    "Declined": "refusé",
    "Tentative": "provisoire",
    "NeedsAction": "sans réponse",
}


def libelle_part_status(part_status: str | None) -> str:
    return _STATUTS_PART.get(part_status or "", "sans réponse")


# ── Conversions BmDateTime ↔ datetime/epoch ─────────────────────────────────────

def _bmdatetime_vers_dt(bmdt: dict) -> datetime:
    dt = datetime.fromisoformat(bmdt["iso8601"])
    if dt.tzinfo is not None:
        return dt
    fuseau = bmdt.get("timezone")
    if fuseau:
        try:
            return dt.replace(tzinfo=ZoneInfo(fuseau))
        except Exception:  # noqa: BLE001 — fuseau inconnu, on ne bloque pas la sync
            pass
    return dt.replace(tzinfo=timezone.utc)


def _epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _dt_vers_bmdatetime(dt: datetime) -> dict:
    # Le serveur BlueMind (parseur Java `DateTimeParseException`) exige un offset —
    # un iso8601 sans 'Z'/'+HH:MM' échoue en 500 (constaté en test réel, 2026-07-09).
    return {
        "iso8601": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "UTC",
        "precision": "DateTime",
    }


def _est_journee_entiere(bmdt: dict) -> bool:
    return bmdt.get("precision") == "Date"


# ── Parsing des personnes (organisateur/invités) ────────────────────────────────

# Ressource de visioconférence auto-ajoutée par BlueMind (`cutype: "Resource"`) —
# pas un participant humain, à exclure de la liste des invités (constaté en test
# réel, 2026-07-09 : présente sur ~18 % des réunions du calendrier de Sylvain).
_NOM_RESSOURCE_VIDEO = "bluemind.video"


def _est_ressource_video(brut: dict) -> bool:
    return (brut.get("commonName") or "").strip().lower() == _NOM_RESSOURCE_VIDEO


def _parse_personne(brut: dict) -> dict:
    return {
        "nom": brut.get("commonName") or brut.get("mailto", ""),
        "email": (brut.get("mailto") or "").lower(),
        "part_status": brut.get("partStatus"),
        "role": brut.get("role"),
    }


def mon_part_status(email_utilisateur: str, organisateur: dict, invites: list[dict]) -> str | None:
    email_l = email_utilisateur.lower()
    for inv in invites:
        if inv.get("email", "").lower() == email_l:
            return inv.get("part_status")
    if (organisateur.get("email") or "").lower() == email_l:
        return "Accepted"
    return None


# ── Parsing des événements (réponse `_search` ou série `/complete`) ─────────────

def evenement_depuis_json(item: dict, cal_uid: str, email_utilisateur: str) -> Evenement | None:
    """Construit un `Evenement` à partir d'un item `_search` (occurrence déjà résolue
    côté serveur) ou d'une série sans récurrence (`main` sans `rrule`/`occurrences`).
    Défensif sur la forme exacte du JSON ([pressenti], cf. docs/40 §3) : accepte aussi
    bien `{"uid","value":{"main":...}}` que `{"uid","main":...}`."""
    uid = item.get("uid")
    valeur = item.get("value", item)
    main = valeur.get("main", valeur)
    dtstart, dtend = main.get("dtstart"), main.get("dtend")
    if not uid or not dtstart or not dtend:
        return None
    try:
        debut, fin = _bmdatetime_vers_dt(dtstart), _bmdatetime_vers_dt(dtend)
    except (KeyError, ValueError, TypeError):
        return None

    organisateur_brut = main.get("organizer") or {}
    organisateur = _parse_personne(organisateur_brut) if organisateur_brut else {}
    invites = [_parse_personne(a) for a in (main.get("attendees") or []) if not _est_ressource_video(a)]

    return Evenement(
        uid=uid,
        cal_uid=cal_uid,
        debut_ms=_epoch_ms(debut),
        fin_ms=_epoch_ms(fin),
        journee_entiere=_est_journee_entiere(dtstart),
        titre=main.get("summary") or "",
        lieu=main.get("location") or "",
        organisateur=organisateur,
        invites=invites,
        mon_part_status=mon_part_status(email_utilisateur, organisateur, invites),
        serie_uid=valeur.get("seriesUid") or uid,
        json_complet=item,
    )


def _extraire_items(corps) -> list[dict]:
    if isinstance(corps, list):
        return corps
    if isinstance(corps, dict):
        return corps.get("values") or corps.get("results") or []
    return []


# ── Algorithme de synchronisation (pur, testable sans QThread) ─────────────────

@dataclass
class ResultatSync:
    ajoutes_ou_maj: int
    supprimes: int
    methode: str  # toujours "recherche_complete" depuis docs/40 §5.2 (incrémental retiré)


def _identite_avec_cache(client: ClientBlueMind, store: StoreCalendrier, email: str) -> IdentiteResolue:
    if store.get_meta("identite_email") == email:
        domain_uid, user_uid = store.get_meta("identite_domain_uid"), store.get_meta("identite_user_uid")
        if domain_uid and user_uid:
            return IdentiteResolue(domain_uid=domain_uid, user_uid=user_uid, email=email, nom_affiche="")
    identite = resoudre_identite(client, email)
    store.set_meta("identite_email", identite.email)
    store.set_meta("identite_domain_uid", identite.domain_uid)
    store.set_meta("identite_user_uid", identite.user_uid)
    return identite


def _rechercher(client: ClientBlueMind, cal_uid: str, debut: datetime, fin: datetime) -> list[dict]:
    corps = {
        "containers": [cal_uid],
        "eventQuery": {"dateMin": _dt_vers_bmdatetime(debut), "dateMax": _dt_vers_bmdatetime(fin)},
    }
    reponse = client.post("calendars/_search", json=corps)
    return _extraire_items(reponse.json())


def _evenements_depuis_item(
    item: dict, cal_uid: str, email: str, debut: datetime, fin: datetime,
) -> list[Evenement]:
    """Un item `_search` → un ou plusieurs `Evenement`. Une série récurrente est
    développée en occurrences concrètes (docs/40 §5.2) ; un événement simple donne
    un seul `Evenement`. Import tardif de `recurrence` pour éviter un cycle (recurrence
    importe les primitives de parsing d'ici)."""
    from debrief_meet.core.bluemind.recurrence import est_serie, expanser_serie

    if est_serie(item):
        return expanser_serie(item, cal_uid, email, debut, fin)
    evt = evenement_depuis_json(item, cal_uid, email)
    return [evt] if evt is not None else []


def _sync_complete(
    client: ClientBlueMind, store: StoreCalendrier, cal_uid: str, email: str,
    debut: datetime, fin: datetime,
) -> ResultatSync:
    """Resync complète : `_search` de la fenêtre, développement des récurrences, puis
    **remplacement total** du calendrier dans la réplique. C'est l'unique stratégie
    depuis docs/40 §5.2 — le chemin incrémental (changeset) ne développait pas les
    séries et rendait toutes les réunions récurrentes invisibles à l'association."""
    items = _rechercher(client, cal_uid, debut, fin)
    evenements: list[Evenement] = []
    for it in items:
        evenements.extend(_evenements_depuis_item(it, cal_uid, email, debut, fin))
    store.remplacer_evenements(cal_uid, evenements)
    return ResultatSync(ajoutes_ou_maj=len(evenements), supprimes=0, methode="recherche_complete")


def executer_sync(
    client: ClientBlueMind, store: StoreCalendrier, email: str,
    fenetre_passe_jours: int, fenetre_futur_jours: int,
    maintenant: datetime | None = None,
) -> ResultatSync:
    """Logique complète d'une synchronisation — pure (sans QThread), directement
    testable. Lève `ErreurBlueMind` en cas d'échec réseau/identité (capturé par le
    worker Qt, jamais affiché sauf « Tester la connexion », cf. §1.1).

    Toujours une resync complète + expansion des récurrences (docs/40 §5.2) : les
    occurrences sont fenêtre-relatives, il faut donc les régénérer à chaque synchro
    quand la fenêtre glisse. Le coût réseau (un `_search`, calendrier minuscule) est
    négligeable — « la correction prime sur l'efficacité réseau en v1 »."""
    maintenant = maintenant or datetime.now(timezone.utc)
    identite = _identite_avec_cache(client, store, email)
    cal_uid = f"calendar:Default:{identite.user_uid}"
    debut = maintenant - timedelta(days=fenetre_passe_jours)
    fin = maintenant + timedelta(days=fenetre_futur_jours)

    resultat = _sync_complete(client, store, cal_uid, email, debut, fin)

    store.set_meta("derniere_sync", maintenant.isoformat())
    return resultat


# ── Worker Qt + gestionnaire persistant ─────────────────────────────────────────

class _WorkerSync(QObject):
    terminee = Signal(int)
    erreur = Signal(str)

    def __init__(
        self, client: ClientBlueMind, store: StoreCalendrier, email: str,
        fenetre_passe_jours: int, fenetre_futur_jours: int,
    ) -> None:
        super().__init__()
        self._client = client
        self._store = store
        self._email = email
        self._fenetre_passe_jours = fenetre_passe_jours
        self._fenetre_futur_jours = fenetre_futur_jours

    @Slot()
    def executer(self) -> None:
        try:
            resultat = executer_sync(
                self._client, self._store, self._email,
                self._fenetre_passe_jours, self._fenetre_futur_jours)
            self.terminee.emit(resultat.ajoutes_ou_maj)
        except Exception as exc:  # noqa: BLE001 — jamais de crash, jamais de popup (§1.1)
            self.erreur.emit(str(exc))
        finally:
            self._client.close()


class SynchroCalendrier(QObject):
    """Gestionnaire persistant (survit à l'ouverture/fermeture des fenêtres, comme
    `GestionnaireDiarization`) : un seul worker de sync à la fois (verrou), déclenché
    par l'ouverture de l'Historique, le démarrage d'une réunion, le timer périodique
    ou le bouton « Tester la connexion » (docs/40 §5)."""

    terminee = Signal(int)   # nb d'événements ajoutés/mis à jour
    echouee = Signal(str)

    def __init__(self, config: "Config", store: StoreCalendrier | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._store = store or StoreCalendrier()
        self._thread: QThread | None = None
        self._worker: _WorkerSync | None = None
        self._client_en_cours: ClientBlueMind | None = None
        self._en_cours = False

    @property
    def store(self) -> StoreCalendrier:
        return self._store

    def configuree(self) -> bool:
        return bool(
            self._config.get("bluemind_url")
            and self._config.get("bluemind_email")
            and self._config.get("bluemind_token")
        )

    def en_cours(self) -> bool:
        return self._en_cours

    def synchroniser_si_necessaire(self) -> bool:
        if not self.configuree() or self._en_cours:
            return False
        try:
            client = ClientBlueMind(
                self._config.get("bluemind_url"), self._config.get("bluemind_token"),
                bool(self._config.get("bluemind_verifier_tls")))
        except ErreurBlueMind as exc:
            logger.debug("Sync BlueMind non démarrée — configuration invalide : %s", exc)
            return False

        worker = _WorkerSync(
            client, self._store, self._config.get("bluemind_email"),
            int(self._config.get("bluemind_fenetre_passe_jours") or 90),
            int(self._config.get("bluemind_fenetre_futur_jours") or 30),
        )
        thread = QThread()
        worker.moveToThread(thread)
        proteger_thread(thread, worker, client)
        thread.started.connect(worker.executer)
        worker.terminee.connect(self._sur_terminee)
        worker.erreur.connect(self._sur_erreur)
        worker.terminee.connect(thread.quit)
        worker.erreur.connect(thread.quit)

        self._thread = thread
        self._worker = worker
        self._client_en_cours = client
        self._en_cours = True
        thread.start()
        return True

    @Slot(int)
    def _sur_terminee(self, n: int) -> None:
        self._en_cours = False
        self.terminee.emit(n)

    @Slot(str)
    def _sur_erreur(self, message: str) -> None:
        logger.debug("Sync BlueMind échouée (silencieux, docs/40 §1.1) : %s", message)
        self._en_cours = False
        self.echouee.emit(message)

    def reinitialiser(self) -> None:
        """§5.1 — stoppe un éventuel worker en cours, vide le store (opération locale
        rapide, immédiate), relance une sync complète en fond si la config est valide."""
        if self._thread is not None and self._thread.isRunning():
            arreter_thread(self._thread, 5_000, garder=(self._worker, self._client_en_cours))
        self._en_cours = False
        self._store.tout_effacer()
        self.synchroniser_si_necessaire()

    def terminer(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            arreter_thread(self._thread, 5_000, garder=(self._worker, self._client_en_cours))
