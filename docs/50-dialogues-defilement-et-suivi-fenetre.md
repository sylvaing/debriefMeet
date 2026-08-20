# 50 — Dialogues : défilement, suivi de fenêtre, listes de participants

> **Statut : À FAIRE — rien n'est codé.** Constaté et instruit le 2026-08-20 sur le
> Mac de Sylvain, à partir de deux captures du dialogue « Associer à un événement »
> ouvert sur un événement à **~34 invités** (« CAIH - Daily Meeting »). Ce document
> fige le diagnostic (déjà fait, code lu) et le plan ; il reste **4 points à trancher
> avec Sylvain avant d'écrire une ligne** (§6).
>
> **Portée :** le gabarit de dialogue partagé (`ui/dialogues.py`) et les dialogues
> BlueMind qui affichent des listes de participants. Aucun impact sur le cœur métier,
> la capture audio ou les pipelines.

---

## 1. Les trois symptômes rapportés

Sur un événement à beaucoup de participants :

1. **Impossible de faire défiler la popup** — la liste des participants est coupée en
   bas de fenêtre.
2. **Pas de « tout cocher / tout décocher »** — il faut décocher les invités un par un
   (ce que Sylvain a fait à la main sur la 2ᵉ capture).
3. **Déplacer la fenêtre debriefMeet laisse la popup et son voile gris sur place** —
   la fenêtre bouge, l'overlay reste.

---

## 2. Diagnostic (code lu le 2026-08-20)

### 2.1 Pas de défilement — et le pied de page devient inatteignable

