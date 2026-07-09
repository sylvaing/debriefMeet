"""F3 — notification de début de réunion (docs/40 §8).

QTimer léger (tick 30 s, thread UI) qui lit uniquement la réplique locale — **jamais
de réseau au tick**. Le filtre par défaut (≥ 1 autre invité, pas refusée, pas journée
entière) est débrayable par les clés `bluemind_notif_inclure_*` (§4). Anti-double-
notification via le store (`meta`, effacé par `reinitialiser()` au reset §5.1)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from debrief_meet.core.bluemind.store import Evenement, StoreCalendrier

if TYPE_CHECKING:
    from debrief_meet.core.config import Config

logger = logging.getLogger(__name__)

_TICK_MS = 30_000
_GRACE_RETARD_MIN = 5  # événement commencé depuis plus longtemps -> app lancée en retard, ne pas notifier


def _cle_notif(evt: Evenement) -> str:
    return f"notifie_reunion:{evt.cal_uid}:{evt.uid}:{evt.debut_ms}"


class PlanificateurReunions(QObject):
    reunion_due = Signal(object)  # Evenement

    def __init__(self, config: "Config", store: StoreCalendrier, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._store = store
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self.tick)

    def demarrer(self) -> None:
        self._timer.start()

    def arreter(self) -> None:
        self._timer.stop()

    def tick(self, maintenant: datetime | None = None) -> list[Evenement]:
        """Un passage de vérification — public (pas seulement `@Slot`) pour être
        appelable directement et de façon déterministe dans les tests."""
        maintenant = maintenant or datetime.now()
        dus: list[Evenement] = []
        if not self._config.get("notifications") or not self._config.get("bluemind_notif_reunions"):
            return dus

        avance_min = int(self._config.get("bluemind_notif_avance_min") or 5)
        email = self._config.get("bluemind_email") or ""
        fin = maintenant + timedelta(minutes=avance_min)
        debut_ms, fin_ms = int(maintenant.timestamp() * 1000), int(fin.timestamp() * 1000)

        for evt in self._store.evenements_dans_plage(debut_ms, fin_ms):
            if self._doit_notifier(evt, maintenant, avance_min, email):
                self._store.set_meta(_cle_notif(evt), "1")
                dus.append(evt)
                self.reunion_due.emit(evt)
        return dus

    def _doit_notifier(self, evt: Evenement, maintenant: datetime, avance_min: int, email: str) -> bool:
        if self._store.get_meta(_cle_notif(evt)) is not None:
            return False
        if evt.journee_entiere and not self._config.get("bluemind_notif_inclure_journee"):
            return False
        autres_invites = [i for i in evt.invites if (i.get("email") or "").lower() != email.lower()]
        if not autres_invites and not self._config.get("bluemind_notif_inclure_solo"):
            return False
        if evt.mon_part_status == "Declined" and not self._config.get("bluemind_notif_inclure_refuses"):
            return False

        debut = datetime.fromtimestamp(evt.debut_ms / 1000)
        if maintenant < debut - timedelta(minutes=avance_min):
            return False  # pas encore l'heure
        if maintenant > debut + timedelta(minutes=_GRACE_RETARD_MIN):
            return False  # commencé depuis trop longtemps (app lancée en retard)
        return True
