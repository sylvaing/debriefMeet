"""Conversion markdown → HTML pour le collage riche du CR (docs/51).

Le CR est stocké en markdown (`CR.md`), mais un éditeur riche — note Pipedrive,
webmail, traitement de texte — ne met en forme que ce qu'il reçoit **en HTML**
sur le presse-papiers : du markdown collé en texte brut reste littéral, `**gras**`
marqueurs compris. D'où ce module, appelé au moment du copier (`PressePapiers.
copier_riche`), jamais à la génération : le fichier sur disque reste du markdown.

Fonctions pures, aucune dépendance — le sous-ensemble à couvrir est petit et
**fermé** : il est borné par ce que l'éditeur de note Pipedrive conserve
réellement (mesuré à la balise près sur une note de test relue par l'API, cf.
docs/51 §2). Ce qu'il jette, il est inutile de le produire :

- conservés : ``strong``/``b``, ``em``/``i``, ``u``, ``p``, ``br``, ``ul``/``ol``/``li``
  (imbrication comprise), ``hr``, ``a``, ``blockquote``, ``code``, ``table`` ;
- **aplatis en ``div``** : ``h1``…``h3`` — d'où le choix de rendre les titres
  markdown en paragraphe gras plutôt qu'en ``<h1>`` (`_TITRE`) : dégrader vers du
  gras, qui survit partout, vaut mieux que dégrader vers rien ;
- **supprimé** : ``s`` (barré) — la syntaxe ``~~…~~`` n'est donc pas gérée.

Le dialecte accepté est celui que **produit réellement le modèle**, pas
CommonMark : mesuré sur les 56 CR du poste de référence (docs/51 §3), il s'en
écarte sur trois points qui casseraient une implémentation conforme à la spec.
Chacun est traité explicitement ci-dessous — cf. `_MOTIF_GRAS`, `_deplier_enveloppe`
et `_niveau_indentation`.
"""
from __future__ import annotations

import html
import re

# Enveloppe ```markdown … ``` : le modèle l'ajoute malgré la consigne « sans bloc de
# code englobant » dans **30 des 56** CR mesurés (docs/51 §3). Sans ce dépliage, tout
# le CR arrive en bloc monospace — et c'est déjà ce que la copie brute colle
# aujourd'hui, backticks compris. La fence ouvrante n'est pas forcément en ligne 1
# (30 fichiers l'ont en tête, 32 se terminent par une fence) : on la cherche dans les
# premières lignes non vides.
_MOTIF_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*$")

# Gras et italique **permissifs par choix**. En CommonMark, un délimiteur fermant
# précédé d'une espace n'est pas *right-flanking* : `**TEXTE **` ne rend pas en gras.
# Or c'est la forme majoritaire des blocs de CR — 199 lignes sur les 56 fichiers
# mesurés. Une implémentation conforme à la spec afficherait donc les marqueurs en
# clair sur la construction centrale du document. L'espace est absorbée dans la
# capture puis rendue après la balise fermante, pour ne pas coller le mot suivant.
_MOTIF_GRAS = re.compile(r"\*\*(?!\s*\*\*)(.+?)\*\*")
_MOTIF_ITALIQUE = re.compile(r"(?<![*\w])\*(?!\s*\*)([^*\n]+?)\*(?!\*)")
_MOTIF_CODE = re.compile(r"`([^`\n]+)`")

# Écart d'indentation à partir duquel une puce compte comme imbriquée dans la
# précédente. Les niveaux sont comparés **relativement** à la liste englobante, pas
# convertis en profondeur absolue : les CR mesurés mélangent 2, 3 et 4 espaces
# (docs/51 §3), si bien qu'une largeur donnée ne désigne pas le même niveau d'un
# fichier à l'autre — 4 espaces est un deuxième niveau là où le premier est à 2, et
# un premier niveau ailleurs. La tolérance absorbe le flottement de 2 à 3 espaces
# pour un même niveau sans confondre 2 et 4.
_TOLERANCE_INDENT = 2

