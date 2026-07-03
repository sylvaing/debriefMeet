"""Prompts de copie — modèles éditables ajoutés en tête lors de la copie (cf. docs/12).

Un prompt = `{ "titre": str, "contenu": str }`. La liste et l'index actif sont stockés
en config. À la copie d'une transcription / d'un débrief locuteurs depuis l'Historique,
le contenu du prompt actif est préfixé au texte. Aucun moteur LLM ici : on prépare juste
le presse-papiers pour que l'utilisateur colle le tout dans l'assistant de son choix.
"""
from __future__ import annotations

CR_SIMPLE_TITRE = "CR simple"

CR_SIMPLE_CONTENU = """\
Tu es un assistant spécialisé dans la rédaction de comptes-rendus au format markdown de réunion professionnels. À partir de la transcription que je te fournis, génère un CR concis et structuré en respectant les règles suivantes :

Format
- Titre : "CR — [Sujet] — [Date]"
- Participants listés sous le titre
- Séparateurs --- entre les sections
- Sections en gras et numérotées
- Listes à tirets pour les sous-points

Contenu
- Une section courte "Contexte" (1-2 phrases max) pour poser le cadre
- Une section "Points discutés" numérotés, chacun avec un titre en gras et un paragraphe court suivi de tirets si nécessaire
- Une section "Actions" listant uniquement les tâches concrètes avec le responsable, sans reformuler ce qui a déjà été dit plus haut

Règles de rédaction
- Phrases courtes et directes, pas de style administratif lourd
- Ne pas paraphraser inutilement : si un chiffre ou un terme technique est mentionné, le conserver tel quel
- Ne pas inventer de décisions ou d'actions qui ne sont pas explicitement dans la transcription
- Ignorer les apartés, problèmes techniques de connexion et digressions sans rapport avec le sujet

Voici la transcription :"""

# Index du prompt actif par défaut (le CR simple, en position 0).
PROMPT_ACTIF_DEFAUT = 0


def prompts_par_defaut() -> list[dict]:
    """Liste de prompts par défaut (une copie fraîche à chaque appel)."""
    return [{"titre": CR_SIMPLE_TITRE, "contenu": CR_SIMPLE_CONTENU}]


def contenu_actif(prompts: list[dict] | None, index: int | None) -> str | None:
    """Contenu du prompt actif, ou None si aucun actif / index invalide / contenu vide."""
    if not prompts or index is None:
        return None
    if not (0 <= index < len(prompts)):
        return None
    contenu = (prompts[index] or {}).get("contenu", "")
    return contenu if contenu.strip() else None


def prefixer(transcription: str, contenu: str) -> str:
    """Préfixe la transcription par le contenu du prompt (séparés d'une ligne vide)."""
    return f"{contenu.rstrip()}\n\n{transcription}"
