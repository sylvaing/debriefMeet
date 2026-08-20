# 50 — Dialogues : défilement, suivi de fenêtre, listes de participants

> **Statut : À FAIRE — rien n'est codé, mais les arbitrages sont pris.** Constaté et
> instruit le 2026-08-20 sur le Mac de Sylvain, à partir de deux captures du dialogue
> « Associer à un événement » ouvert sur un événement à **~34 invités**
> (« CAIH - Daily Meeting »). Les 4 points ouverts ont été **tranchés le même jour**
> (§6) : le chantier est prêt à être implémenté dans une session dédiée, sans nouvelle
> question bloquante.
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
eux-mêmes : le correctif de défilement (qui porte sur `zone_corps`) **ne les couvrira
pas** — à vérifier un par un, leur contenu est aujourd'hui de longueur fixe. En
revanche, la refonte en overlay enfant (§3.3) les concerne **tous**.

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

## 3. Le chantier (décisions du §6 appliquées)

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
La ligne « PARTICIPANTS » devient une ligne à deux éléments — `PARTICIPANTS (12/34)` à
gauche, un bouton texte discret à droite qui **bascule** son libellé selon l'état
courant (tout coché → « Tout décocher » ; sinon → « Tout cocher »), le compteur se
mettant à jour à chaque case cochée.

Le compteur prend tout son sens avec le nouveau défaut partiel (§3.5) : il rend visible,
sans dérouler la liste, combien d'invités partiront dans le CR.

### 3.3 Suivi de la fenêtre : refonte en overlay enfant (priorité 3) — **décision D3**

`CarteFlottante` cesse d'être une fenêtre de premier niveau : la carte devient un
**widget enfant de la fenêtre hôte**, posé par-dessus, occupant tout son rectangle. Le
suivi du déplacement devient alors **gratuit et exact** (la géométrie est relative au
parent) ; seul le redimensionnement reste à répercuter, par un `resizeEvent` sur l'hôte.

C'est la voie la plus coûteuse des deux étudiées, choisie en connaissance de cause pour
un rendu parfait. Points d'attention à traiter dans la session d'implémentation :

1. **`exec()` doit rester `exec()`** — les 6 dialogues et leurs tests appellent
   `dlg.exec() == QDialog.DialogCode.Accepted`. L'émulation passe par un `QEventLoop`
   local (boucle imbriquée) et doit renvoyer le même code de retour ; `accept()`/
   `reject()` sortent de la boucle. Ne pas casser `_valider` ni `_ignorer`, qui
   appellent `accept()` après avoir écrit sur disque.
2. **⚠️ Changement de modalité, à valider en test manuel** — aujourd'hui
   `setModal(True)` rend le dialogue **modal à toute l'application** : rien d'autre
   n'est cliquable. Un overlay enfant ne bloque, lui, que **sa fenêtre hôte** : il
   deviendrait possible d'ouvrir les Préférences ou une autre fenêtre pendant qu'un
   dialogue est ouvert. Si ce n'est pas acceptable, prévoir de désactiver explicitement
   les autres fenêtres de premier niveau tant que l'overlay est monté (et de les
   réactiver à coup sûr, y compris sur exception).