_MOTIF_TITRE = re.compile(r"^(#{1,6})\s+(.*)$")
_MOTIF_PUCE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_MOTIF_NUMERO = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_MOTIF_FILET = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")

# Balises inline déjà présentes dans le source, restaurées après échappement. 4 des
# 56 CR mesurés en contiennent : ceux produits par l'ancien prompt « CR Pipedrive »,
# qui réclamait des <b>/<i>/<br> littéraux (prompt retiré, fichiers toujours sur
# disque). Les échapper afficherait « &lt;b&gt; » dans la note.
#
# Ces fichiers sont **hybrides** — 5 à 48 puces markdown *et* 28 à 114 balises inline
# chacun : les passer tels quels laisserait leurs puces littérales. On convertit donc
# normalement et on ne rend leur forme qu'à cette liste blanche ; toute autre balise
# du source reste échappée, donc visible et inoffensive.
_TAGS_AUTORISES = ("b", "strong", "i", "em", "u", "br")
_MOTIF_TAG_ECHAPPE = re.compile(
    r"&lt;(/?(?:" + "|".join(_TAGS_AUTORISES) + r"))\s*/?&gt;", re.IGNORECASE)


def _echapper(texte: str) -> str:
    """Échappe tout, puis rend leur forme aux seules balises de `_TAGS_AUTORISES`."""
    return _MOTIF_TAG_ECHAPPE.sub(
        lambda m: f"<{m.group(1).lower()}>", html.escape(texte, quote=False))


def _inline(texte: str) -> str:
    """Balisage intra-ligne, après échappement — l'ordre compte : le code littéral
    d'abord (son contenu ne doit pas être re-balisé), puis gras avant italique
    (sinon `**` serait mangé par le motif italique)."""
    rendu = _echapper(texte)
    rendu = _MOTIF_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", rendu)
    rendu = _MOTIF_GRAS.sub(_baliser("strong"), rendu)
    rendu = _MOTIF_ITALIQUE.sub(_baliser("em"), rendu)
    # `_baliser` rejette hors de la balise l'espace de bord de capture : en fin de
    # ligne elle ne sert plus à rien (`**TITRE **` donnerait `<strong>TITRE</strong> `),
    # et une espace de bord n'a de toute façon aucun sens en HTML.
    return rendu.strip()


def _baliser(balise: str):
    """Remplacement qui rejette hors de la balise les espaces de bord de capture :
    `**TEXTE **` donne `<strong>TEXTE</strong> `, jamais `<strong>TEXTE </strong>`
    (l'espace interne serait avalée à l'affichage, collant le mot suivant)."""
    def remplacer(m: re.Match) -> str:
        contenu = m.group(1)
        if not contenu.strip():
            return m.group(0)
        gauche = " " if contenu[:1].isspace() else ""
        droite = " " if contenu[-1:].isspace() else ""
        return f"{gauche}<{balise}>{contenu.strip()}</{balise}>{droite}"
    return remplacer


def _deplier_enveloppe(lignes: list[str]) -> list[str]:
    """Retire l'enveloppe ```markdown … ``` quand le document entier est dedans, en
    jetant au passage le bavardage du modèle autour d'elle.

    L'enveloppe n'est pas toujours en tête : sur 8 des 56 CR mesurés, le modèle a
    écrit un préambule (« Voici le compte-rendu : ») avant la fence et laissé des
    lignes après la fermante, malgré la consigne « sans commentaire avant ou après ».
    Ce bavardage est jeté — c'est précisément ce que le prompt interdit, et le garder
    mettrait une phrase de politesse en tête de chaque CR collé.

    Une fence ouvrante est cherchée dans les 3 premières lignes non vides seulement :
    au-delà, c'est un bloc de code interne, et on préfère laisser le document intact
    plutôt que de risquer d'en tronquer le début."""
    non_vides = [i for i, l in enumerate(lignes) if l.strip()]
    debut = next((i for i in non_vides[:3] if _MOTIF_FENCE.match(lignes[i])), None)
    if debut is None:
        return lignes
    fin = next((i for i in reversed(non_vides) if i > debut and _MOTIF_FENCE.match(lignes[i])), None)
    if fin is None:
        return lignes
    return lignes[debut + 1:fin]


