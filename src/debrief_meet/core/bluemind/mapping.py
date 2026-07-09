"""F2 — mapping des locuteurs détectés dans `_locuteurs.md` sur les invités de la
réunion associée (docs/40 §7).

Le pipeline de diarization (`core/diarization.py:etiqueter`) nomme déjà les clusters
de façon contextuelle (« Moi », « Présent 1/2… », « Distant 1/2… ») plutôt que le
générique `SPEAKER_00/01` — ce module détecte donc **les étiquettes en gras réellement
présentes** dans le fichier plutôt qu'un motif `SPEAKER_XX` figé, tout en gardant la
mécanique décrite par la spec (aperçu des interventions, heuristiques, réécriture)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from debrief_meet.core.bluemind.association import InviteAssocie

_MOTIF_TOUR = re.compile(r"^\*\*(.+?)\*\*\s*\[(\d{2}):(\d{2})\]\s*(.*)$")


@dataclass
class LocuteurDetecte:
    label: str
    apercu: list[str] = field(default_factory=list)   # 2-3 premières interventions
    poids_parole: int = 0                              # proxy du temps de parole


def extraire_locuteurs(chemin_locuteurs: Path, max_apercu: int = 3) -> list[LocuteurDetecte]:
    """Étiquettes en gras `**Label** [MM:SS] texte…`, dans l'ordre de 1ʳᵉ apparition.
    `poids_parole` = somme des longueurs de texte (proxy du temps de parole — les
    horodatages de `_locuteurs.md` n'ont pas de durée de fin explicite)."""
    try:
        texte = chemin_locuteurs.read_text(encoding="utf-8")
    except OSError:
        return []

    ordre: list[str] = []
    apercus: dict[str, list[str]] = {}
    poids: dict[str, int] = {}
    for ligne in texte.splitlines():
        m = _MOTIF_TOUR.match(ligne.strip())
        if not m:
            continue
        label, _mm, _ss, contenu = m.groups()
        if label not in ordre:
            ordre.append(label)
            apercus[label] = []
            poids[label] = 0
        contenu = contenu.strip()
        if contenu and len(apercus[label]) < max_apercu:
            apercus[label].append(contenu)
        poids[label] += len(contenu)

    return [LocuteurDetecte(label=l, apercu=apercus[l], poids_parole=poids[l]) for l in ordre]


def pre_remplir(locuteurs: list[LocuteurDetecte], invites: list[InviteAssocie]) -> dict[str, str]:
    """Heuristiques légères de pré-remplissage (§7) — jamais silencieusement
    définitives, seulement une suggestion que l'utilisateur voit et corrige.

    1. nb locuteurs == nb invités « accepté » (+ organisateur) → dans l'ordre de temps
       de parole décroissant vs (organisateur, puis acceptés) ;
    2. 2 locuteurs et 1 seul autre invité accepté → « Moi » + cet invité ;
    3. sinon, si un organisateur existe : le locuteur au plus grand temps de parole →
       organisateur (seule suggestion).
    Aucune des trois ne s'applique → dict vide (« aucune suggestion »)."""
    if not locuteurs:
        return {}
    ordre = sorted(locuteurs, key=lambda l: l.poids_parole, reverse=True)
    organisateur = next((i for i in invites if i.organisateur), None)
    acceptes = [i for i in invites if not i.organisateur and i.part_status == "Accepted"]

    cible = ([organisateur] if organisateur else []) + acceptes
    if cible and len(ordre) == len(cible):
        return {loc.label: personne.nom for loc, personne in zip(ordre, cible)}

    if len(ordre) == 2 and len(acceptes) == 1:
        return {ordre[0].label: "Moi", ordre[1].label: acceptes[0].nom}

    if organisateur is not None:
        return {ordre[0].label: organisateur.nom}

    return {}


def renommer_locuteurs(chemin_locuteurs: Path, mapping: dict[str, str]) -> None:
    """Remplace chaque étiquette `**Label**` par `**Nouveau nom**`, partout — y compris
    les horodatages de prise de parole (§7). No-op si `mapping` est vide."""
    if not mapping or not chemin_locuteurs.exists():
        return
    texte = chemin_locuteurs.read_text(encoding="utf-8")
    # Les labels les plus longs d'abord : évite qu'un label préfixe d'un autre
    # (« Présent 1 » / « Présent 10 ») ne soit remplacé partiellement.
    for label in sorted(mapping, key=len, reverse=True):
        nouveau = mapping[label].strip()
        if nouveau:
            texte = texte.replace(f"**{label}**", f"**{nouveau}**")
    chemin_locuteurs.write_text(texte, encoding="utf-8")
