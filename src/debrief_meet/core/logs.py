from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import platformdirs

from debrief_meet import APP_NAME

_ROOT_LOGGER = "debrief_meet"
_TAILLE_MAX = 1_000_000   # 1 Mo par fichier
_SAUVEGARDES = 3


def chemin_log() -> Path:
    return Path(platformdirs.user_log_dir(APP_NAME)) / "debriefMeet.log"


def configurer_logs(actifs: bool, debug: bool = False) -> None:
    root = logging.getLogger(_ROOT_LOGGER)
    root.handlers.clear()

    if not actifs:
        root.addHandler(logging.NullHandler())
        root.setLevel(logging.CRITICAL + 1)
        return

    log_path = chemin_log()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_TAILLE_MAX,
        backupCount=_SAUVEGARDES,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.info("Logs activés (debug=%s)", debug)
