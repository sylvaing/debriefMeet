"""Sidecar `<stem>.bluemind.json` — source de vérité de l'association F1 (docs/40 §6.3).

Sert aussi à F2 (mapping des locuteurs, `mapping`) et à ne pas re-proposer le bouton
« Associer à la réunion » une fois l'association faite."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

VERSION_SIDECAR = 1


@dataclass
class InviteAssocie:
    nom: str
    email: str
    part_status: str | None
    organisateur: bool
    coche: bool


@dataclass
class Association:
    event_uid: str
    cal_uid: str
    titre: str
    debut: str  # iso8601
    invites: list[InviteAssocie] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)  # F2 : SPEAKER_XX -> "Prénom Nom"
    version: int = VERSION_SIDECAR


def chemin_sidecar(md: Path) -> Path:
    return md.with_name(md.stem + ".bluemind.json")


def existe(md: Path) -> bool:
    return chemin_sidecar(md).exists()


def lire(md: Path) -> Association | None:
    chemin = chemin_sidecar(md)
    if not chemin.exists():
        return None
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        invites = [InviteAssocie(**i) for i in donnees.get("invites", [])]
        return Association(
            event_uid=donnees["event_uid"],
            cal_uid=donnees["cal_uid"],
            titre=donnees.get("titre", ""),
            debut=donnees.get("debut", ""),
            invites=invites,
            mapping=donnees.get("mapping", {}),
            version=donnees.get("version", VERSION_SIDECAR),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Sidecar BlueMind illisible (%s) : %s", chemin, exc)
        return None


def ecrire(md: Path, association: Association) -> None:
    chemin = chemin_sidecar(md)
    donnees = {
        "version": association.version,
        "event_uid": association.event_uid,
        "cal_uid": association.cal_uid,
        "titre": association.titre,
        "debut": association.debut,
        "invites": [asdict(i) for i in association.invites],
        "mapping": association.mapping,
    }
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")


def enregistrer_mapping(md: Path, mapping: dict[str, str]) -> None:
    """F2 — sauvegarde le mapping SPEAKER_XX → nom dans le sidecar existant.
    No-op si aucun sidecar (le mapping reste utilisable sans BlueMind, §7)."""
    association = lire(md)
    if association is None:
        return
    association.mapping = mapping
    ecrire(md, association)


# ── Construction depuis un `Evenement` (F1 dialog + F3 démarrage pré-associé) ───

def construire_invites_depuis_evenement(evt) -> list[InviteAssocie]:
    """Organisateur + invités d'un `Evenement` (store), tous cochés par défaut."""
    invites: list[InviteAssocie] = []
    if evt.organisateur:
        invites.append(InviteAssocie(
            nom=evt.organisateur.get("nom") or evt.organisateur.get("email", ""),
            email=evt.organisateur.get("email", ""), part_status=None,
            organisateur=True, coche=True))
    for inv in evt.invites:
        invites.append(InviteAssocie(
            nom=inv.get("nom") or inv.get("email", ""), email=inv.get("email", ""),
            part_status=inv.get("part_status"), organisateur=False, coche=True))
    return invites


def finaliser_association(md: Path, association: Association, appliquer_titre: bool = True) -> None:
    """Écrit le sidecar, applique éventuellement le titre, insère le bloc invités
    dans `<stem>.md` et `<stem>_locuteurs.md` (docs/40 §6.3) — commun à F1 (dialog,
    invités éventuellement décochés) et F3 (démarrage pré-associé, tous cochés)."""
    from datetime import datetime

    from debrief_meet.core.bluemind.participants import inserer_pour_reunion
    from debrief_meet.core.fichiers import definir_titre, titre_reunion

    ecrire(md, association)
    if appliquer_titre and association.titre:
        definir_titre(md, association.titre)

    titre_bloc = association.titre if appliquer_titre else (titre_reunion(md) or association.titre)
    try:
        debut_texte = datetime.fromisoformat(association.debut).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        debut_texte = association.debut
    invites_coches = [
        {"nom": i.nom, "email": i.email, "organisateur": i.organisateur, "part_status": i.part_status}
        for i in association.invites if i.coche
    ]
    inserer_pour_reunion(md, titre_bloc, debut_texte, invites_coches)


def associer_evenement(md: Path, evt) -> Association:
    """F3 — démarrage pré-associé : associe `md` à `evt` avec tous les invités
    cochés, titre appliqué (docs/40 §8)."""
    from datetime import datetime

    debut_dt = datetime.fromtimestamp(evt.debut_ms / 1000).astimezone()
    asso = Association(
        event_uid=evt.uid, cal_uid=evt.cal_uid, titre=evt.titre,
        debut=debut_dt.isoformat(), invites=construire_invites_depuis_evenement(evt),
    )
    finaliser_association(md, asso, appliquer_titre=True)
    return asso