`CarteFlottante` place la carte dans un `QGridLayout` centré, à **hauteur naturelle**,
sans aucun défilement ([`ui/dialogues.py:90-94`](../src/debrief_meet/ui/dialogues.py#L90)).
Quand le contenu dépasse la hauteur de la fenêtre, le bas est simplement **coupé**.

⚠️ Conséquence plus grave que le symptôme rapporté : ce n'est pas seulement la fin de
la liste qui est perdue, **c'est le pied de page** — « Annuler », « Sans association »,
« Associer » sont hors champ (on le vérifie sur la 1ʳᵉ capture : aucun bouton visible).
Le dialogue devient **inutilisable**, seule la touche Échap en sort. En variante
`contexte_cr` (proposition d'association juste avant un CR Mistral, docs/42 §4.1), cela
signifie qu'un événement à beaucoup d'invités **bloque le parcours de génération du CR**.

Le dialogue de mapping des locuteurs n'a pas ce défaut parce qu'il enveloppe son contenu
dans un `QScrollArea` ([`ui/bluemind_mapping.py:54`](../src/debrief_meet/ui/bluemind_mapping.py#L54)) —
la parade existe déjà dans le dépôt, mais posée **au cas par cas** au lieu d'être dans
le gabarit.

**Dialogues concernés par le même risque** (héritent de `DialogueGabarit`, contenu de
longueur non bornée) :

| Dialogue | Contenu variable | État |
|---|---|---|
| `bluemind_association.py` | liste des invités (cases à cocher) | 🔴 constaté cassé |
| `bluemind_details.py` | liste des invités (libellés) | 🔴 même défaut, non constaté en réel |
| `bluemind_mapping.py` | locuteurs détectés | 🟢 déjà protégé (`QScrollArea` local) |
| `confirmer`/`informer`/`avertir` | textes courts | 🟢 sans risque |

Les dialogues qui héritent de `CarteFlottante` **sans** passer par `DialogueGabarit`
(`assistant_diarization`, `assistant_mistral`, `premier_lancement`) peuplent `corps`
eux-mêmes : le correctif ci-dessous (qui porte sur `zone_corps`) **ne les couvrira
pas** — à vérifier un par un, leur contenu est aujourd'hui de longueur fixe.

### 2.2 Libellés tronqués à droite

La carte est à **largeur fixe** (`setFixedWidth`,
[`ui/dialogues.py:79`](../src/debrief_meet/ui/dialogues.py#L79) ; 440 px pour les deux
dialogues BlueMind) et chaque invité est une `QCheckBox` d'une seule ligne au texte
`Nom <email> — statut` ([`ui/bluemind_association.py:180`](../src/debrief_meet/ui/bluemind_association.py#L180)).
Une `QCheckBox` ne sait pas passer à la ligne : le texte est **coupé net**. Sur la
capture, `prenom.nom@exemple.fr <prenom.nom@exemple.fr> — sa…` — le statut de
participation, qui est l'information utile pour décider de cocher ou non, est
précisément ce qui disparaît.

À noter : `bluemind_details.py` affiche la même information en `QLabel` avec
`setWordWrap(True)` — pas de troncature, mais la ligne prend deux lignes de haut.

### 2.3 La popup ne suit pas la fenêtre

`showEvent` recopie la géométrie de la fenêtre parente **une seule fois**
([`ui/dialogues.py:102-106`](../src/debrief_meet/ui/dialogues.py#L102)) :

```python
def showEvent(self, event):
    super().showEvent(event)
    parent = self.parentWidget()
    if parent is not None:
        self.setGeometry(parent.window().geometry())
```

Le dialogue est une **fenêtre de premier niveau distincte** (`FramelessWindowHint` +
`WA_TranslucentBackground`), pas un widget enfant : rien ne le rattache ensuite à la
fenêtre principale. Déplacer ou redimensionner debriefMeet laisse donc l'overlay grisé
et la carte à leur position d'origine — le voile ne recouvre plus la fenêtre qu'il est
censé désactiver.

---

## 3. Correctifs proposés

### 3.1 Défilement dans le gabarit (priorité 1)

Enrober `zone_corps` d'un `QScrollArea` dans `DialogueGabarit` — **en-tête et pied
restent fixes hors du défilement**, ce qui garantit que les boutons sont toujours
atteignables, quel que soit le contenu.

Point technique à ne pas rater : le `sizeHint` d'un `QScrollArea` est petit, donc tel
quel **tous** les dialogues courts rétréciraient. Il faut une petite sous-classe dont
`sizeHint()` renvoie celui du widget contenu (le `minimumSizeHint` restant petit) : la
carte garde alors sa taille naturelle actuelle quand le contenu tient, et n'est
rétrécie par le layout que lorsque la fenêtre est trop courte — auquel cas la barre de
défilement apparaît. Réglages : `setFrameShape(NoFrame)`, `setWidgetResizable(True)`,
barre horizontale `AlwaysOff`, fond transparent (la carte est blanche).

Bénéfice : la classe de bug disparaît pour **tous** les dialogues du gabarit, pas
seulement l'association BlueMind.

### 3.2 Tout cocher / tout décocher (priorité 2)

Purement local à
[`ui/bluemind_association.py:169-183`](../src/debrief_meet/ui/bluemind_association.py#L169).
Proposition : la ligne « PARTICIPANTS » devient une ligne à deux éléments —
`PARTICIPANTS (12/34)` à gauche, un bouton texte discret à droite qui **bascule** son
libellé selon l'état courant (tout coché → « Tout décocher » ; sinon → « Tout
cocher »), le compteur se mettant à jour à chaque case cochée.

### 3.3 Suivi de la fenêtre parente (priorité 3)

Deux voies, décrites ici parce que le choix est à trancher (§6) :

- **(a) Filtre d'événements** posé par `CarteFlottante` sur `parent.window()` :
  sur `Move`/`Resize`, réappliquer `setGeometry`. ~10 lignes, corrige tous les
  dialogues d'un coup, à désinstaller proprement à la fermeture. Limite connue : sur
  macOS le suivi peut avoir une frame de retard pendant le glissement (l'overlay
  « traîne » légèrement derrière la fenêtre).
- **(b) Overlay enfant** de la fenêtre principale (widget posé par-dessus + boucle
  d'événement locale pour émuler `exec()`) au lieu d'une fenêtre séparée : suivi parfait
  et gratuit, mais refonte de `CarteFlottante` touchant la modalité, `exec()`, les
  6 dialogues qui en héritent et leurs tests.

Recommandation de l'agent : **(a)**, le décalage résiduel pendant le glissement est
cosmétique et sans commune mesure avec le coût de (b).

### 3.4 Lisibilité des lignes de participants (priorité 4)

Deux options, à trancher (§6) :

- **Élargir la carte** de ce dialogue (560-600 px au lieu de 440) — 1 ligne de code,
  ne règle le problème que jusqu'à la prochaine adresse longue.
- **Ligne à deux niveaux** : `case + nom` en 1ʳᵉ ligne, `email — statut` en 2ᵉ ligne
  grise plus petite, email complet en infobulle. Plus lisible sur 34 lignes, aligné sur
  la hiérarchie visuelle des Préférences (DESIGN.md §3), mais impose de remplacer la
  `QCheckBox` simple par une ligne composée (case + colonne de libellés) et de retoucher
  la collecte des états dans `_valider`.

---

## 4. Question de fond soulevée au passage — le défaut « tout coché »

Aujourd'hui **tous** les invités sont pré-cochés
([`ui/bluemind_association.py:181`](../src/debrief_meet/ui/bluemind_association.py#L181)),
choix fait pour des réunions internes à 3-8 personnes. Ces noms partent ensuite dans le
prompt du CR **et** dans le `context_bias` Voxtral. Or on sait déjà, depuis le premier
CR réel avec lexique (correctif du 2026-08-06, cf. mémoire « Lexique de corrections »),
qu'une liste de noms **non présents** pousse le modèle à **inventer des participants**.

Un événement type « CAIH - Daily Meeting » à 34 invités externes, dont une majorité
« sans réponse », est exactement le cas pathologique : Sylvain a décoché les trois
quarts à la main. Deux réponses possibles, à trancher (§6) : s'en remettre au « tout
décocher » de §3.2 (aucun changement de comportement), ou pré-cocher seulement
organisateur + `accepté` au-delà d'un certain nombre d'invités (meilleur défaut, mais
change un comportement établi et validé en réel).

---

## 5. Tests attendus

- **Gabarit** : un `DialogueGabarit` au contenu très haut (N labels) reste dans la
  géométrie du parent et son bouton d'action reste visible/atteignable — c'est le test
  qui aurait attrapé le bug. Un dialogue court garde sa taille naturelle (non-régression
  sur `confirmer`/`informer`/`avertir`).
- **Suivi de fenêtre** : après déplacement simulé du parent (`move()`), la géométrie du
  dialogue suit. Attention en environnement `offscreen` : vérifier que l'événement
  `Move` est bien émis, sinon tester le handler directement.
- **Association** : « tout décocher » met les N cases à `False` et le compteur à `0/N` ;
  re-cliquer recoche tout ; `_valider` reflète bien l'état final dans les
  `InviteAssocie.coche`.
- Rappel environnement : lancer les tests depuis un worktree impose `PYTHONPATH` **et**
  `QT_QPA_PLATFORM=offscreen` (mémoire dédiée), sinon pytest se bloque.

---

## 6. À trancher avec Sylvain avant de coder

> Ces quatre points ne sont **pas** des détails d'implémentation : ils changent le
> comportement visible ou le coût du chantier. **Demander avant d'écrire le code.**

1. **Format des lignes de participants** — élargir la carte (rapide) ou ligne à deux
   niveaux nom / email + statut (plus lisible, plus de travail) ? cf. §3.4
2. **Défaut de cochage** — garder « tout coché » et s'en remettre au bouton « tout
   décocher », ou pré-cocher seulement organisateur + `accepté` au-delà d'un seuil
   d'invités (et lequel) ? cf. §4
3. **Suivi de fenêtre** — filtre d'événements (recommandé) ou refonte en overlay
   enfant ? cf. §3.3
4. **Périmètre** — corrige-t-on aussi `bluemind_details.py` (même défaut de
   débordement, jamais constaté en réel) dans le même chantier ? Le correctif §3.1 étant
   dans le gabarit, il en bénéficie automatiquement : la question porte sur la
   vérification manuelle à faire ou non.

---

## 7. Journal

- **2026-08-20** — symptômes rapportés par Sylvain (2 captures d'écran, dialogue
  d'association sur un événement à ~34 invités). Diagnostic fait sur lecture du code,
  aucun correctif écrit ; document créé, chantier reporté à une session dédiée.