def _largeur_indentation(blancs: str) -> int:
    return len(blancs.replace("\t", "    "))


def convertir(markdown: str) -> str:
    """Rend `markdown` en HTML collable dans un éditeur riche.

    Renvoie un fragment (pas de `<html>`/`<body>`) sans aucune couleur ni style
    inline : c'est volontaire — les styles calculés qu'un navigateur embarque dans
    le presse-papiers ressortaient en `style=" color:rgb"` cassés côté Pipedrive
    (docs/51 §2)."""
    lignes = _deplier_enveloppe(markdown.splitlines())
    sortie: list[str] = []
    # Listes ouvertes, de la plus externe à la plus interne : (balise, indentation
    # de ses puces). Garder l'indentation permet de situer la puce suivante par
    # comparaison plutôt que par calcul de profondeur — cf. `_TOLERANCE_INDENT`.
    pile: list[tuple[str, int]] = []
    paragraphe: list[str] = []

    def vider_paragraphe() -> None:
        if paragraphe:
            sortie.append(f"<p>{'<br>'.join(paragraphe)}</p>")
            paragraphe.clear()

    def fermer_listes(profondeur: int = 0) -> None:
        while len(pile) > profondeur:
            sortie.append(f"</{pile.pop()[0]}>")

    def ouvrir_liste(balise: str, largeur: int) -> None:
        sortie.append(f"<{balise}>")
        pile.append((balise, largeur))

    for ligne in lignes:
        if not ligne.strip():
            vider_paragraphe()
            fermer_listes()
            continue

        if _MOTIF_FILET.match(ligne) and not _MOTIF_GRAS.search(ligne):
            vider_paragraphe()
            fermer_listes()
            sortie.append("<hr>")
            continue

        titre = _MOTIF_TITRE.match(ligne)
        if titre:
            vider_paragraphe()
            fermer_listes()
            # Pipedrive aplatit h1-h3 en <div> : un titre rendu en <h1> perdrait
            # toute distinction visuelle. Le gras, lui, survit partout.
            sortie.append(f"<p><strong>{_inline(titre.group(2))}</strong></p>")
            continue

        puce = _MOTIF_PUCE.match(ligne)
        numero = None if puce else _MOTIF_NUMERO.match(ligne)
        if puce or numero:
            m = puce or numero
            balise = "ul" if puce else "ol"
            largeur = _largeur_indentation(m.group(1))
            vider_paragraphe()
            # Refermer les listes dont les puces sont plus indentées que celle-ci :
            # on remonte d'un ou plusieurs niveaux d'imbrication.
            while pile and pile[-1][1] - largeur >= _TOLERANCE_INDENT:
                fermer_listes(len(pile) - 1)
            if not pile or largeur - pile[-1][1] >= _TOLERANCE_INDENT:
                ouvrir_liste(balise, largeur)          # niveau plus profond
            elif pile[-1][0] != balise:
                # Bascule de type au même niveau (des tirets qui deviennent une
                # liste numérotée, ou l'inverse) : refermer avant de rouvrir, sinon
                # les <li> des deux styles atterrissent dans la même liste.
                fermer_listes(len(pile) - 1)
                ouvrir_liste(balise, largeur)
            sortie.append(f"<li>{_inline(m.group(2))}</li>")
            continue

        # Ligne de texte ordinaire : accumulée, les lignes consécutives d'un même
        # bloc étant séparées par <br> (et non par un paragraphe chacune).
        fermer_listes()
        paragraphe.append(_inline(ligne.strip()))

    vider_paragraphe()
    fermer_listes()
    return "\n".join(sortie)
