"""Export diagnostic « en un clic » (docs/31 §3.6) — décision D6.

Cross-platform (utile aussi sur macOS) : `infos_systeme` est injecté par l'appelant
(collecté fraîchement via `platform/infos_systeme.py` juste avant l'appel) — ce
module ne touche à rien d'OS-spécifique et reste dans `core/`.

Règle vie privée (docs/31 §3.7.1) : jamais de texte transcrit dans le zip — seuls les
logs (déjà nettoyés de tout texte transcrit), les infos système et la config.

Règle secrets (ajoutée le 2026-07-31) : le zip est **fait pour être envoyé**, donc la
config y est caviardée. Un diagnostic réel reçu de Alix contenait sa clé API Mistral et
son token BlueMind en clair — les deux ont dû être révoqués. La valeur d'un secret n'a
jamais aidé à diagnostiquer quoi que ce soit ; savoir s'il est **renseigné** si.
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


# Fragments de nom de clé trahissant un secret. Heuristique volontairement large, et
# non une liste figée de clés : le jour où un `xxx_token` ou un `yyy_cle_api` sera
# ajouté à `_DEFAUTS` pour un nouveau fournisseur, il sera caviardé d'office. Une liste
# nominative, elle, aurait laissé fuir la nouvelle clé en silence.
_FRAGMENTS_SECRETS = ("cle_api", "token", "secret", "password", "mot_de_passe")


def _est_secret(cle: str) -> bool:
    return any(f in cle.lower() for f in _FRAGMENTS_SECRETS)


def caviarder(donnees: dict) -> dict:
    """Remplace la valeur des secrets par un marqueur, sans perdre l'information utile.

    Une clé **vide reste vide** : la distinction « configuré / pas configuré » est
    précisément ce qu'on vient diagnostiquer (une édition lite sans clé Mistral
    enregistre mais ne transcrira jamais). La longueur est conservée — elle ne révèle
    rien d'exploitable et permet de repérer une clé collée tronquée.
    """
    propre = {}
    for cle, valeur in donnees.items():
        if _est_secret(cle) and isinstance(valeur, str) and valeur:
            propre[cle] = f"<masqué — {len(valeur)} caractères>"
        else:
            propre[cle] = valeur
    return propre


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
        zf.writestr(
            "config.json",
            json.dumps(caviarder(config.donnees()), ensure_ascii=False, indent=2),
        )

    logger.info("Diagnostic exporté : %s", chemin_zip)
    return chemin_zip