3. **Deux hôtes possibles** — les dialogues sont ouverts tantôt depuis la fenêtre
   principale, tantôt depuis les Préférences. L'hôte est `parent.window()` ; le cas
   `parent is None` (aucun overlay, dialogue centré sur l'écran) doit **conserver le
   chemin actuel en fenêtre de premier niveau**, sans quoi les appels sans parent
   n'auraient plus de fenêtre du tout.
4. **Le voile change de support** — `paintEvent` peignait `_COULEUR_OVERLAY` sur la
   fenêtre translucide ; il peint désormais sur le widget enfant. `WA_TranslucentBackground`
   et `FramelessWindowHint` n'ont plus lieu d'être sur ce chemin. Vérifier que l'ombre
   portée (`QGraphicsDropShadowEffect`) rend toujours correctement au-dessus d'un fond
   opaque, et sur les 3 OS.
5. **Clavier** — Échap doit continuer à fermer, la tabulation rester piégée dans la
   carte (`setFocus` à l'ouverture), et l'overlay doit avaler les clics destinés à la
   fenêtre en dessous.
6. **Ordre d'empilement** — `raise_()` après montage, et remontage si un widget de
   l'hôte est ajouté ensuite.

Les tests existants qui instancient un dialogue sans l'afficher doivent continuer à
passer : la construction ne doit pas dépendre de la présence d'une fenêtre hôte visible.

### 3.4 Lisibilité des lignes de participants — **décision D1 : élargir la carte**

`largeur_carte` de `DialogAssociationBluemind` passe de **440 à 580 px** ; la
`QCheckBox` mono-ligne est conservée telle quelle. Une infobulle portant le texte
complet est ajoutée sur chaque case — coût nul, et c'est le filet quand une adresse
dépasse quand même la largeur.

Limite assumée : la troncature n'est pas éliminée, seulement repoussée (une adresse
très longue la ramènera), et la carte est plus large qu'il n'est nécessaire sur une
réunion à 3 invités. La variante « ligne à deux niveaux » (nom, puis `email — statut`
en gris) reste la porte de sortie si la troncature réapparaît en usage réel.

`bluemind_details.py` garde sa largeur actuelle : ses libellés passent déjà à la ligne.

### 3.5 Défaut de cochage à seuil — **décision D2**

Aujourd'hui **tous** les invités sont pré-cochés
([`ui/bluemind_association.py:181`](../src/debrief_meet/ui/bluemind_association.py#L181)).
Nouveau comportement :

- **jusqu'à N invités inclus** : tout coché, comme aujourd'hui (les réunions internes à
  3-8 personnes, cas nominal, ne changent pas) ;
- **au-delà de N** : seuls l'**organisateur** et les invités au statut **`accepté`**
  sont pré-cochés ; les « sans réponse », « refusé » et « provisoire » sont décochés, à
  recocher au besoin (le « tout cocher » de §3.2 le fait en un clic).

**N = 12** (valeur retenue par l'agent, à confirmer si Sylvain préfère un autre seuil —
c'est une constante nommée, changeable en une ligne). Motivation : au-delà d'une
douzaine d'invités, on n'est plus sur une réunion d'équipe mais sur une invitation
large, où la majorité des adresses ne correspond à personne ayant réellement parlé.

Le statut est déjà disponible (`part_status`, rendu par `libelle_part_status`) — il
faut décider du mapping exact des libellés vers « accepté » et le figer dans un test,
la valeur brute venant du serveur BlueMind.

**Pourquoi ce changement** : les invités cochés partent dans le prompt du CR **et** dans
le `context_bias` Voxtral. Or on sait, depuis le premier CR réel avec lexique (correctif
du 2026-08-06, cf. mémoire « Lexique de corrections »), qu'une liste de noms **non
présents** pousse le modèle à **inventer des participants**. Un « CAIH - Daily Meeting »
à 34 invités externes majoritairement « sans réponse » est exactement le cas
pathologique — Sylvain a décoché les trois quarts à la main.

---

## 4. Vérifications manuelles attendues

- **Association** sur un événement à ~34 invités : la liste défile, le pied de page
  reste visible, « tout cocher/décocher » fonctionne, le compteur suit, et le défaut
  partiel a bien décoché les « sans réponse ».
- **`bluemind_details`** (décision D4) : ouvrir « Événement associé » sur cette même
  réunion et confirmer que le correctif générique du gabarit suffit — c'est le seul
  point du chantier qui ne sera pas prouvé par un test automatisé.
- **Déplacement/redimensionnement** de la fenêtre principale avec un dialogue ouvert,
  sur les 3 OS si possible (le rendu de l'ombre et du voile change de support).
- **Modalité** (§3.3 point 2) : vérifier explicitement ce qui reste cliquable pendant
  qu'un dialogue est ouvert, et trancher si le comportement diffère de l'actuel.
- Dialogues montés depuis les **Préférences** (fenêtre hôte différente de la principale).

---

## 5. Tests attendus

- **Gabarit** : un `DialogueGabarit` au contenu très haut (N labels) reste dans la
  géométrie de l'hôte et son bouton d'action reste visible/atteignable — c'est le test
  qui aurait attrapé le bug. Un dialogue court garde sa taille naturelle (non-régression
  sur `confirmer`/`informer`/`avertir`).
- **Overlay enfant** : `exec()` renvoie toujours `Accepted`/`Rejected` (les 3 sorties de
  la variante `contexte_cr` en particulier) ; après `resize()` de l'hôte, l'overlay
  couvre toujours tout son rectangle ; `parent=None` conserve le chemin fenêtre centrée.
- **Association** : « tout décocher » met les N cases à `False` et le compteur à `0/N` ;
  re-cliquer recoche tout ; `_valider` reflète bien l'état final dans les
  `InviteAssocie.coche`.
- **Seuil de cochage** : à N invités tout est coché ; à N+1, seuls organisateur et
  `accepté` le sont — et le mapping des statuts est figé par le test.
- Rappel environnement : lancer les tests depuis un worktree impose `PYTHONPATH` **et**
  `QT_QPA_PLATFORM=offscreen` (mémoire dédiée), sinon pytest se bloque.

---

## 6. Décisions actées (2026-08-20, avec Sylvain)

| # | Point | Décision |
|---|---|---|
| **D1** | Format des lignes de participants | **Élargir la carte** (440 → 580 px), `QCheckBox` mono-ligne conservée + infobulle. La ligne à deux niveaux reste en réserve si la troncature revient. cf. §3.4 |
| **D2** | Défaut de cochage | **Seuil** : tout coché jusqu'à N invités, au-delà organisateur + `accepté` seulement. **N = 12** proposé par l'agent, à confirmer. cf. §3.5 |
| **D3** | Suivi de fenêtre | **Refonte en overlay enfant** (et non le filtre d'événements) — suivi parfait, coût assumé sur `exec()`, la modalité et les tests. cf. §3.3 |
| **D4** | Périmètre | **`bluemind_details` inclus**, avec vérification manuelle sur un événement à beaucoup d'invités. cf. §4 |

Seul reliquat : la **valeur de N** (12 par défaut) — constante nommée, à ajuster d'un mot
si Sylvain préfère un autre seuil.

---

## 7. Journal

- **2026-08-20** — symptômes rapportés par Sylvain (2 captures d'écran, dialogue
  d'association sur un événement à ~34 invités). Diagnostic fait sur lecture du code,
  aucun correctif écrit ; document créé, chantier reporté à une session dédiée.
- **2026-08-20** — les 4 points ouverts tranchés (§6) : carte élargie, cochage à seuil,
  overlay enfant, `bluemind_details` inclus. Le document devient exécutable en l'état.
