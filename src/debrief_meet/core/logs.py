from __future__ import annotations

import logging
import logging.handlers
import sys
import threading
from pathlib import Path
from typing import Any

import platformdirs

from debrief_meet import APP_NAME, VERSION_COMPLETE

_ROOT_LOGGER = "debrief_meet"
# Le DEBUG est bavard (une tranche de réunion loggue RMS/porte/RTF, docs/31 §3.7.2) —
# 1 Mo x 3 ne couvrirait que quelques minutes de réunion.
_TAILLE_MAX = 5_000_000   # 5 Mo par fichier
_SAUVEGARDES = 5

_fichier_crash: Any = None   # handle gardé ouvert au niveau module (faulthandler)


def chemin_log() -> Path:
    # appauthor=False : cf. core/config.py — sans lui, platformdirs double le
    # dossier sur Windows (`%LOCALAPPDATA%\debriefMeet\debriefMeet\Logs`).
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False)) / "debriefMeet.log"


def chemin_log_crash() -> Path:
    return chemin_log().parent / "debriefMeet-crash.log"


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
        logging.Formatter("%(asctime)s %(threadName)s %(name)s %(levelname)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.info("Logs activés (debug=%s) — %s", debug, VERSION_COMPLETE)


def journaliser_entete_session(infos: dict) -> None:
    """Logge en INFO un bloc balisé résumant la machine/session (docs/31 §3.3).

    `infos` est collecté par l'appelant (`platform/infos_systeme.py`) — ce module ne
    collecte rien lui-même et reste sans dépendance OS."""
    root = logging.getLogger(_ROOT_LOGGER)
    lignes = [f"===== SESSION {APP_NAME} {VERSION_COMPLETE} ====="]
    lignes += [f"{cle}: {valeur}" for cle, valeur in infos.items()]
    lignes.append("=" * 22)
    root.info("\n".join(lignes))


def installer_traces_crash() -> None:
    """Capture tout ce qui, sans elle, ne laisserait aucune trace : exceptions non
    rattrapées (main + threads), et crashs natifs via `faulthandler` (docs/31 §3.5)."""
    global _fichier_crash
    logger = logging.getLogger(_ROOT_LOGGER)

    hook_precedent = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        logger.critical("Exception non rattrapée", exc_info=(exc_type, exc_value, exc_tb))
        hook_precedent(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    hook_thread_precedent = threading.excepthook

    def _thread_excepthook(args) -> None:
        logger.critical(
            "Exception non rattrapée dans le thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        hook_thread_precedent(args)

    threading.excepthook = _thread_excepthook

    try:
        import faulthandler
        chemin_log().parent.mkdir(parents=True, exist_ok=True)
        _fichier_crash = chemin_log_crash().open("a", encoding="utf-8")
        faulthandler.enable(file=_fichier_crash)
    except OSError as exc:
        logger.warning("faulthandler indisponible (%s)", exc)
