# Spec — Copie du CR mise en forme (collage riche Pipedrive/webmail)

> **Statut :** ✅ **fusionné dans `main`** (03f5829→1cbbd5d, 2026-08-26) — **1581
> passed, 0 échec** en environnement complet (+45 tests). Validé manuellement par
> Sylvain (collage réel dans une note Pipedrive). Build Windows + fumée automatisée
> **verts** le même soir (`debriefMeet-setup-0.3.0+20260826.1cbbd5d.exe`).
>
> **Besoin :** le prompt « CR Pipedrive » générait des balises `<b>`/`<i>`/`<br>`
> littérales pour contourner le fait que Pipedrive n'interprète pas le markdown —
> mais un copier-coller ordinaire ne pose que du **texte brut** sur le presse-papiers,
> donc ces balises restaient visibles telles quelles au collage : l'éditeur riche ne
> met en forme que ce qu'il reçoit **déjà en HTML**, il n'interprète jamais la syntaxe
> d'un texte collé — ni markdown, ni pseudo-HTML.

---

## 1. Décision actée

Convertir le markdown du CR en HTML **au moment du copier**, et poser les deux
flavors sur le presse-papiers (`text/html` + `text/plain` en repli) — plutôt que de
maintenir un prompt dédié qui produit un format de sortie exotique. Le prompt
« CR Pipedrive » est retiré des défauts (migration config v4, §5) : le « CR full .md »
suffit, sa syntaxe standard étant celle que le convertisseur sait lire.

Alternatives écartées :
- **Garder le prompt Pipedrive, déclarer son contenu HTML au collage** — contournement,
  pas correction : `CR.md` continue de contenir un format qui n'est pas du markdown.
- **Écrire directement dans Pipedrive par l'API** — le champ `content` d'une note
  Pipedrive est bien du HTML, donc le chemin le plus fiable qui existe, mais c'est une
  interco à part entière (calibre BlueMind docs/40). Gardé en tête, hors scope ici.

## 2. Mesure du sous-ensemble HTML conservé par Pipedrive

Avant d'écrire le convertisseur, mesure empirique de ce que l'éditeur de note
Pipedrive **conserve réellement** — pas une inspection visuelle : une note de test
(20 constructions HTML numérotées) a été collée puis enregistrée dans une affaire
réelle, et son `content` relu **à la balise près** via l'API (`getNotes`).

Résultat :

| Construction | Verdict |
|---|---|
| `<h1>`/`<h2>`/`<h3>` | ❌ **aplatis en `<div>`** — aucune distinction visuelle |
| `<strong>`/`<b>`, `<em>`/`<i>`, `<u>` | ✅ conservés |
| `<ul>`/`<ol>`/`<li>`, imbrication | ✅ conservée |
| `<hr>`, `<p>` distincts, `<br>` | ✅ |
| `<a href>` (http + mailto) | ✅ (Pipedrive ajoute `rel="noopener"`) |
| `<blockquote>`, `<code>` | ✅ |
| `<s>` (barré) | ❌ supprimé (texte gardé, balise jetée) |
| `<table>` | ✅ réécrit en `class="page_table"`, styles inlinés |

Conséquence directement exploitable : le CR BlueMind ne s'appuie **jamais** sur des
niveaux de titre — structure entièrement portée par le gras (« Titre en gras »,
« Blocs en majuscules et en gras », « conclusion en gras », cf. `core/prompts.py`). Le
seul refus qui compte (les titres) ne concerne donc aucune construction utilisée.
D'où le choix du convertisseur : `#`/`##`/`###` → `<p><strong>…</strong></p>` plutôt
que `<h1>` — dégrader vers du gras, qui survit partout, vaut mieux que dégrader vers
rien.

## 3. Calibrage sur les CR réels du poste (pas sur CommonMark)

Le convertisseur (`core/markdown_html.py`) n'implémente pas CommonMark : il lit le
**dialecte que produit réellement le modèle**, mesuré sur les 56 `CR.md` du poste de
référence (formes de lignes seulement, aucun contenu inspecté). Trois écarts, chacun
casserait une implémentation conforme à la spec :

1. **`**TEXTE **` — délimiteur fermant précédé d'une espace.** Forme majoritaire
   (199 lignes/56 fichiers) — c'est la construction centrale du CR (blocs en gras). En
   CommonMark ce délimiteur n'est pas *right-flanking* → pas de gras du tout, marqueurs
   affichés en clair. Le convertisseur est délibérément permissif : l'espace de bord
   est rejetée **hors** de la balise plutôt que d'invalider le gras.
