"""Export diagnostic « en un clic » (docs/31 §3.6) — décision D6.

Cross-platform (utile aussi sur macOS) : `infos_systeme` est injecté par l'appelant
(collecté fraîchement via `platform/infos_systeme.py` juste avant l'appel) — ce
module ne touche à rien d'OS-spécifique et reste dans `core/`.

Règle vie privée (docs/31 §3.7.1) : jamais de texte transcrit dans le zip — seuls les
logs (déjà nettoyés de tout texte transcrit), les infos système et la config.
"""
from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

from debrief_meet import VERSION_COMPLETE
from debrief_meet.core.config import Config
from debrief_meet.core.logs import chemin_log, chemin_log_crash

logger = logging.getLogger(__name__)


def dossier_diagnostic_par_defaut() -> Path:
    """Le Bureau (décision D6) ; repli sur le dossier utilisateur si absent (pas de
    résolution du Bureau localisé/OneDrive en v1 — le repli couvre ce cas)."""
    bureau = Path.home() / "Desktop"
    return bureau if bureau.is_dir() else Path.home()


def exporter_diagnostic(dossier_cible: Path, infos_systeme: dict) -> Path:
    """Crée `debriefMeet-diagnostic-<VERSION_COMPLETE>-<AAAAMMJJ-HHMMSS>.zip` dans
    `dossier_cible` et retourne son chemin."""
    dossier_cible.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    nom = f"debriefMeet-diagnostic-{VERSION_COMPLETE}-{horodatage}.zip"
    chemin_zip = dossier_cible / nom

    with zipfile.ZipFile(chemin_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        log_path = chemin_log()
        dossier_logs = log_path.parent
        if dossier_logs.is_dir():
            for f in sorted(dossier_logs.glob(f"{log_path.name}*")):
                zf.write(f, arcname=f.name)

        crash = chemin_log_crash()
        if crash.exists():
            zf.write(crash, arcname=crash.name)

        zf.writestr(
            "infos_systeme.json", json.dumps(infos_systeme, ensure_ascii=False, indent=2)
        )

        config = Config()
        config.charger()
        zf.writestr("config.json", json.dumps(config.donnees(), ensure_ascii=False, indent=2))

    logger.info("Diagnostic exporté : %s", chemin_zip)
    return chemin_zip
