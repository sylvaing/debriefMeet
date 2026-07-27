"""Réplique locale SQLite du calendrier BlueMind (docs/40 §5).

Une connexion par appel (ouverte/fermée à chaque méthode) : plus simple et plus sûr
que le partage d'une connexion entre le thread de sync (écriture) et le thread UI
(lecture) — évite tout piège `check_same_thread` pour un volume de données qui reste
minuscule (le calendrier d'un utilisateur sur quelques mois). WAL activé pour que la
lecture ne soit jamais bloquée par une écriture en cours."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from debrief_meet import APP_NAME

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur TEXT);
CREATE TABLE IF NOT EXISTS evenements (
  uid TEXT, cal_uid TEXT, debut_ms INTEGER, fin_ms INTEGER,
  journee_entiere INTEGER, titre TEXT, lieu TEXT,
  organisateur_json TEXT, invites_json TEXT,
  mon_part_status TEXT,
  serie_uid TEXT, json_complet TEXT,
  PRIMARY KEY (uid, cal_uid, debut_ms)
);
CREATE INDEX IF NOT EXISTS idx_evt_plage ON evenements (debut_ms, fin_ms);
"""


def chemin_store_defaut() -> Path:
    # appauthor=False : même convention que config.py/logs.py (CLAUDE.md).
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)) / "bluemind.sqlite3"


@dataclass
class Evenement:
    uid: str
    cal_uid: str
    debut_ms: int
    fin_ms: int
    journee_entiere: bool
    titre: str
    lieu: str
    organisateur: dict = field(default_factory=dict)     # {"nom":..., "email":...}
    invites: list = field(default_factory=list)           # [{"nom","email","part_status","role"}]
    mon_part_status: str | None = None
    serie_uid: str = ""
    json_complet: dict = field(default_factory=dict)      # VEvent brut (F1/F2)


def _ligne_vers_evenement(ligne: sqlite3.Row) -> Evenement:
    return Evenement(
        uid=ligne["uid"],
        cal_uid=ligne["cal_uid"],
        debut_ms=ligne["debut_ms"],
        fin_ms=ligne["fin_ms"],
        journee_entiere=bool(ligne["journee_entiere"]),
        titre=ligne["titre"] or "",
        lieu=ligne["lieu"] or "",
        organisateur=json.loads(ligne["organisateur_json"] or "{}"),
        invites=json.loads(ligne["invites_json"] or "[]"),
        mon_part_status=ligne["mon_part_status"],
        serie_uid=ligne["serie_uid"] or "",
        json_complet=json.loads(ligne["json_complet"] or "{}"),
    )


