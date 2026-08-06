"""Lexique de corrections — termes mal transcrits, injectés dans les prompts (docs/46).

Une correspondance = `{ "entendu": str, "ecrire": str }` — la cellule « entendu »
accepte plusieurs variantes séparées par des virgules. Le tableau (config
`lexique_corrections`, interrupteur `lexique_actif`) est rendu en bloc d'instructions
ajouté à la fin des prompts envoyés à l'IA (génération du CR Mistral, copie de
transcription avec prompt) ; la colonne « à écrire » nourrit aussi le `context_bias`
Voxtral. Fonctions pures, aucun moteur LLM ici — la politique d'activation vit dans
`completer_prompt`, seul point d'entrée des sites d'injection.
"""
from __future__ import annotations

import re

_CHAPEAU = (
    "Corrections de transcription :\n"
    "la transcription peut contenir des erreurs phonétiques sur les noms propres et le "
    "jargon technique. Corrige une erreur uniquement si une variante « entendu » "
    "apparaît réellement dans la transcription — silencieusement, sans la signaler. "
    "Cette liste est un référentiel d'orthographes, pas une liste de participants ni "
    "de sujets : n'introduis jamais dans ta réponse un nom ou un terme de la liste qui "
    "n'apparaît pas dans la transcription. Correspondances fréquentes "
    "(« entendu » → à écrire) :"
)

_CONSIGNE_FINALE = (
    "Étends cette logique à tout terme manifestement mal entendu : sigles, noms de "
    "produits, noms de partenaires. Un nom de personne ou d'organisation dont tu n'es "
    "pas sûr : ne l'invente pas — écris-le suivi de « (à confirmer) », ou omets-le."
)

# Précision entre parenthèses de la colonne « à écrire » — gardée dans le bloc injecté
# (elle éclaire le modèle), retirée des termes de biais Voxtral.
_MOTIF_PARENTHESES = re.compile(r"\([^)]*\)")


def corrections_par_defaut() -> list[dict]:
    """Tableau par défaut (copie fraîche à chaque appel) — vocabulaire BlueMind,
    l'app n'étant déployée qu'en interne (docs/46 §7)."""
    return [
        {"entendu": "afida", "ecrire": "Acme"},
        {"entendu": "aron", "ecrire": "Bastien"},
                        {"entendu": "Blue Moon, Bluemine, Blue Mind", "ecrire": "BlueMind"},
        {"entendu": "Hotlook, hot look", "ecrire": "Outlook"},
        {"entendu": "Seppning Club, Second Club", "ecrire": "SecNumCloud"},
        {"entendu": "Maza, Mazin", "ecrire": "ACME (société fictive)"},
        {"entendu": "dire-câble, dircad", "ecrire": "dircab (directeur de cabinet)"},
        {"entendu": "Mappy", "ecrire": "MAPI"},
        {"entendu": "IMAT", "ecrire": "IMAP"},
        {"entendu": "SNTP", "ecrire": "SMTP"},
    ]


def _exploitables(corrections: list[dict] | None) -> list[tuple[list[str], str]]:
    """(variantes entendues, terme à écrire) des lignes complètes — une ligne dont
    « entendu » ou « ecrire » est vide est ignorée (saisie en cours dans l'UI),
    l'ordre du tableau est préservé."""
    lignes: list[tuple[list[str], str]] = []
    for c in corrections or []:
        entendu = ((c or {}).get("entendu") or "").strip()
        ecrire = ((c or {}).get("ecrire") or "").strip()
        variantes = [v.strip() for v in entendu.split(",") if v.strip()]
        if variantes and ecrire:
            lignes.append((variantes, ecrire))
    return lignes


def bloc_instructions(corrections: list[dict] | None) -> str | None:
    """Bloc à injecter à la fin d'un prompt, ou None si aucune ligne exploitable."""
    lignes = _exploitables(corrections)
    if not lignes:
        return None
    corps = "\n".join(
        f"- {', '.join(f'« {v} »' for v in variantes)} → {ecrire}"
        for variantes, ecrire in lignes
    )
    return f"{_CHAPEAU}\n{corps}\n{_CONSIGNE_FINALE}"


# Ligne d'annonce qui clôt les prompts CR — le bloc de corrections doit rester AVANT
# elle : injecté après, il est lu comme faisant partie de la transcription et ses noms
# propres deviennent des « gens de la réunion » (participant inventé sur un CR réel,
# 2026-08-06).
_MARQUEUR_TRANSCRIPTION = "Voici la transcription"


def completer_prompt(prompt: str, config) -> str:
    """`prompt` complété du bloc de corrections si le lexique est actif et non vide —
    sinon le prompt inchangé, à l'identique (pas de rstrip parasite).

    Le bloc est inséré avant la dernière ligne « Voici la transcription… » quand le
    prompt en contient une (groupé avec les instructions, au plus près du contenu) ;
    sans elle, il est mis en TÊTE de prompt — jamais en fin, où il se retrouverait au
    contact direct de la transcription concaténée derrière."""
    if not config.get("lexique_actif"):
        return prompt
    bloc = bloc_instructions(config.get("lexique_corrections"))
    if bloc is None:
        return prompt
    tronc = prompt.rstrip()
    idx = tronc.rfind(_MARQUEUR_TRANSCRIPTION)
    if idx == -1:
        return f"{bloc}\n\n{tronc}"
    debut_ligne = tronc.rfind("\n", 0, idx) + 1
    avant, annonce = tronc[:debut_ligne].rstrip(), tronc[debut_ligne:]
    if not avant:
        return f"{bloc}\n\n{annonce}"
    return f"{avant}\n\n{bloc}\n\n{annonce}"


def termes_biais(corrections: list[dict] | None) -> list[str]:
    """Colonne « à écrire » des lignes exploitables, sans les précisions entre
    parenthèses (« ACME (société fictive) » → « MASA ») — destinée au
    `context_bias` Voxtral. Le découpage en jetons sans espace ni virgule reste
    l'affaire de `mistral.transcription._jetons_context_bias`."""
    termes: list[str] = []
    for _variantes, ecrire in _exploitables(corrections):
        terme = _MOTIF_PARENTHESES.sub("", ecrire).strip()
        if terme:
            termes.append(terme)
    return termes