2. **Enveloppe ` ```markdown … ``` ` malgré la consigne contraire.** 30 des 56 CR
   (54 %) sont enveloppés ; 8 ont en plus un préambule du modèle avant la fence et du
   bavardage après (« Voici le compte-rendu : », « N'hésitez pas… »). Le dépliage jette
   ce bavardage — c'est précisément ce que le prompt interdit. La fence n'est cherchée
   que dans les 3 premières lignes non vides : au-delà, c'est un bloc de code interne,
   qu'on laisse intact plutôt que de risquer de tronquer le document.
3. **Indentation des sous-puces à 2, 3 *et* 4 espaces**, parfois dans un même fichier.
   Une profondeur calculée en absolu confond alors un vrai deuxième niveau avec un
   premier niveau ailleurs. Les niveaux sont comparés **relativement** à la liste
   englobante (tolérance de 2 espaces), comme le font les vrais analyseurs markdown.

**CR legacy hybrides** : les 4 fichiers issus de l'ancien prompt Pipedrive contiennent
*à la fois* 5 à 48 puces markdown et 28 à 114 balises inline littérales chacun — un
passage « tel quel » aurait laissé leurs puces non converties. Traité par
désescapement limité à une liste blanche (`b`/`strong`/`i`/`em`/`u`/`br`) : toute
autre balise du source (y compris `<script>`) reste échappée, donc visible et
inoffensive — c'est ce qui rend le désescapement sûr sans sniffer le format du
fichier.

Validation : les 56 CR du poste convertissent sans anomalie mesurable (balises
équilibrées, aucun marqueur `**`/puce/titre/fence résiduel, aucun style inline).

## 4. UI — split button de copie (Historique réunions)

Le bouton de copie de la ligne réunion devient un split button, sur le modèle exact
de « Générer le CR ▾ » :
- **Clic direct** → copie **mise en forme** (nouveau défaut) : c'est le geste courant
  (coller dans une note Pipedrive, un mail, un document).
- **Flèche ▾** → menu à deux entrées, « Copier le CR mis en forme » et « Copier le CR »
  (brut) — la flèche liste les deux formats, celui du bouton compris, comme la flèche
  de « Générer le CR » liste tous les prompts sans exclure l'actif.
- La flèche reste **peinte même sans CR disponible** (colonne de géométrie constante)
  mais **inerte** : son état actif dérive de celui du bouton (`ActionsDelegate.
  _zone_active`), qui la grise quand `cr_disponible` est faux.
- Menu ⋯ exhaustif : les deux formats y figurent comme deux items distincts.

`copier()` (transcription, journal, dictée) reste strictement inchangé — texte brut
uniquement, aucun flavor HTML, sous peine de casser le collage dans un éditeur
markdown ou un terminal.

⚠️ **`NB_FLECHES_REUNION` passe de 1 à 2.** Piège déjà mordu le 2026-08-24 (bouton
peint par-dessus l'icône calendrier voisine, colonne sous-dimensionnée) —
`test_largeur_colonne_journal_et_reunion` ne peut pas le voir (il vérifie la formule,
jamais le nombre de boutons qu'on lui passe) ; le garde-fou vit côté vue
(`test_colonne_actions_dimensionnee_pour_les_boutons_reellement_produits`), avec un CR
réellement écrit dans la fixture — sans lui le test ne couvre plus le pire cas si la
flèche de copie devenait un jour conditionnelle, et passerait quand même, en silence.

## 5. Presse-papiers — `copier_riche(html, texte)`

Nouvelle méthode sur l'interface `PressePapiers`, implémentation **commune aux 3 OS**
dans `platform/commun/presse_papiers_riche.py` : Qt traduit `text/html` vers le format
natif de chaque plate-forme (`public.html` macOS, `CF_HTML` Windows, `text/html`
X11/Wayland) en une seule opération `QMimeData`. macOS quitte `pbcopy` pour ce
chemin — `pbcopy` n'écrit que du texte brut, il ne peut pas porter de flavor HTML.

## 6. Migration config v4 — retrait du prompt Pipedrive

`prompt_actif` est un **index**, pas un nom : retirer un prompt décale tout ce qui
suit. C'est précisément pour éviter ça que la migration v2 n'ajoutait qu'en fin de
liste (cf. docs incluant ce piège pour le CR simple). La v4 :

1. Ne retire le prompt que s'il est **resté identique au défaut**
   (`CR_PIPEDRIVE_CONTENU_V2`, conservée dans `core/prompts.py` pour cette seule
   comparaison — sur le modèle de `CR_SIMPLE_CONTENU_V1`). Un prompt retouché
   appartient à l'utilisateur, il n'est jamais touché.
2. Recale `prompt_actif` : décrémenté s'il pointait après le prompt retiré, ramené à
   `PROMPT_ACTIF_DEFAUT` s'il pointait dessus.

Effet de bord assumé : pour une config encore en v0/v1, la migration v2 ajoute
toujours le prompt Pipedrive en fin de liste, que la v4 retire aussitôt dans la même
passe. Volontairement laissé tel quel — une migration passée est un enregistrement de
ce qui a joué sur les postes déjà migrés ; la réécrire fausserait ce qu'elle a
signifié.

## 7. Découpage des commits

1. `03f5829` — convertisseur `core/markdown_html.py` (pur, testé isolément sur les
   trois écarts CommonMark mesurés).
2. `5471ebc` — `copier_riche` (interface + commun + 3 adaptateurs + stub).
3. `3b12322` — split button de l'Historique.
4. `1cbbd5d` — retrait du prompt Pipedrive + migration v4.

Chacun vert indépendamment.
