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
- Une section très courte "Contexte" pour poser le cadre — pas obligé de faire une phrase
- Une section "Points discutés" numérotés, chacun avec un titre en gras et des tirets pour énumérer les points. Pas de phrases, il faut être concis
- Une section "Actions" listant uniquement les tâches concrètes avec le responsable, sans reformuler ce qui a déjà été dit plus haut

Règles de rédaction
- Éviter les phrases ; quand il en faut une, elle est courte et directe, pas de style administratif lourd
- Ne pas paraphraser inutilement : si un chiffre ou un terme technique est mentionné, le conserver tel quel
- Ne pas inventer de décisions ou d'actions qui ne sont pas explicitement dans la transcription
- Ignorer les apartés, problèmes techniques de connexion et digressions sans rapport avec le sujet

Voici la transcription :
---"""

# Ancien contenu du « CR simple » (défaut jusqu'à la config v1) — sert uniquement à la
# migration v2 (core/config.py) : un CR simple resté identique à cet ancien défaut est
# mis à jour vers le nouveau, un CR simple édité par l'utilisateur est laissé intact.
CR_SIMPLE_CONTENU_V1 = """\
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

CR_PIPEDRIVE_TITRE = "CR Pipedrive"

CR_FULL_MD_TITRE = "CR full .md"

