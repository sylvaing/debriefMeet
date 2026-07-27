"""Migration one-shot : réunions à plat → 1 dossier par réunion (docs/43 §7).

Avant docs/43, une réunion était un `.md` isolé (`AAAA-MM-JJ_HH-MM[-N].md`) à la
racine de `dossier_reunions`, avec ses dérivés (pistes audio, locuteurs, CR,
sidecar BlueMind) comme fichiers frères nommés par suffixe. Cette migration les
regroupe dans un sous-dossier, fichiers renommés en noms génériques.

Idempotente (rejouable sans dégât) et non bloquante : appelée au démarrage, avant
toute lecture de `dossier_reunions` par l'UI — une erreur sur une réunion est
loguée et n'interrompt jamais les suivantes ni le lancement de l'app."""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from debrief_meet.core.fichiers import slugifier_titre, titre_reunion

logger = logging.getLogger(__name__)

_MOTIF_LEGACY = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(-\d+)?$")
_SUFFIXES_DERIVES_LEGACY = ("_locuteurs", "_CR")


def _est_reunion_legacy(chemin: Path) -> bool:
    """Un `.md` de réunion à plat (racine, pas un dérivé, pas une entrée de journal)."""
    if not chemin.is_file() or chemin.suffix != ".md":
        return False
    if chemin.stem.endswith(_SUFFIXES_DERIVES_LEGACY):
        return False
    return bool(_MOTIF_LEGACY.match(chemin.stem))


def _titre_legacy(md: Path) -> str | None:
    """Titre déduit du sidecar BlueMind legacy (`<stem>.bluemind.json`, prioritaire)
    ou du H1 custom du `.md` — avant tout déplacement, donc encore à l'ancien nom."""
    sidecar = md.with_name(md.stem + ".bluemind.json")
    if sidecar.exists():
        try:
            donnees = json.loads(sidecar.read_text(encoding="utf-8"))
            titre = donnees.get("titre")
            if titre:
                return titre
        except (OSError, ValueError):
            logger.warning("Sidecar BlueMind illisible pendant la migration : %s",
                           sidecar, exc_info=True)
    return titre_reunion(md)


def _mouvements(dossier_reunions: Path, stem: str) -> list[tuple[Path, str]]:
    """Fichiers legacy présents pour ce `stem`, avec leur nom générique cible."""
    candidats = (
        (dossier_reunions / f"{stem}.md", "transcription.md"),
        (dossier_reunions / f"{stem}_moi.opus", "moi.opus"),
        (dossier_reunions / f"{stem}_moi.wav", "moi.wav"),
        (dossier_reunions / f"{stem}_systeme.opus", "systeme.opus"),
        (dossier_reunions / f"{stem}_systeme.wav", "systeme.wav"),
        (dossier_reunions / f"{stem}_locuteurs.md", "locuteurs.md"),
        (dossier_reunions / f"{stem}_CR.md", "CR.md"),
        (dossier_reunions / f"{stem}.bluemind.json", "bluemind.json"),
    )
    return [(src, nom) for src, nom in candidats if src.exists()]


def _cible_unique(dossier_reunions: Path, nom: str) -> Path:
    """Dossier cible libre — collision (migration interrompue en plein milieu par un
    crash précédent, cas rare) résolue par suffixe `-N`, comme les nouvelles réunions."""
    cible = dossier_reunions / nom
    i = 2
    while cible.exists():
        logger.warning("Migration réunions → dossiers : collision sur %s → suffixe -%d", nom, i)
        cible = dossier_reunions / f"{nom}-{i}"
        i += 1
    return cible


def _deplacer(src: Path, dst: Path) -> None:
    try:
        src.rename(dst)
    except OSError:
        # Cross-device (improbable : ~/Documents est le même volume) — repli copie+suppr.
        shutil.move(str(src), str(dst))


def _migrer_une(dossier_reunions: Path, md: Path) -> None:
    stem = md.stem
    titre = _titre_legacy(md)
    slug = slugifier_titre(titre or "")
    nom = f"{stem}_{slug}" if slug else stem
    cible = _cible_unique(dossier_reunions, nom)
    mouvements = _mouvements(dossier_reunions, stem)

    cible.mkdir(parents=True)
    deplaces = []
    for src, nom_nouveau in mouvements:
        _deplacer(src, cible / nom_nouveau)
        deplaces.append(src.name)

    logger.info("Migration réunions → dossiers : %s → %s (%s)",
                stem, cible.name, ", ".join(deplaces) or "aucun satellite")


def migrer_reunions_vers_dossiers(dossier_reunions: Path) -> int:
    """Migre les réunions stockées à plat vers 1 dossier/réunion. Idempotente
    (re-exécutable sans dégât : un 2ᵉ appel ne trouve plus de `.md` à la racine).

    Ne lève jamais : toute erreur sur une réunion est loguée et la migration
    continue avec les suivantes (appelée au démarrage — ne doit jamais empêcher
    le lancement)."""
    if not dossier_reunions.exists():
        return 0
    candidats = sorted(
        (f for f in dossier_reunions.iterdir() if _est_reunion_legacy(f)),
        key=lambda p: p.name,
    )
    migrees = 0
    for md in candidats:
        try:
            _migrer_une(dossier_reunions, md)
            migrees += 1
        except Exception:
            logger.warning("Migration réunions → dossiers : échec sur %s", md.name, exc_info=True)
    return migrees
