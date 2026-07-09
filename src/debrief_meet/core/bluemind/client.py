"""Client HTTP BlueMind — `httpx` sync, appelé depuis des threads de fond
uniquement (jamais le thread UI, cf. docs/40 §1.1/§9).

Auth par header `X-BM-ApiKey`. Timeouts courts (connect 3 s, total 10 s) :
un serveur BlueMind injoignable ne doit jamais faire attendre l'app.
"""
from __future__ import annotations

import logging
import warnings

import httpx

logger = logging.getLogger(__name__)


class ErreurBlueMind(Exception):
    """Base des erreurs BlueMind — jamais affichée sauf action explicite (§1.1)."""


class ErreurConfigurationBlueMind(ErreurBlueMind):
    """URL mal formée (ex. sans le suffixe `/api`)."""


class ErreurAuthBlueMind(ErreurBlueMind):
    """401/403 — clé API invalide ou insuffisante."""


class ErreurIntrouvable(ErreurBlueMind):
    """404."""


class ErreurReseauBlueMind(ErreurBlueMind):
    """Timeout, connexion refusée, DNS…"""


class ErreurServeurBlueMind(ErreurBlueMind):
    """Autre code d'erreur HTTP (4xx/5xx non mappé ci-dessus)."""


def valider_url(url: str) -> str:
    """Normalise (retire le `/` final superflu) et valide l'URL de base.

    Lève `ErreurConfigurationBlueMind` si le suffixe `/api` est absent — cf.
    docs/40 §9 : c'est l'erreur la plus fréquente à la saisie."""
    normalisee = url.strip().rstrip("/")
    if not normalisee.endswith("/api"):
        raise ErreurConfigurationBlueMind(
            "L'URL de l'API BlueMind se termine par /api (ex. https://bm.exemple.com/api)."
        )
    return normalisee


_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=10.0)


class ClientBlueMind:
    """Enveloppe fine autour de `httpx.Client` — un client par appel réseau
    (créé dans le worker, jamais partagé avec le thread UI)."""

    def __init__(self, url: str, token: str, verifier_tls: bool = True) -> None:
        self._base_url = valider_url(url)
        if not verifier_tls:
            # httpx.Client(verify=False) émet un avertissement à chaque requête
            # sans TLS vérifié — filtré une bonne fois pour ne pas polluer les
            # logs (docs/40 §9), sans masquer les autres avertissements.
            warnings.filterwarnings("ignore", message=".*[Cc]ertificate verif.*")
        self._client = httpx.Client(
            base_url=self._base_url + "/",
            headers={"X-BM-ApiKey": token},
            verify=verifier_tls,
            timeout=_TIMEOUT,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClientBlueMind":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ── Requêtes ─────────────────────────────────────────────────────────────

    def get(self, chemin: str, params: dict | None = None) -> httpx.Response:
        return self._requete("GET", chemin, params=params)

    def post(self, chemin: str, json: object | None = None, params: dict | None = None) -> httpx.Response:
        return self._requete("POST", chemin, json=json, params=params)

    def _requete(self, methode: str, chemin: str, **kwargs) -> httpx.Response:
        try:
            r = self._client.request(methode, chemin.lstrip("/"), **kwargs)
        except httpx.TimeoutException as exc:
            raise ErreurReseauBlueMind(f"Délai dépassé ({self._base_url}) : {exc}") from exc
        except httpx.HTTPError as exc:
            raise ErreurReseauBlueMind(f"Connexion impossible ({self._base_url}) : {exc}") from exc

        if r.status_code in (401, 403):
            raise ErreurAuthBlueMind(f"Authentification refusée ({r.status_code}) sur {chemin}")
        if r.status_code == 404:
            raise ErreurIntrouvable(f"Introuvable (404) sur {chemin}")
        if r.status_code >= 400:
            raise ErreurServeurBlueMind(f"Erreur serveur ({r.status_code}) sur {chemin}")
        return r