class StoreCalendrier:
    def __init__(self, chemin: Path | None = None) -> None:
        self._chemin = chemin or chemin_store_defaut()
        self._chemin.parent.mkdir(parents=True, exist_ok=True)
        self._initialiser_schema()

    def _connexion(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._chemin), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialiser_schema(self) -> None:
        with self._connexion() as conn:
            conn.executescript(_SCHEMA)

    # ── meta (clé/valeur) ────────────────────────────────────────────────────

    def get_meta(self, cle: str) -> str | None:
        with self._connexion() as conn:
            ligne = conn.execute("SELECT valeur FROM meta WHERE cle = ?", (cle,)).fetchone()
            return ligne["valeur"] if ligne else None

    def set_meta(self, cle: str, valeur: str) -> None:
        with self._connexion() as conn:
            conn.execute(
                "INSERT INTO meta (cle, valeur) VALUES (?, ?) "
                "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
                (cle, valeur),
            )

    def supprimer_meta(self, cle: str) -> None:
        with self._connexion() as conn:
            conn.execute("DELETE FROM meta WHERE cle = ?", (cle,))

    # ── événements ───────────────────────────────────────────────────────────

    def upsert_evenements(self, evenements: list[Evenement]) -> None:
        with self._connexion() as conn:
            for e in evenements:
                conn.execute(
                    "INSERT INTO evenements "
                    "(uid, cal_uid, debut_ms, fin_ms, journee_entiere, titre, lieu, "
                    " organisateur_json, invites_json, mon_part_status, serie_uid, json_complet) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(uid, cal_uid, debut_ms) DO UPDATE SET "
                    " fin_ms=excluded.fin_ms, journee_entiere=excluded.journee_entiere, "
                    " titre=excluded.titre, lieu=excluded.lieu, "
                    " organisateur_json=excluded.organisateur_json, invites_json=excluded.invites_json, "
                    " mon_part_status=excluded.mon_part_status, serie_uid=excluded.serie_uid, "
                    " json_complet=excluded.json_complet",
                    (
                        e.uid, e.cal_uid, e.debut_ms, e.fin_ms, int(e.journee_entiere),
                        e.titre, e.lieu, json.dumps(e.organisateur, ensure_ascii=False),
                        json.dumps(e.invites, ensure_ascii=False), e.mon_part_status,
                        e.serie_uid, json.dumps(e.json_complet, ensure_ascii=False),
                    ),
                )

    def remplacer_evenements(self, cal_uid: str, evenements: list[Evenement]) -> None:
        """Remplace *tout* le contenu d'un calendrier par `evenements` (delete + insert
        atomique). Utilisé par la resync complète (docs/40 §5.2) : comme on ne suit plus
        de changeset incrémental, un simple upsert laisserait traîner les événements
        supprimés/annulés côté serveur — le remplacement garantit que la réplique reflète
        exactement la fenêtre synchronisée (occurrences récurrentes comprises)."""
        with self._connexion() as conn:
            conn.execute("DELETE FROM evenements WHERE cal_uid = ?", (cal_uid,))
            conn.executemany(
                "INSERT INTO evenements "
                "(uid, cal_uid, debut_ms, fin_ms, journee_entiere, titre, lieu, "
                " organisateur_json, invites_json, mon_part_status, serie_uid, json_complet) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(uid, cal_uid, debut_ms) DO UPDATE SET "
                " fin_ms=excluded.fin_ms, journee_entiere=excluded.journee_entiere, "
                " titre=excluded.titre, lieu=excluded.lieu, "
                " organisateur_json=excluded.organisateur_json, invites_json=excluded.invites_json, "
                " mon_part_status=excluded.mon_part_status, serie_uid=excluded.serie_uid, "
                " json_complet=excluded.json_complet",
                [
                    (
                        e.uid, e.cal_uid, e.debut_ms, e.fin_ms, int(e.journee_entiere),
                        e.titre, e.lieu, json.dumps(e.organisateur, ensure_ascii=False),
                        json.dumps(e.invites, ensure_ascii=False), e.mon_part_status,
                        e.serie_uid, json.dumps(e.json_complet, ensure_ascii=False),
                    )
                    for e in evenements
                ],
            )

    def supprimer_par_serie(self, cal_uid: str, series_uids: list[str]) -> int:
        """Supprime toutes les occurrences dont `serie_uid` (ou `uid` pour un événement
        non récurrent, où série == uid) est dans `series_uids`."""
        if not series_uids:
            return 0
        with self._connexion() as conn:
            marques = ",".join("?" * len(series_uids))
            cur = conn.execute(
                f"DELETE FROM evenements WHERE cal_uid = ? AND (serie_uid IN ({marques}) OR uid IN ({marques}))",
                (cal_uid, *series_uids, *series_uids),
            )
            return cur.rowcount

    def evenements_dans_plage(self, debut_ms: int, fin_ms: int, cal_uid: str | None = None) -> list[Evenement]:
        with self._connexion() as conn:
            if cal_uid is None:
                lignes = conn.execute(
                    "SELECT * FROM evenements WHERE debut_ms <= ? AND fin_ms >= ? ORDER BY debut_ms",
                    (fin_ms, debut_ms),
                ).fetchall()
            else:
                lignes = conn.execute(
                    "SELECT * FROM evenements WHERE cal_uid = ? AND debut_ms <= ? AND fin_ms >= ? "
                    "ORDER BY debut_ms",
                    (cal_uid, fin_ms, debut_ms),
                ).fetchall()
            return [_ligne_vers_evenement(l) for l in lignes]

    def purger_hors_fenetre(self, debut_ms: int, fin_ms: int) -> int:
        with self._connexion() as conn:
            cur = conn.execute(
                "DELETE FROM evenements WHERE fin_ms < ? OR debut_ms > ?", (debut_ms, fin_ms)
            )
            return cur.rowcount

    def nombre_evenements(self) -> int:
        with self._connexion() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM evenements").fetchone()["n"]

    # ── reset total (§5.1) ───────────────────────────────────────────────────

    def tout_effacer(self) -> None:
        """Vide `evenements` ET `meta` (identité en cache, version changeset, registre
        anti-double-notification F3 — tout ce qui est du cache, rien qui est une
        donnée utilisateur). Les sidecars/blocs insérés ne vivent PAS ici."""
        with self._connexion() as conn:
            conn.execute("DELETE FROM evenements")
            conn.execute("DELETE FROM meta")
