"""Détection matériel + table d'auto-sélection du backend de transcription (docs/34 §1.4).

v1 : retourne **toujours** faster-whisper CPU int8 — le matériel est détecté et
loggé quand même à chaque démarrage : ces logs (machines Bastien/Alix) alimenteront
la table d'auto-sélection iGPU définitive une fois le rapport spike (docs/18) rendu.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_BACKENDS_CONNUS = {"auto", "faster-whisper"}


@dataclass
class SelectionBackend:
    nom: str
    options: dict


def detecter_materiel() -> dict:
    """cpu (nom/vendor), igpu (liste de noms détectés), ram_go.

    Réutilise `platform/infos_systeme.py` pour la détection GPU — ne duplique pas
    le PowerShell (docs/31 §3.4)."""
    from debrief_meet.platform.infos_systeme import collecter_infos_systeme

    infos = collecter_infos_systeme()
    gpu = infos.get("gpu", "non collecté")
    igpu: list[str] = [] if gpu == "non collecté" or gpu.startswith("indisponible") else gpu.split(" | ")
    return {
        "cpu": infos.get("processeur", "indisponible"),
        "igpu": igpu,
        "ram_go": infos.get("ram_go", "indisponible"),
    }


def selectionner_backend(config) -> SelectionBackend:
    materiel = detecter_materiel()
    logger.info(
        "Matériel détecté : cpu=%s igpu=%s ram_go=%s",
        materiel["cpu"], materiel["igpu"], materiel["ram_go"],
    )

    backend = config.get("backend") if config is not None else "auto"
    if backend not in _BACKENDS_CONNUS:
        logger.warning("Backend %r non reconnu — repli sur faster-whisper CPU", backend)

    return SelectionBackend("faster-whisper", {"device": "cpu", "compute_type": "int8"})
