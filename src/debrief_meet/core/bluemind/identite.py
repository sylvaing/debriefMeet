"""Résolution d'identité BlueMind : email → (domain_uid, user_uid).

Séquence (docs/40 §3/§9, alignée sur le projet frère `bluemind-mcp` ENDPOINTS.md §2) :

1. `domain_guess = email.split("@")[1]` — hypothèse de départ.
2. `GET users/{domain_guess}/byEmail/{email}` : marche pour la plupart des comptes.
3. Si refusé (401/403/404) ou introuvable (204) : `POST directory/{domain_guess}/_search`
   (accessible à un utilisateur normal, comme l'autocomplétion webmail) — le **vrai**
   `domain_uid` se déduit de `value.path` (`{domainUid}/users/{uid}`), pas de la partie
   droite de l'email (alias mail ≠ domaine technique).
4. Aucun résultat → `ErreurIdentiteIntrouvable`.

Ne cache rien elle-même : l'appelant (sync.py) décide de la persistance (store.meta,
cf. docs/40 §5.1 — le reset vide aussi cette identité mise en cache)."""
from __future__ import annotations

from dataclasses import dataclass

from debrief_meet.core.bluemind.client import (
    ClientBlueMind,
    ErreurAuthBlueMind,
    ErreurBlueMind,
    ErreurIntrouvable,
)


class ErreurIdentiteIntrouvable(ErreurBlueMind):
    """Aucun utilisateur BlueMind ne correspond à l'email fourni."""


@dataclass(frozen=True)
class IdentiteResolue:
    domain_uid: str
    user_uid: str
    email: str
    nom_affiche: str


def _nom_affiche(donnees: dict, repli: str) -> str:
    """Best-effort — le nom n'est affiché que dans « Tester la connexion »,
    jamais utilisé pour une décision métier : on ne lève jamais ici."""
    if not isinstance(donnees, dict):
        return repli
    for cle in ("displayName", "commonName", "name"):
        valeur = donnees.get(cle)
        if isinstance(valeur, str) and valeur.strip():
            return valeur
    try:
        formatte = donnees["contactInfos"]["identification"]["formatted_name"]["value"]
        if isinstance(formatte, str) and formatte.strip():
            return formatte
    except (KeyError, TypeError):
        pass
    login = donnees.get("login")
    return login if isinstance(login, str) and login.strip() else repli


def _domain_uid_depuis_path(path: str) -> str | None:
    """`value.path` est de la forme `{domainUid}/users/{uid}`."""
    if not path or "/" not in path:
        return None
    return path.split("/", 1)[0]


def resoudre_identite(client: ClientBlueMind, email: str) -> IdentiteResolue:
    if "@" not in email:
        raise ErreurIdentiteIntrouvable(f"Adresse email invalide : {email!r}")
    domain_guess = email.split("@", 1)[1]

    reponse = None
    try:
        reponse = client.get(f"users/{domain_guess}/byEmail/{email}")
    except (ErreurAuthBlueMind, ErreurIntrouvable):
        reponse = None

    if reponse is not None and reponse.status_code != 204:
        donnees = reponse.json()
        # `or {}` : un `"value": null` (clé présente) échapperait au défaut de `get`
        # et ferait lever `_nom_affiche` — cf. docs/40 §5.3.
        valeur = (donnees.get("value") or {}) if isinstance(donnees, dict) else {}
        return IdentiteResolue(
            domain_uid=domain_guess,
            user_uid=donnees.get("uid", ""),
            email=email,
            nom_affiche=_nom_affiche(valeur, email),
        )

    # Fallback : recherche annuaire (accessible à un utilisateur non-admin).
    reponse2 = client.post(
        f"directory/{domain_guess}/_search",
        json={
            "emailFilter": email,
            "kindsFilter": ["USER"],
            "hiddenFilter": True,
        },
    )
    corps = reponse2.json()
    valeurs = corps.get("values", corps if isinstance(corps, list) else [])
    if not valeurs:
        raise ErreurIdentiteIntrouvable(f"Aucun utilisateur BlueMind trouvé pour {email}")

    entree = valeurs[0]
    valeur = (entree.get("value") or {}) if isinstance(entree, dict) else {}
    domain_uid = _domain_uid_depuis_path(valeur.get("path", "")) or domain_guess
    return IdentiteResolue(
        domain_uid=domain_uid,
        user_uid=entree.get("uid", ""),
        email=email,
        nom_affiche=_nom_affiche(valeur, email),
    )
