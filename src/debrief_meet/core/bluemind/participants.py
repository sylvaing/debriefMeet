"""Bloc invités inséré en tête de transcription (docs/40 §6.3).

Idempotent via marqueurs HTML — re-valider F1 remplace le bloc existant, jamais de
doublon. L'en-tête « participants potentiels… ne vaut pas liste de présence » est
**exigé explicitement** par la spec : un invité n'est pas forcément présent."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from debrief_meet.core.bluemind.sync import libelle_part_status

MARQUEUR_DEBUT = "<!-- bluemind:invites v1 -->"
MARQUEUR_FIN = "<!-- /bluemind:invites -->"

_ENTETE = (
    "## Invités à la réunion (participants potentiels — extrait du calendrier "
    "BlueMind, ne vaut pas liste de présence)"
)


def construire_bloc(titre_reunion: str, debut_texte: str, invites: list[dict]) -> str:
    """`invites` : dicts `{"nom","email","organisateur":bool,"part_status"}` — déjà
    filtrés aux seuls invités cochés (docs/40 §6.3 point 3)."""
    lignes = [MARQUEUR_DEBUT, _ENTETE, f"Réunion : « {titre_reunion} » — {debut_texte}"]
    for inv in invites:
        statut = "organisateur" if inv.get("organisateur") else libelle_part_status(inv.get("part_status"))
        lignes.append(f"- {inv['nom']} <{inv['email']}> — {statut}")
    lignes.append(MARQUEUR_FIN)
    return "\n".join(lignes) + "\n"


def _retirer_bloc_existant(texte: str) -> str:
    debut = texte.find(MARQUEUR_DEBUT)
    if debut == -1:
        return texte
    fin = texte.find(MARQUEUR_FIN, debut)
    if fin == -1:
        return texte
    fin += len(MARQUEUR_FIN)
    while fin < len(texte) and texte[fin] == "\n":
        fin += 1
    return texte[:debut] + texte[fin:]


def _inserer_apres_h1(texte: str, bloc: str) -> str:
    lignes = texte.splitlines(keepends=True)
    for i, ligne in enumerate(lignes):
        if ligne.startswith("# "):
            j = i + 1
            if j < len(lignes) and lignes[j].strip() == "":
                j += 1
            return "".join(lignes[:j]) + bloc + "\n" + "".join(lignes[j:])
    return bloc + "\n" + texte


def inserer_dans_fichier(chemin: Path, bloc: str) -> None:
    """Insère/remplace le bloc invités en tête du fichier (après le H1 s'il existe).
    No-op si le fichier n'existe pas (docs/40 §10 : « fichiers absents »)."""
    if not chemin.exists():
        return
    texte = chemin.read_text(encoding="utf-8")
    sans_bloc = _retirer_bloc_existant(texte)
    chemin.write_text(_inserer_apres_h1(sans_bloc, bloc), encoding="utf-8")


def inserer_pour_reunion(md: Path, titre_reunion: str, debut_texte: str, invites: list[dict]) -> None:
    """Insère dans `<stem>.md` **et** `<stem>_locuteurs.md` s'il existe déjà (§6.3
    point 2) — sinon le hook diarization (`GestionnaireDiarization`) l'insère à sa
    génération."""
    from debrief_meet.core.fichiers import chemin_locuteurs

    bloc = construire_bloc(titre_reunion, debut_texte, invites)
    inserer_dans_fichier(md, bloc)
    loc = chemin_locuteurs(md)
    if loc.exists():
        inserer_dans_fichier(loc, bloc)


def debut_lisible(debut: str | None) -> str:
    """« 2026-08-24T11:00:00+02:00 » → « 2026-08-24 11:00 » ; valeur brute si illisible."""
    try:
        return datetime.fromisoformat(debut).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return debut or ""


def reinserer_depuis_sidecar(md: Path, *, cible: Path | None = None) -> bool:
    """Ré-insère le cartouche invités en le relisant du sidecar `bluemind.json`.

    Point d'entrée UNIQUE des chemins qui réécrivent un fichier de réunion de bout en
    bout — ils repartent d'une page blanche et effacent donc le cartouche au passage
    (transcription différée locale, réécriture Voxtral) — ou qui créent un fichier
    après coup, la réunion étant déjà associée (`locuteurs.md` de la diarization).
    Sans ce rappel le cartouche disparaît du `.md` livré alors que le sidecar, lui,
    reste complet : constaté le 2026-08-24 sur une transcription locale, où seul le
    chemin Voxtral avait son correctif.

    `cible` vise un fichier précis ; par défaut le `.md` **et** son `locuteurs.md`
    s'il existe. Renvoie False (sans rien écrire) si la réunion n'est pas associée ou
    si aucun invité n'est coché — un cartouche sans nom n'apprendrait rien."""
    from debrief_meet.core.bluemind import association
    from debrief_meet.core.fichiers import chemin_locuteurs, titre_reunion

    asso = association.lire(md)
    if asso is None:
        return False
    invites = [
        {"nom": i.nom, "email": i.email, "organisateur": i.organisateur,
         "part_status": i.part_status}
        for i in asso.invites if i.coche
    ]
    if not invites:
        return False
    # Le titre courant du `.md` prime : il peut avoir été édité à la main depuis
    # l'association, et c'est lui que l'utilisateur voit dans l'Historique.
    titre = titre_reunion(md) or asso.titre or md.parent.name
    bloc = construire_bloc(titre, debut_lisible(asso.debut), invites)
    if cible is not None:
        inserer_dans_fichier(cible, bloc)
        return True
    inserer_dans_fichier(md, bloc)
    loc = chemin_locuteurs(md)
    if loc.exists():
        inserer_dans_fichier(loc, bloc)
    return True
