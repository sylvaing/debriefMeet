"""Qualité des transcriptions : WER + détection d'hallucination par ratio de répétition.

Implémentation interne sans dépendance externe (run unique, ne doit pas planter).
WER : relatif par backend (large-v3 du même backend = référence).
Hallucination : ratio du n-gramme le plus fréquent > seuil → boucle détectée.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

_PONCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_ESPACES = re.compile(r"\s+")

SEUIL_REPETITION = 0.5   # ratio > 50 % de n-grammes dupliqués → hallucination présumée
TAILLE_NGRAM = 5          # n-gramme de 5 mots


def normaliser(texte: str) -> list[str]:
    """Normalise un texte : minuscules, sans accents ni ponctuation."""
    if not texte:
        return []
    texte = unicodedata.normalize("NFD", texte)
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    texte = texte.lower()
    texte = _PONCTUATION.sub(" ", texte)
    texte = _ESPACES.sub(" ", texte).strip()
    return texte.split(" ") if texte else []


def _distance_edition(ref: list[str], hyp: list[str]) -> int:
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
                precedente[j] + 1,
                courante[j - 1] + 1,
                precedente[j - 1] + cout,
            )
        precedente = courante
    return precedente[m]


def wer(reference: str, hypothese: str) -> float:
    """Word Error Rate ∈ [0, 1+]. 0 = identique."""
    ref = normaliser(reference)
    hyp = normaliser(hypothese)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _distance_edition(ref, hyp) / len(ref)


def calculer_ratio_repetition(texte: str, n: int = TAILLE_NGRAM) -> float:
    """Proportion de n-grammes dupliqués : 1 - (n-grammes uniques / total).

    Proche de 1.0 → quasi tout le texte est répétitif (hallucination en boucle).
    Proche de 0.0 → texte naturellement diversifié.

    Robuste à la longueur de la phrase répétée : quel que soit le nombre de mots
    dans la phrase, les n-grammes uniques restent proportionnels à la taille du
    cycle, alors que le total croit avec les répétitions → ratio s'approche de 1.
    """
    mots = normaliser(texte)
    total = len(mots) - n + 1
    if total <= 0:
        return 0.0
    ngrams = [tuple(mots[i:i + n]) for i in range(total)]
    uniques = len(set(ngrams))
    return round(1.0 - uniques / total, 4)


def detecter_hallucination(texte: str, seuil: float = SEUIL_REPETITION) -> bool:
    return calculer_ratio_repetition(texte) > seuil


def appliquer_wer_relatif(resultats: list[dict]) -> None:
    """Calcule le WER de chaque résultat relativement au plus gros modèle réussi
    du même backend. Consomme et retire la clé interne `_texte`."""
    ordre = ["large-v3", "large-v3-turbo", "medium", "small"]
    reussis = [r for r in resultats if r.get("_texte")]
    reference = None
    for pref in ordre:
        for r in reussis:
            if r.get("modele") == pref:
                reference = r
                break
        if reference:
            break
    if reference is None and reussis:
        reference = reussis[-1]

    # Capturés avant la boucle : `del r["_texte"]` ci-dessous efface la clé
    # du dict de référence lui-même quand r is reference, sinon.
    reference_texte = reference["_texte"] if reference is not None else None
    reference_modele = reference["modele"] if reference is not None else None

    for r in resultats:
        if "_texte" in r:
            if reference_texte is not None:
                r["wer"] = round(wer(reference_texte, r["_texte"]), 4)
                r["wer_reference"] = reference_modele
            del r["_texte"]
