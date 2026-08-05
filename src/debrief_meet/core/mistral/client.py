"""Client HTTP Mistral — `httpx` sync, appelé depuis un worker de fond uniquement
(jamais le thread UI, cf. docs/42 §2). Auth par header `Authorization: Bearer`.

Timeouts longs (transcription lente, §7.3) : connect 10 s, read 600 s. Reprises sur
erreur réseau transitoire (broken pipe, timeout…) et sur 429 (respect de
`Retry-After`, sinon backoff) — validées en réel par le spike `spike/mistral-cr/`.
"""
from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)


class ErreurMistral(Exception):
    """Base des erreurs Mistral."""


class ErreurAuthMistral(ErreurMistral):
    """401/403 — clé API invalide ou insuffisante."""


class ErreurQuotaMistral(ErreurMistral):
    """429 — quota/rate-limit dépassé malgré les reprises."""


class ErreurFormatMistral(ErreurMistral):
    """400/415/422 — fichier ou paramètres refusés."""


class ErreurReseauMistral(ErreurMistral):
    """Timeout, connexion refusée, DNS…"""


class ErreurServeurMistral(ErreurMistral):
    """Autre code d'erreur HTTP (4xx/5xx non mappé ci-dessus)."""


def valider_url(url: str) -> str:
    """Normalise (retire le `/` final superflu) et valide l'URL de base."""
    normalisee = url.strip().rstrip("/")
    if not normalisee:
        raise ErreurMistral("URL de l'API Mistral vide.")
    return normalisee


_TIMEOUT = httpx.Timeout(connect=10.0, read=600.0, write=600.0, pool=10.0)
_TENTATIVES_RESEAU = 3
_TENTATIVES_429 = 3


def _dormir(secondes: float) -> None:
    """Isolé pour être monkeypatché en test (évite de vraiment dormir)."""
    time.sleep(secondes)


def _delai_retry_after(reponse: httpx.Response) -> float | None:
    valeur = reponse.headers.get("Retry-After")
    if not valeur:
        return None
    try:
        return float(valeur)
    except ValueError:
        return None


class ClientMistral:
    """Enveloppe fine autour de `httpx.Client` — un client par appel (créé dans le
    worker, jamais partagé avec le thread UI)."""

    def __init__(self, url: str, cle_api: str) -> None:
        self._base_url = valider_url(url)
        self._client = httpx.Client(
            base_url=self._base_url + "/",
            headers={"Authorization": f"Bearer {cle_api}"},
            timeout=_TIMEOUT,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClientMistral":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ── Requêtes ─────────────────────────────────────────────────────────────

    def get(self, chemin: str) -> httpx.Response:
        return self._requete("GET", chemin)

    def post_json(self, chemin: str, corps: dict) -> httpx.Response:
        return self._requete("POST", chemin, json=corps)

    def poster_transcription(self, chemin: str, data: dict, nom_fichier: str,
                             contenu: bytes, mime: str, *,
                             retries_429: bool = True) -> httpx.Response:
        """Upload multipart. `contenu` en bytes (pas un flux) : un flux déjà consommé
        lors d'une première tentative serait vide au retry (reprise §7.3).

        `retries_429=False` : lève `ErreurQuotaMistral` dès le premier 429 — pour une
        piste entière trop grosse pour la fenêtre tokens/minute du tier, réessayer ne
        peut pas aboutir (429 persistant sur 2 tentatives à 3 min d'écart, vécu le
        2026-08-05 sur 74 min) ; l'appelant bascule sur le découpage (§10)."""
        return self._requete("POST", chemin, retries_429=retries_429,
                             data=data, files={"file": (nom_fichier, contenu, mime)})

    def _requete(self, methode: str, chemin: str, *,
                 retries_429: bool = True, **kwargs) -> httpx.Response:
        chemin = chemin.lstrip("/")
        derniere_exc: Exception | None = None
        reponse: httpx.Response | None = None
        for tentative in range(1, _TENTATIVES_RESEAU + 1):
            try:
                reponse = self._client.request(methode, chemin, **kwargs)
                break
            except httpx.TimeoutException as exc:
                derniere_exc = exc
                if tentative == _TENTATIVES_RESEAU:
                    raise ErreurReseauMistral(f"Délai dépassé ({self._base_url}) : {exc}") from exc
                logger.warning("Timeout Mistral (tentative %d/%d) — reprise",
                               tentative, _TENTATIVES_RESEAU)
                _dormir(2 * tentative)
            except httpx.HTTPError as exc:
                derniere_exc = exc
                if tentative == _TENTATIVES_RESEAU:
                    raise ErreurReseauMistral(f"Connexion impossible ({self._base_url}) : {exc}") from exc
                logger.warning("Erreur réseau Mistral (tentative %d/%d) — reprise",
                               tentative, _TENTATIVES_RESEAU)
                _dormir(2 * tentative)
        if reponse is None:
            raise ErreurReseauMistral(f"Connexion impossible ({self._base_url})") from derniere_exc
        return self._gerer_reponse(reponse, methode, chemin, kwargs, retries_429=retries_429)

    def _gerer_reponse(self, reponse: httpx.Response, methode: str, chemin: str, kwargs: dict,
                       *, retries_429: bool = True) -> httpx.Response:
        if reponse.status_code == 429:
            if not retries_429:
                raise ErreurQuotaMistral(f"Quota dépassé (429) sur {chemin}")
            for tentative in range(1, _TENTATIVES_429 + 1):
                attente = _delai_retry_after(reponse)
                if attente is None:
                    # Sans Retry-After, les attentes doivent TRAVERSER une fenêtre
                    # tokens/minute complète (cumul > 60 s avant la dernière tentative) :
                    # un gros appel qui vient de réussir laisse la fenêtre pleine, et
                    # 5/10/15 s (cumul 30 s) échouaient dans la même fenêtre — vécu le
                    # 2026-08-05 sur le 1er segment du repli découpage (deux fois).
                    attente = 20.0 * tentative
                logger.warning("429 Mistral — attente %.1fs (tentative %d/%d)",
                               attente, tentative, _TENTATIVES_429)
                _dormir(attente)
                reponse = self._client.request(methode, chemin, **kwargs)
                if reponse.status_code != 429:
                    break
            else:
                raise ErreurQuotaMistral(f"Quota dépassé (429) sur {chemin}")
        if reponse.status_code in (401, 403):
            raise ErreurAuthMistral(f"Authentification refusée ({reponse.status_code}) sur {chemin}")
        if reponse.status_code in (400, 415, 422):
            raise ErreurFormatMistral(
                f"Requête refusée ({reponse.status_code}) sur {chemin} : {reponse.text[:300]}")
        if reponse.status_code >= 400:
            raise ErreurServeurMistral(f"Erreur serveur ({reponse.status_code}) sur {chemin}")
        return reponse