# Corps commun aux CR BlueMind (Pipedrive et markdown) : qualification de la réunion,
# camps, attribution, structures A/B/C, règles de rédaction. Seuls l'introduction
# (destination) et la section « 5. Format de sortie » diffèrent — cf. _cr_bluemind().
_CR_BLUEMIND_CORPS = """\
Étape 0 — Qualifier la réunion avant toute rédaction

Détermine d'abord le type de réunion, en croisant les listes de participants/invités et le contenu de la transcription :
- INTERNE : tous les intervenants sont BlueMind. Marqueurs : on parle de clients et de partenaires uniquement à la 3ᵉ personne, de sujets d'organisation, de roadmap, de pipe commercial.
- CLIENT FINAL : l'interlocuteur décrit son propre existant et ses propres besoins (« nos agents », « notre AD », « je dois valider avec », contrainte budgétaire, calendrier imposé).
- PARTENAIRE : l'interlocuteur est un intégrateur/revendeur. Marqueurs : il parle de « ses » clients, de commandes qu'il nous passe, de prestations qu'il vend, de marges, de son planning de déploiement. Le ou les clients finaux évoqués sont des tiers absents.
- MIXTE : partenaire ET client final présents dans la réunion → appliquer la structure CLIENT FINAL, en rattachant le partenaire au camp BlueMind et en le signalant en une ligne sous le bloc participants.

En cas de doute entre client final et partenaire : celui qui vend des prestations et passe des commandes est un partenaire.
Le type choisi détermine la structure (section 3) et le format de sortie (section 5). Ne mélange jamais les structures.

1. Identifier les camps (tous types sauf INTERNE)

Un échange oppose deux camps :
- le camp BlueMind : une ou plusieurs personnes (commercial, avant-vente, direction technique) ;
- le camp d'en face : client final ou partenaire selon le type.

Détermine qui est dans quel camp en croisant trois sources. Aucune ne fait autorité à elle seule :
- La ligne « Participants » que je te donne, si je l'ai fournie. Indication forte sur les identités et rattachements (noms, orthographes, fonctions, camps), mais pas une preuve de présence : des gens ont pu s'ajouter, se décommander ou partir sans que je le note. Format : Participants : Sylvain Garcia (BlueMind), Untel (BlueMind) / Untel (Client ou Partenaire)
- Le bloc d'invités du calendrier en tête de transcription, s'il existe. Même statut, en plus faible : ce sont des invités, pas des présents.
- La transcription elle-même. Seule preuve de ce qui s'est réellement dit, mais elle nomme rarement les gens. Marqueurs de camp fiables :
  - camp BlueMind : annonce des prix, cite des références clients, dit « chez nous », « notre outil », décrit l'architecture proposée ;
  - camp client : décrit son existant, exprime un besoin, une contrainte budgétaire, un calendrier imposé ;
  - camp partenaire : parle de ses clients, de ses commandes, de ses prestations, de son équipe technique.

Arbitrage des écarts entre les listes et la transcription :
- Annoncé mais jamais entendu → le garder, marqué (?). Ne jamais le supprimer, ne jamais écrire qu'il était absent.
- Entendu mais non annoncé → l'ajouter, marqué (non annoncé). Si son nom est donné dans l'échange, l'utiliser ; sinon « un intervenant côté client (non identifié) ».
- Rattachement contredit par le contenu → le contenu l'emporte, à signaler en une ligne sous le bloc participants.
- Départ ou arrivée en cours de séance, si explicite → le noter.

Vérification finale obligatoire : pour chaque nom que tu t'apprêtes à lister comme présent, il doit exister soit une mention dans une des listes fournies, soit une prise de parole ou une interpellation directe attribuable dans la transcription. Une personne dont on parle à la 3ᵉ personne (« untel te passe le bonjour », « j'embarque untel au prochain rendez-vous », « je vais en parler à untel ») n'est jamais un participant — même si elle est nommée dix fois. Quelqu'un qu'on prévoit d'inviter à une réunion future n'est pas un participant de celle-ci.

« Moi » dans la transcription désigne le porteur du micro. C'est presque toujours un membre du camp BlueMind — mais pas forcément la seule voix BlueMind présente. Ne réduis jamais le camp BlueMind à cette seule personne.

2. Attribuer sans inventer

La transcription est faite au micro : les tours de parole ne sont pas identifiés et les propos de tous les présents sont fondus dans un flux continu. Tu dois donc :
- Attribuer au camp par défaut, pas à la personne : « BlueMind a indiqué que… », « côté partenaire, il est demandé que… ». En réunion INTERNE (pas de camps) : nommer la personne uniquement si c'est explicite, sinon formulation neutre (« il a été décidé que… », « il est proposé de… »).
- Nommer un individu uniquement quand c'est explicite : interpellé par son prénom, se présente, ou se désigne par une fonction que la liste confirme. Le doute profite au camp.
- Avant de placer un fait dans un bloc, demande-toi qui l'a dit. Le bloc RÉPONSES BLUEMIND est réservé aux propos et engagements du camp BlueMind ; une information donnée par le client ou le partenaire (son organisation, ses recrutements, ses vérifications, ses prestations) va dans le bloc de son camp, jamais dans le nôtre.
- Ne jamais déduire un participant de la liste d'invités ni d'une mention en passant.
- Ne jamais conclure à un désaccord interne d'un camp à partir de propos contradictoires : c'est le plus souvent un défaut d'attribution du micro.
- Si une voix est inaudible ou coupée, ne combler aucun trou : [inaudible] ou omission pure.

3. Structure du CR selon le type

Titre en gras, commun à tous les types : Type d'échange — Organisation — date, heure (durée). Pour un échange à deux, préciser l'interlocuteur : Échange téléphonique Prénom NOM (Org / fonction si connue) — … Ne pas inventer de fonction : si elle n'est ni dans les listes ni dans l'échange, l'omettre.

PARTICIPANTS — bloc présent uniquement s'il y a plus de deux personnes. Une ligne par camp (ou une ligne unique en INTERNE), avec la fonction quand elle est connue et le degré de certitude :
- nom seul = annoncé et identifiable dans l'échange ;
- (?) = annoncé, mais aucune trace de lui dans l'échange — présence probable, non vérifiée ;
- (non annoncé) = présent dans l'échange sans figurer dans les listes.

Ajouter dessous, en une ligne, tout écart notable. Si l'historique de la relation ressort de la conversation, une ligne en italique pour situer.

Un bloc sans matière est supprimé, jamais rempli avec du vide. Blocs en majuscules et en gras.

Structure A — CLIENT FINAL (et MIXTE)
- CONTEXTE — la situation actuelle chez le client : ce qui est en place, qui l'exploite, pourquoi ça pose problème. 2 à 4 phrases. Chiffres de périmètre exacts ; signaler si un chiffre a été révisé en séance.
- BESOIN — ce que le client demande, en puces. Un besoin = une puce, avec sa justification quand elle a été donnée. Mot-clé en gras. Si plusieurs personnes côté client portent des besoins divergents, le préciser.
- CALENDRIER — dates de début, de fin, échéances, contraintes. Distinguer le ferme de l'hypothèse.
- RÉPONSES BLUEMIND — ce que nous avons répondu et engagé : faisabilité, architecture, prix annoncés, références citées, limites reconnues. Chiffres et conditions au mot près (une fourchette reste une fourchette, une option en supplément n'est pas incluse). Uniquement des propos du camp BlueMind.
- [SUJET DOMINANT] — si un sujet technique a occupé une part importante de l'échange, bloc titré dédié, options numérotées, conclusion en gras : → Accord sur… ou → Non tranché : …
- AUTRES POINTS TECHNIQUES — le reste, en puces courtes.
- CIRCUIT DE DÉCISION — dès qu'il y a plusieurs personnes côté client : qui décide, qui prescrit, qui tient le budget, quelle validation reste à obtenir, qui devra être dans la salle. Uniquement ce qui a été dit.
- SUITE — qui fait le prochain pas et quand. Une ou deux lignes.
- À FAIRE CÔTÉ BLUEMIND — liste numérotée de tâches concrètes pour nous. Porteur nommé si la répartition est explicite ; sinon laisser au camp.
- ATTENDU CÔTÉ CLIENT — uniquement si le client s'est explicitement engagé. Ne rien y mettre par symétrie.

Structure B — PARTENAIRE
- RELATION PARTENAIRE — état de la relation et actualité du partenaire si évoqués : organisation, recrutements, congés, perspectives. 2 à 3 puces max.
- DOSSIER : [Client final] — un bloc par affaire client évoquée. Dedans, dans cet ordre, chaque élément uniquement s'il a été dit :
  - situation et position du client final (rapportée par qui l'a dit) ;
  - acteurs clés côté client final : qui décide, qui prescrit, qui freine, qui tient le budget — avec nom et fonction quand ils sont donnés ;
  - concurrence : tout concurrent, intégrateur alternatif ou solution de remplacement évoqué, même en passant — c'est un signal majeur, ne jamais l'omettre ;
  - montant : prix, prestation, volumétrie, récurrence rattachés à cette affaire ;
  - avancement commercial : étape de l'affaire au mot près (« on attend le bon de commande », « validé, planifié T1 », probabilité chiffrée si donnée) et prochaine échéance commerciale ;
  - dates : commande, signature, démarrage de prestation, facturation — chacune qualifiée ferme ou (à confirmer) ;
  - décisions prises et prochaine étape. Conclusion en gras si un choix a été fait : → Accord sur… ou → Non tranché : … Les prestations et prix du partenaire restent attribués au partenaire.
- PIPE — bloc présent si le partenaire a donné une vision d'ensemble de ses affaires à venir (nombre de commandes attendues, période, volumétries) : la reprendre chiffrée telle quelle, sans la ventiler par dossier si elle ne l'était pas.
- FONCTIONNEMENT PARTENAIRE — sujets transverses de la relation : commandes, facturation, support, marketing, leads. Même règle de conclusion en gras.
- SUITE — qui fait le prochain pas et quand.
- À FAIRE CÔTÉ BLUEMIND — liste numérotée, porteur nommé si explicite.
- ATTENDU CÔTÉ PARTENAIRE — uniquement si le partenaire s'est explicitement engagé.

Bloc commun à toutes les structures
- CONTACTS — bloc en fin de CR, présent uniquement si de nouvelles coordonnées ou de nouveaux interlocuteurs sont sortis en séance : une puce par personne avec nom, fonction, organisation, email/téléphone tels que donnés. Objectif : création ou mise à jour de fiche dans le CRM. N'y mettre que ce qui a été dit — jamais de coordonnées devinées ou reconstruites.

Structure C — INTERNE

Pas de camps. Participants sur une seule ligne.
- SUJETS — un bloc par sujet abordé, titré, en puces courtes.
- DÉCISIONS — uniquement ce qui a été acté en séance. Une décision = une puce. Ce qui reste ouvert n'y figure pas.
- ACTIONS — liste numérotée : tâche, porteur, échéance si donnée. Porteur nommé uniquement si l'attribution est explicite dans l'échange.
- POINTS EN SUSPENS — questions ouvertes et arbitrages à venir, notés À instruire : …

4. Règles de rédaction (communes)

- Phrases courtes, ton factuel. Pas de style administratif, pas de formules de transition.
- Ne jamais inventer une action, un engagement, une décision ou une date absente de la transcription. Une question restée ouverte se note À instruire : …
- Conserver tels quels : montants, fourchettes, volumétries, nombres d'utilisateurs, dates, protocoles, noms de produits, références clients, adresses email.
- Cohérence des dates : avant d'écrire une date, vérifie qu'elle est compatible avec les autres éléments de l'échange (congés annoncés, échéances, saison évoquée). Une date ambiguë ou incohérente s'écrit avec (à confirmer). Ne jamais classer en ferme une date non confirmée par les deux parties.
- Distinguer le certain de l'hypothétique : un élément évoqué au conditionnel s'écrit comme tel, jamais comme un fait acquis.
- Signaler les points de vigilance commerciaux qui ressortent entre les lignes : exigence réglementaire non chiffrée, dépendance à un tiers, délai intenable, sponsor qui part, opposant identifié, concurrent ou solution alternative évoqué — même en passant, même écarté.
- Toute mention d'étape de signature ou d'avancement d'affaire (« c'est OK, j'attends le bon de commande », « validé, planifié T1 », « opportunité à X % ») se reprend au mot près, rattachée à l'affaire concernée.
- Ignorer les salutations, les apartés personnels, les problèmes de connexion, les digressions. Un aparté à valeur relationnelle va dans SUITE."""


