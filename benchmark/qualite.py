"""Mesure de qualité des transcriptions — WER (Word Error Rate).

Implémentation interne (distance d'édition au niveau mot), sans dépendance
externe : un outil qui ne tourne qu'une fois et ne doit jamais planter a tout
intérêt à minimiser ses dépendances. Mode retenu : large-v3 sert de référence,
on mesure la dégradation relative de small/medium.
"""
from __future__ import annotations

import re
import unicodedata

_PONCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_ESPACES = re.compile(r"\s+")


def normaliser(texte: str) -> list[str]:
    """Normalise un texte en liste de mots : minuscules, sans accents ni ponctuation."""
    if not texte:
        return []
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")  # ôte accents
    texte = texte.lower()
    texte = _PONCTUATION.sub(" ", texte)
    texte = _ESPACES.sub(" ", texte).strip()
    return texte.split(" ") if texte else []


def _distance_edition(ref: list[str], hyp: list[str]) -> int:
    """Distance de Levenshtein entre deux listes de mots (programmation dynamique)."""
    n, m = len(ref), len(hyp)
    if n == 0:
        return m
    if m == 0:
        return n
    precedente = list(range(m + 1))
    for i in range(1, n + 1):
        courante = [i] + [0] * m
        for j in range(1, m + 1):
            cout = 0 if ref[i - 1] == hyp[j - 1] else 1
            courante[j] = min(
                precedente[j] + 1,        # suppression
                courante[j - 1] + 1,      # insertion
                precedente[j - 1] + cout,  # substitution / égalité
            )
        precedente = courante
    return precedente[m]


def wer(reference: str, hypothese: str) -> float:
    """Word Error Rate ∈ [0, 1+]. 0 = identique.

    Conventions de bord : référence vide → 0.0 si hypothèse vide aussi, sinon 1.0.
    """
    ref = normaliser(reference)
    hyp = normaliser(hypothese)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _distance_edition(ref, hyp) / len(ref)


def metriques(reference: str, hypothese: str) -> dict:
    """WER + comptes de mots, pour le rapport."""
    ref = normaliser(reference)
    hyp = normaliser(hypothese)
    return {
        "wer": round(wer(reference, hypothese), 4),
        "n_mots_reference": len(ref),
        "n_mots_hypothese": len(hyp),
    }
