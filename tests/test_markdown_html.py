"""Conversion markdown → HTML du collage riche (docs/51).

Les trois premières classes figent les écarts **mesurés** entre le markdown que
produit réellement le modèle et CommonMark (docs/51 §3) : ce sont les cas qui
casseraient une implémentation conforme à la spec, donc ceux qui doivent rester
verts si quelqu'un remplace un jour ce module par une bibliothèque.
"""
from __future__ import annotations

from debrief_meet.core.markdown_html import convertir


class TestEcartsMesuresAvecCommonMark:
    def test_gras_avec_espace_avant_le_delimiteur_fermant(self):
        """`**TEXTE **` : forme majoritaire des blocs de CR (199 lignes sur 56
        fichiers). En CommonMark le délimiteur fermant précédé d'une espace n'est
        pas *right-flanking* → pas de gras du tout, marqueurs affichés en clair."""
        assert "<strong>PARTICIPANTS</strong>" in convertir("**PARTICIPANTS **")

    def test_espace_de_bord_rejetee_hors_de_la_balise(self):
        """L'espace absorbée par la capture ressort *après* la balise fermante :
        sinon elle est avalée à l'affichage et colle le mot suivant."""
        html = convertir("le client a demandé **une migration ** avant octobre")
        assert "<strong>une migration</strong> " in html
        assert "<strong>une migration </strong>" not in html

    def test_enveloppe_bloc_de_code_depliee(self):
        """```markdown … ``` : ajouté par le modèle dans 30 des 56 CR mesurés,
        malgré la consigne. Sans dépliage, tout le CR arrive en monospace."""
        html = convertir("```markdown\n**TITRE **\n- un point\n```")
        assert "<strong>TITRE</strong>" in html
        assert "```" not in html
        assert "<code>" not in html

    def test_enveloppe_avec_preambule_et_postambule(self):
        """8 des 56 CR mesurés ont la fence en ligne 2, après une phrase du modèle,
        et des lignes après la fermante — malgré « sans commentaire avant ou après ».
        Ce bavardage est jeté : le garder mettrait une politesse en tête du CR."""
        html = convertir("Voici le compte-rendu :\n\n```markdown\n**TITRE **\n```\n"
                         "N'hésitez pas si vous voulez des précisions.")
        assert "<strong>TITRE</strong>" in html
        assert "compte-rendu" not in html
        assert "précisions" not in html

    def test_fence_tardive_traitee_comme_bloc_interne(self):
        """Au-delà des 3 premières lignes non vides, une fence n'est plus une
        enveloppe : on préfère laisser le document intact que tronquer son début."""
        html = convertir("**TITRE **\nligne\nautre ligne\n\n```\ncode\n```")
        assert "<strong>TITRE</strong>" in html
        assert "ligne" in html

    def test_indentation_de_2_3_ou_4_espaces_donne_le_meme_niveau(self):
        """Les CR mélangent les trois largeurs pour un même niveau, parfois dans
        le même fichier — diviser par une unité fixe produirait des profondeurs
        différentes pour des puces visuellement alignées."""
        rendus = [convertir(f"- parent\n{' ' * n}- enfant") for n in (2, 3, 4)]
        assert rendus[0] == rendus[1] == rendus[2]
        assert rendus[0].count("<ul>") == 2


class TestSousEnsembleConservePipedrive:
    """Seules les balises que Pipedrive conserve réellement doivent être émises
    (mesuré à la balise près sur une note relue par l'API, docs/51 §2)."""

    def test_titre_markdown_rendu_en_gras_pas_en_h1(self):
        """Pipedrive aplatit h1-h3 en <div> : un <h1> perdrait toute distinction
        visuelle, alors que le gras survit partout. 33 des 56 CR ont un titre."""
        html = convertir("# Échange téléphonique — ACME")
        assert "<p><strong>Échange téléphonique — ACME</strong></p>" == html
        assert "<h1>" not in html

    def test_aucune_couleur_ni_style_inline(self):
        """Les styles calculés qu'un navigateur embarque dans le presse-papiers
        ressortaient en `style=" color:rgb"` cassés côté Pipedrive."""
        html = convertir("**BESOIN **\n- un point\n\n---\n\ntexte")
        assert "style=" not in html
        assert "color" not in html

    def test_barre_non_genere(self):
        """`<s>` est purement supprimé par Pipedrive (texte gardé, balise jetée) :
        inutile de produire du barré, la syntaxe reste littérale."""
        assert "<s>" not in convertir("~~abandonné~~")