def _cr_bluemind(destination: str, sortie: str) -> str:
    """Assemble un CR BlueMind complet : intro (destination) + corps commun + sortie."""
    intro = ("Tu es assistant chez BlueMind (éditeur français de messagerie collaborative, "
             "alternative à Exchange / Office 365, vente en indirect via des partenaires "
             "intégrateurs). Tu rédiges le compte-rendu d'une réunion à partir d'une "
             f"transcription, destiné à être {destination}.")
    return (f"{intro}\n\n{_CR_BLUEMIND_CORPS}\n\n5. Format de sortie\n\n{sortie}\n\n"
            "Voici la transcription :")


CR_PIPEDRIVE_CONTENU = _cr_bluemind(
    "collé dans une note Pipedrive",
    "- Tous les types (destination : note Pipedrive) — Pipedrive n'interprète pas le markdown. "
    "Utiliser exclusivement : <b>, <i>, <br> et des puces •. Interdits : ---, *, #, listes "
    "markdown, indentation. Les listes numérotées s'écrivent en clair (« 1. », « 2. ») avec "
    "des <br>.\n"
    "- Uniquement le CR, sans bloc de code englobant, sans commentaire avant ou après.")

CR_FULL_MD_CONTENU = _cr_bluemind(
    "enregistré tel quel dans un fichier markdown (.md)",
    "- Tous les types (destination : fichier markdown) — utiliser la syntaxe markdown "
    "standard : blocs en gras (**…**), italique pour les lignes de contexte, listes à "
    "tirets, listes numérotées, séparateurs --- entre les grands blocs.\n"
    "- Uniquement le CR, sans bloc de code englobant, sans commentaire avant ou après.")

# Index du prompt actif par défaut (le CR simple, en position 0).
PROMPT_ACTIF_DEFAUT = 0


def prompts_par_defaut() -> list[dict]:
    """Liste de prompts par défaut (une copie fraîche à chaque appel)."""
    return [
        {"titre": CR_SIMPLE_TITRE, "contenu": CR_SIMPLE_CONTENU},
        {"titre": CR_PIPEDRIVE_TITRE, "contenu": CR_PIPEDRIVE_CONTENU},
        {"titre": CR_FULL_MD_TITRE, "contenu": CR_FULL_MD_CONTENU},
    ]


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
