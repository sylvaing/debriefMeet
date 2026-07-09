"""Association enregistrement ↔ événement de calendrier (docs/40 §6.1).

Chevauchement de `[début_enr - tolérance, début_enr + durée + tolérance]` avec
`[début_évt, fin_évt]` — tolérance pour les enregistrements démarrés en avance/retard.
Journées entières exclues (une réunion ne dure jamais un jour complet)."""
from __future__ import annotations

from datetime import datetime, timedelta

from debrief_meet.core.bluemind.store import Evenement

TOLERANCE_MINUTES = 10


def evenements_correspondants(
    evenements: list[Evenement], debut_enregistrement: datetime, duree_s: int | None,
) -> list[Evenement]:
    tolerance = timedelta(minutes=TOLERANCE_MINUTES)
    fenetre_debut = debut_enregistrement - tolerance
    fenetre_fin = debut_enregistrement + timedelta(seconds=duree_s or 0) + tolerance
    debut_ms = int(fenetre_debut.timestamp() * 1000)
    fin_ms = int(fenetre_fin.timestamp() * 1000)
    return [
        e for e in evenements
        if not e.journee_entiere and e.debut_ms <= fin_ms and e.fin_ms >= debut_ms
    ]