class TestLegacyHtml:
    """Les 4 CR issus de l'ancien prompt « CR Pipedrive » sont **hybrides** : 5 à 48
    puces markdown *et* 28 à 114 balises inline chacun. Les passer tels quels
    laisserait leurs puces littérales ; les échapper afficherait « &lt;b&gt; »."""

    def test_balises_inline_du_source_conservees(self):
        assert "<b>PARTICIPANTS</b>" in convertir("<b>PARTICIPANTS</b>")

    def test_hybride_puces_markdown_converties_et_balises_gardees(self):
        html = convertir("<b>BESOIN</b>\n- <i>un point</i>\n- un autre")
        assert "<b>BESOIN</b>" in html
        assert "<li><i>un point</i></li>" in html
        assert "<li>un autre</li>" in html

    def test_balise_hors_liste_blanche_reste_echappee(self):
        """Une balise non prévue doit rester visible et inoffensive, jamais active
        — c'est ce qui rend le désescapage sûr."""
        html = convertir("<script>alert(1)</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_br_autoferme_normalise(self):
        assert "<br>" in convertir("une ligne<br />la suivante")


class TestStructure:
    def test_gras_italique_et_code(self):
        html = convertir("**gras** et *italique* et `code`")
        assert "<strong>gras</strong>" in html
        assert "<em>italique</em>" in html
        assert "<code>code</code>" in html

    def test_puces_et_liste_numerotee(self):
        assert convertir("- a\n- b") == "<ul>\n<li>a</li>\n<li>b</li>\n</ul>"
        assert convertir("1. a\n2. b") == "<ol>\n<li>a</li>\n<li>b</li>\n</ol>"

    def test_gras_en_tete_de_puce(self):
        html = convertir("- **Décision :** valider le devis")
        assert "<li><strong>Décision :</strong> valider le devis</li>" in html

    def test_bascule_puces_vers_numerotee_au_meme_niveau(self):
        html = convertir("- a\n1. b")
        assert html == "<ul>\n<li>a</li>\n</ul>\n<ol>\n<li>b</li>\n</ol>"

    def test_puce_orpheline_profonde_ne_cree_quun_niveau(self):
        """Les niveaux étant relatifs à la liste englobante, une puce indentée sans
        puce parente ouvre une liste unique — pas de niveaux intermédiaires vides."""
        assert convertir("      - orpheline") == "<ul>\n<li>orpheline</li>\n</ul>"

    def test_quatre_espaces_imbriquent_vraiment_quand_le_niveau_1_est_a_deux(self):
        """Le pendant du test de tolérance : 2 et 4 espaces dans le MÊME document
        sont deux niveaux distincts. Une profondeur calculée en absolu (« ≥ 2
        espaces ⇒ niveau 1 ») les confondait — c'est ce qui a fait tomber ce test
        et imposé la comparaison relative."""
        html = convertir("- a\n  - b\n    - c")
        assert html.count("<ul>") == html.count("</ul>") == 3

    def test_remontee_de_deux_niveaux_dun_coup(self):
        html = convertir("- a\n  - b\n    - c\n- d")
        assert html.count("<ul>") == html.count("</ul>") == 3
        assert html.endswith("<li>d</li>\n</ul>")

    def test_filet_et_paragraphes(self):
        html = convertir("avant\n\n---\n\naprès")
        assert html == "<p>avant</p>\n<hr>\n<p>après</p>"

    def test_lignes_consecutives_dans_un_meme_paragraphe(self):
        assert convertir("une ligne\nla suivante") == "<p>une ligne<br>la suivante</p>"

    def test_liste_fermee_par_une_ligne_vide(self):
        html = convertir("- a\n\ntexte")
        assert html == "<ul>\n<li>a</li>\n</ul>\n<p>texte</p>"

    def test_toutes_les_listes_sont_refermees(self):
        html = convertir("- a\n  - b\n    - c")
        assert html.count("<ul>") == html.count("</ul>") == 3

    def test_chevrons_et_esperluettes_du_texte_echappes(self):
        """Sans échappement, un `<` du CR casserait le HTML reçu par l'éditeur."""
        html = convertir("marge < 5 % & délai")
        assert "&lt; 5 % &amp;" in html

    def test_document_vide(self):
        assert convertir("") == ""
        assert convertir("\n\n") == ""
