# debriefMeet — Guide de design

> Référence visuelle et d'implémentation pour l'application de bureau **debriefMeet** (Qt, macOS / Windows / Linux).
> Direction retenue : **C** — typographie *IBM Plex*, accent *indigo*, structure « barre d'outils + tableau ».

Ce document est la source de vérité pour les couleurs, la typographie, l'espacement, les composants et leurs états. Toute nouvelle vue doit réutiliser ces tokens plutôt que d'introduire des valeurs ad hoc.

---

## 1. Principes

1. **Neutre et professionnel, avec une identité.** Chrome sobre, une seule couleur d'accent, hiérarchie portée par la typo et l'espacement — pas par des aplats de couleur.
2. **Une seule fenêtre, navigation par type.** Trois onglets de type (**Réunion · Dictée · Journal**) + un bouton **Préférences** (engrenage) à droite de la barre. Il n'y a **pas** d'onglet « Historique » global : chaque type affiche **son propre historique** (sauf Dictée, sans historique), précédé d'un bouton **Démarrer / Arrêter** l'enregistrement. On navigue entre tout sans repasser par le tray.
3. **La couleur encode l'état, pas la décoration.** Rouge = enregistrement, vert = transcrit, etc. On n'utilise jamais ces couleurs comme ornement.
4. **Cross-platform maison.** Look identique sur les trois OS, avec quelques concessions aux conventions système (voir §10).
5. **Densité maîtrisée.** Lignes de tableau à hauteur fixe, marges régulières, monospace pour toute donnée technique (dates, durées, chemins, raccourcis).

---

## 2. Couleurs / tokens

### 2.1 Accent (indigo)

| Token | Hex | Usage |
|---|---|---|
| `accent` | `#3B5BDB` | Actions primaires, onglet actif, logo, focus |
| `accent-ink` | `#2A46B8` | Texte/icône sur fond clair, survol d'accent |
| `accent-soft` | `#EEF1FE` | Fonds sélectionnés, pastilles, hover discret |

### 2.2 Neutres (texte & surfaces)

| Token | Hex | Usage |
|---|---|---|
| `ink-900` | `#1A1D23` | Texte principal, titres |
| `ink-700` | `#344054` | Libellés de formulaire |
| `ink-600` | `#475467` | Texte secondaire fort |
| `ink-500` | `#667085` | Texte secondaire |
| `ink-400` | `#7A828F` | Texte tertiaire / légendes |
| `ink-350` | `#8A919E` | Métadonnées mono (dates, durées) |
| `ink-300` | `#98A2B3` | Icônes au repos, placeholders |
| `ink-200` | `#B0B7C0` | Icônes désactivées, séparateurs mono |
| `surface` | `#FFFFFF` | Fond des panneaux, lignes |
| `surface-sunken` | `#F6F7F9` | Champs, cellules « choisir », sidebar |
| `surface-header` | `#FBFBFC` | En-tête de tableau, barre auto-save |
| `surface-hover` | `#FAFAFB` | Survol de ligne |
| `border` | `#E7E9EE` | Bordures de champs, cartes, séparateurs |
| `border-soft` | `#EFF1F4` | Séparateurs internes |
| `divider` | `#F1F2F5` | Filets de lignes de tableau |

### 2.3 Couleurs sémantiques (états)

| État | Texte/icône | Fond pastille |
|---|---|---|
| Enregistrement / En cours | `#FF3B30` | `#FFECEA` |
| Succès / Transcrit / Diarization OK | `#1F9D6B` | `#E7F6EF` |
| Neutre / Audio seul | `#7A828F` | `#F1F2F5` |
| Info / Locuteurs | `#3B5BDB` (accent) | `#EEF1FE` |
| Danger / destructif | `#B42318` | `#FEF3F2` (bordure `#F4C9C7`) |

> **Règle :** le rouge `#FF3B30` est réservé à l'activité d'enregistrement (écran, badge, boutons de la barre, icône du tray). Le rouge `#B42318` est réservé aux actions destructives (supprimer, vider le log).

---

## 3. Typographie

Deux familles seulement.

| Rôle | Famille | Graisses |
|---|---|---|
| Interface | **IBM Plex Sans** | 400, 500, 600, 700 |
| Données techniques | **IBM Plex Mono** | 400, 500 |

**IBM Plex Mono** est obligatoire pour : dates, heures, durées, chronomètre, chemins de fichiers, noms de fichiers `.md`, raccourcis clavier, numéros de version, noms de modèles.

### Échelle

| Style | Taille / graisse | Exemple |
|---|---|---|
| Titre de section (écran enregistrement) | 20 px / 700 | « Réunion en cours » |
| Chronomètre | 42 px / 500 mono | `03:12` |
| Onglet de navigation | 14 px / 600 | Historique |
| Titre de ligne | 13.5 px / 600 | Acme — discussion devis |
| Libellé de formulaire | 12.5 px / 600 | Microphone |
| Corps / valeur | 13–14 px / 400–500 | Périphérique par défaut |
| Métadonnée mono | 12 px / 400 mono | `03/07/2026 · 14:22` |
| En-tête de colonne | 10.5 px / 500 mono, `letter-spacing: .06em`, MAJUSCULES | `DURÉE` |
| Badge d'état | 12 px / 600 | Transcrit |

Interlignage des paragraphes d'aide : **1.7**. Couleur : `ink-400`.

---

## 4. Espacement, rayons, ombres

### Grille d'espacement (multiples de 4)
`4 · 6 · 8 · 10 · 12 · 14 · 16 · 20 · 24 · 28 · 30`

Repères d'implémentation :
- Padding horizontal des zones de contenu : **20 px** (tableau) à **30 px** (formulaires de préférences).
- Hauteur de ligne de tableau : **52 px**.
- Hauteur de barre d'outils : **58 px** ; titlebar : **40 px**.
- Gap entre champs de formulaire : **20 px** ; entre label et champ : **6 px**.

### Rayons
| Élément | Rayon |
|---|---|
| Fenêtre | 12 px |
| Cartes / champs / listes | 8–9 px |
| Boutons | 7–9 px |
| Pastilles d'icône, petites tuiles | 7 px |
| Badges d'état (pilule) | 20 px |
| Cases à cocher | 5 px |
| Puces / points d'état | 50 % |

### Ombres
- **Fenêtre (maquette) :** `0 30px 70px -24px rgba(16,24,40,.42)` + contour `0 0 0 1px rgba(16,24,40,.07)`.
- **Popover / menu tray :** `0 20px 44px -14px rgba(16,24,40,.40)`.
- **Bouton d'action en survol (dans une ligne) :** `0 1px 3px rgba(16,24,40,.14)` sur fond blanc.
- En usage courant, éviter les ombres portées sur les éléments plats : préférer les bordures `border`.

---

## 5. Iconographie

- Bibliothèque : **[Phosphor Icons](https://phosphoricons.com/)**, style **Regular** (le poids `filled` est réservé à l'état actif de l'icône tray et aux puces `ph-record-fill`).
- Tailles : **13 px** (dans un badge), **15–16 px** (boutons/onglets), **17–18 px** (icône de ligne, actions).
- Couleur par défaut : `ink-300` au repos, `accent-ink` au survol/actif.

Icônes de référence :

| Sens | Icône Phosphor |
|---|---|
| Dictée | `ph-microphone` |
| Réunion | `ph-users-three` |
| Journal | `ph-notebook` |
| Historique | `ph-clock-counter-clockwise` |
| Préférences | `ph-gear` |
| Copier | `ph-copy` · Ouvrir CR | `ph-file-text` · Dossier | `ph-folder` |
| Locuteurs / diarization | `ph-users-three` |
| Transcrit / succès | `ph-check-circle` |
| Audio seul | `ph-waveform` |
| En cours | `ph-record-fill` |
| Supprimer | `ph-trash` |
| Menu d'actions (overflow) | `ph-dots-three-vertical` |
| Nommer les locuteurs | `ph-chat-text` |
| Lien calendrier — associable | `ph-calendar-plus` |
| Lien calendrier — associé | `ph-calendar-check` |

---

## 6. Le logo & l'icône d'application (WaveMark)

Marque unique : un **carré arrondi contenant quatre barres d'onde** de hauteurs `29 % · 50 % · 23.5 % · 41 %` de la taille.

Deux traitements :
- **Rempli** (`filled`) — carré plein en couleur, ondes blanches. Utilisé pour le logo dans l'app et l'icône du **Dock / barre des tâches**.
  - Fond = `accent` ; ombre douce `0 4px 10px -4px accent80`.
- **Contour** (`template`) — fond transparent, contour + ondes monochromes. Utilisé pour l'**icône de la barre d'état (tray)** au repos, afin de s'adapter aux barres claires comme sombres (icône *template* Qt).

Proportions : rayon du carré `≈ 0.27 × taille`, largeur de barre `≈ 0.088 × taille`, gap `≈ 0.072 × taille`, épaisseur de contour `≈ 0.06 × taille`.

---

## 7. Système d'états de l'icône du tray

L'icône est **constante** ; **seule la couleur encode l'activité** (pas le mode). C'est le retour visuel principal quand la fenêtre est fermée.

| État | Couleur | Traitement |
|---|---|---|
| **Repos** | `#3D4351` | Contour monochrome (template) — s'adapte au thème de la barre |
| **Enregistrement** | `#FF3B30` | Rempli |
| **Transcription** | `#FF9500` | Rempli |
| **Terminé** (bref) | `#34C759` | Rempli, ~1,5 s puis retour au repos |
| **Erreur** (bref) | `#8E8E93` | Rempli, puis retour au repos |

**Cycles :**
- **Dictée / Journal :** Repos → 🔴 Enregistrement → 🟠 Transcription (à l'arrêt) → 🟢 Terminé → Repos.
- **Réunion :** 🔴 en continu pendant la capture, 🟢 bref à l'arrêt.

L'icône du **Dock** reste le carré accent rempli (elle n'encode pas l'état).

### Comportements du clic
- **Clic gauche** → ouvre / met au premier plan la fenêtre debriefMeet.
- **Clic droit** → menu contextuel d'actions (Démarrer Dictée / Réunion / Journal, Ouvrir debriefMeet, Préférences…, Quitter). *(plus d'entrée « Historique… » : l'historique vit dans chaque onglet de type.)*

---

## 8. Composants

### 8.1 Barre d'outils (haut de fenêtre)
Hauteur 58 px, fond `surface`, bordure basse `border`. De gauche à droite : WaveMark (26 px) + wordmark + badge version mono ; **3 onglets de navigation** (Réunion · Dictée · Journal) ; *(spacer)* ; **bouton engrenage** (Préférences, icône seule) ; icône d'état (WaveMark 24 px).

**Onglet de navigation :** icône Phosphor 16 px + label 14 px/600. `ink-400` au repos, `accent-ink` + soulignement `2px accent` à l'actif. *(Les onglets ne portent aucun indicateur d'enregistrement ; l'état est signalé par l'icône d'état de la barre + le bouton Arrêter de la section.)*

**Préférences :** un simple bouton **icône engrenage** (`ph-gear`, 18 px, tuile 34×34, rayon 8 px) placé à droite du spacer — pas de gros bouton ni de label. Actif : fond `accent-soft`, icône `accent-ink` ; repos : icône `ink-400`.

> ⚠ Changement d'IA : l'ancien onglet « Historique » et l'ancien « groupe de démarrage segmenté » à droite de la barre sont **supprimés**. Le démarrage se fait désormais **dans chaque section** (§8.2).

### 8.2 Section de capture (Dictée / Réunion / Journal)
Chaque onglet de type ouvre une section construite de la même façon :

1. **Barre d'action** (haut de section, filet bas `border-soft`) : à gauche le bouton **Démarrer / Arrêter** ; pendant la capture, **à côté du bouton Arrêter** : un **point pulsant** rouge + le **chronomètre mono** (`#FF3B30`, 15 px). Quand ≥ 2 lignes sont sélectionnées dans l'historique, une **barre d'actions en masse** (§8.6.4) apparaît juste après le bouton Démarrer. À droite : le champ de recherche (§8.4).
2. **Historique du type** — tableau des captures (§8.6) pour **Réunion**, liste de fichiers pour **Journal**, directement sous la barre d'action. Pendant un enregistrement de réunion, une **ligne « Réunion en cours »** (badge *En cours*, §9) est insérée **en tête** du tableau, sa durée affichant le chronomètre live ; elle bascule vers son état final à l'arrêt.

> **Cas Dictée :** la dictée **copie le texte transcrit dans le presse-papiers** — elle **n'a ni recherche ni historique**. La section affiche seulement le bouton **Démarrer la dictée** + un **état explicatif centré** (tuile micro `accent-soft`, titre « Dictée vocale », rappel du raccourci `⌃⌥⌘D`).

**Bouton Démarrer / Arrêter** (bascule) :
- **Au repos → Démarrer :** bouton **primaire** (`accent`, texte blanc, rayon 9 px), icône du type + libellé « Démarrer la dictée / réunion / journal ».
- **En cours (ce type) → Arrêter :** fond `#FF3B30`, texte blanc, icône `ph-stop-fill` ; suivi (hors bouton) du point pulsant + chronomètre décrits ci-dessus.
- **Un autre type enregistre :** bouton grisé (`surface-sunken`, texte `ink-300`, curseur par défaut) + mention « Un enregistrement est déjà en cours. » *(un seul enregistrement à la fois)*.

> Il n'y a **pas** de fenêtre / bandeau « enregistrement en cours » (waveform, gros chrono, transcription live) : pendant la capture, seuls l'état de la barre, le bouton Arrêter et son chrono le signalent ; l'historique du type reste affiché.

### 8.3 Boutons
| Type | Fond | Texte | Bordure |
|---|---|---|---|
| Primaire | `accent` | `#fff` | — |
| Secondaire | `#fff` | `ink-700` | `#D6D9DE` (survol → `accent`) |
| Destructif | `#fff` | `#B42318` | `#F4C9C7` (survol fond `#FEF3F2`) |
| Danger plein (Arrêter) | `#FF3B30` | `#fff` | ombre `0 6px 16px -6px #FF3B30` |

Padding ≈ `10px 18px`, rayon 9 px, poids 600.

### 8.4 Champs de formulaire
Fond `surface-sunken`, bordure `border`, rayon 8 px, padding `10–11px 13–14px`, texte 13.5–14 px. Selects : chevron `ph-caret-up-down` `ink-300` à droite. Valeurs techniques en **mono**. Zone de texte de prompt : contenu en **mono** 12.5 px, interligne 1.6.

### 8.5 Cases à cocher
Carré 19 px, rayon 5 px. Coché : fond `accent` + `ph-check` blanc 12 px. Décoché : fond blanc, bordure 1.5 px `#CDD2DA`.

### 8.6 Ligne de tableau (historique d'un type — Dictée / Réunion)
Grille (Réunion) : `40px | 1fr | 190px | 74px | 116px | 34px | 68px`, `column-gap: 12px`, hauteur 52 px, filet bas `divider`.
Colonnes : icône de type · **Titre** (600, ellipsis) · **Date** (mono) · **Durée** (mono) · **État** (badge, §9) · **Lien calendrier** (§8.6.2) · **Actions** (§8.6.1).
- **Ligne sélectionnée :** fond `accent-soft` + barre latérale gauche `3px accent`.
- **Survol :** fond `surface-hover`.
En-tête de colonnes : `surface-header`, libellés mono 10.5 px MAJUSCULES `ink-300`, `sticky`. Les colonnes **Lien calendrier** et **Actions** n'ont pas de libellé d'en-tête.

> ⚠ Changement d'IA (remplace l'ancien `ActionsDelegate` qui peignait *N* icônes) : la **rangée d'icônes d'action à nombre variable est supprimée**. Elle rendait la colonne irrégulière (largeur et alignement changeant selon l'état de la ligne — transcrit / locuteurs / audio seul / lien calendrier) et illisible (icônes sans libellé). Remplacée par les motifs §8.6.1–8.6.3.

### 8.6.1 Colonne « actions » — accès direct + menu ⋯
Deux emplacements **fixes**, alignés à droite, **identiques sur toutes les lignes** (plus de bord en dents de scie) :
1. **Copier** (`ph-copy`, bouton icône 30×30, rayon 7) — l'action la plus fréquente, en un clic. Masquée (l'emplacement reste réservé, l'alignement tient) quand il n'y a rien à copier (audio seul).
2. **Menu ⋯** (`ph-dots-three-vertical`) — ouvre le **popover d'actions libellées** (§8.6.3) qui contient **toutes** les autres actions.

Bouton icône : fond transparent, icône `ink-300` ; survol fond `#fff` + icône `accent-ink` + ombre `0 1px 3px rgba(16,24,40,.14)`.

### 8.6.2 Colonne « lien calendrier » (interco BlueMind — F1)
Colonne dédiée de largeur fixe, contenu **icône 28×28 centrée, alignée à droite** — l'alignement vertical est constant quelle que soit la longueur du titre (ne **jamais** placer cet indicateur en ligne après le titre : il se déplacerait selon la longueur et introduirait une action entre le titre et la date). Détection **locale** sur la réplique du calendrier (cf. `core/bluemind`, aucun réseau). Trois états :
- **Associé** : `ph-calendar-check` **vert** (`#1F9D6B`), **passif** (non cliquable), tooltip « Associé à « {event} » ».
- **Un événement correspond** : `ph-calendar-plus` **accent** (`accent-ink`), **bouton** (survol fond `accent-soft`) → ouvre le dialogue d'association (§8.11).
- **Aucune correspondance / BlueMind non configuré** : **vide** (colonne réservée → alignement conservé ; l'interco reste invisible).

### 8.6.3 Popover de menu d'actions (⋯)
Popover ancré sous le bouton ⋯ (ouvre **vers le haut** pour les dernières lignes du tableau afin de ne pas être coupé), largeur ≈ 238 px, fond `surface`, bordure `border`, rayon 10 px, ombre popover (§4), padding conteneur 5 px. Items : `padding 8px 10px`, rayon 7, icône 16 px (`ink-300`) + label 13 px/500 `ink-900`. **Survol :** fond `accent-soft`, texte + icône `accent-ink`. **Item indisponible : grisé** (`ink-200`, non cliquable) *plutôt que masqué* — la position des items reste stable d'une ligne à l'autre. **Item destructif** (Supprimer) : séparé par un filet, texte + icône `#B42318`, survol fond `#FEF3F2`. Un seul menu ouvert à la fois ; fermeture au clic extérieur / `Échap`.

**Contenu (Réunion), dans l'ordre — reprend exactement `reunion_view._actions_reunion` :** Copier la transcription · *Transcrire la réunion* **ou** *Générer les locuteurs* (selon l'état ; libellé « … en cours… » désactivé pendant le job) · Nommer les locuteurs *(si locuteurs générés)* · Ouvrir la transcription · Révéler dans le dossier · *Associer à la réunion* **ou** *Associé — {event}* (grisé) *(si applicable, §8.6.2)* · — · Supprimer l'audio (garde le débrief) · Tout supprimer.
> Les libellés, l'ordre et la **disponibilité** proviennent du fournisseur d'actions par ligne (`ActionSpec`, dépend du fichier **et** de l'état du job en cours) : le menu remplace uniquement l'**affichage** (icônes → items libellés), pas la logique métier existante.

### 8.6.4 Sélection multiple & actions en masse
Les tableaux d'historique (**Réunion**, **Journal** ; la Dictée n'a pas d'historique) sont **multi-sélectionnables** selon les conventions système :
- **Clic simple** : sélectionne une seule ligne (remplace la sélection).
- **Ctrl/Cmd + clic** : bascule l'appartenance d'une ligne (ajoute/retire sans perdre le reste). `Cmd` sur macOS, `Ctrl` sur Windows/Linux.
- **Maj + clic** : sélectionne la **plage** contiguë depuis l'ancre (dernière ligne cliquée) jusqu'à la ligne visée.

Chaque ligne sélectionnée porte le rendu de sélection standard (fond `accent-soft` + barre latérale gauche `3px accent`, §8.6). L'ancre est mémorisée par type (bucket) ; la sélection est **par type** et ne fuit pas d'un onglet à l'autre.

**Barre d'actions en masse.** Dès que **≥ 2 lignes** sont sélectionnées, une barre contextuelle s'insère dans la barre d'action de section, **juste après le bouton Démarrer** (séparée par un filet vertical `1px border`, hauteur 22 px) :
1. **Compteur** — « **{n}** sélectionnés » (12.5 px, `ink-600`, le nombre en `ink-900`/700).
2. **Ignorer l'audio** (`ph-microphone-slash`) — **bouton secondaire** (§8.3 : fond blanc, bordure `#D6D9DE`, survol `accent`). **Réunion uniquement** (l'action ne s'applique pas au Journal). Ouvre la boîte de confirmation destructive (§8.9) avec décompte : « Supprimer l'audio de {n} réunions ? ».
3. **Supprimer** (`ph-trash`) — **bouton destructif** (§8.3 : fond blanc, texte + bordure `#B42318`/`#F4C9C7`, survol fond `#FEF3F2`). Ouvre la confirmation destructive avec décompte : « Supprimer {n} réunions / entrées ? ».
4. **Désélectionner** (`ph-x`, bouton icône ghost 30×30) — vide la sélection.

Icône + libellé pour les deux actions (padding `7px 12px`, rayon 8 px, 12.5 px/600) ; la boîte de confirmation §8.9 accorde le libellé et la description au nombre et au type (`réunion`/`réunions`, `entrée`/`entrées`). À la validation, la sélection du type courant est vidée.
> **Règle :** la barre en masse n'apparaît **jamais** pour une sélection d'une seule ligne (le menu ⋯ par ligne, §8.6.3, couvre déjà le cas unitaire). Elle est réservée au traitement de lot.

### 8.7 Badge d'état (pilule)
`display:inline-flex; gap:6px; padding:3px 9px 3px 7px; border-radius:20px; font:600 12px`. Icône 13 px + label. Couleur texte/icône et fond selon §9.

### 8.8 Menu du tray (popover)
**Exception à la règle typo maison (§4/§10) : ce menu suit la convention système, pas IBM Plex.** Police `-apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif` (rendu SF Pro natif sur macOS). L'horloge de la barre au-dessus est en police système avec `font-variant-numeric: tabular-nums` (plus de mono).

Fond translucide façon vibrancy, calé sur le rendu réel des menus macOS (proche blanc, peu teinté, opacité élevée — pas gris) : `rgba(247,248,250,.93)` + `backdrop-filter: blur(40px) saturate(150%)`, bordure `.5px solid rgba(0,0,0,.09)`, rayon 9 px, padding conteneur 4 px. Items : `padding:5px 9px; radius:5px`, icône 14 px + label 13 px/400 + raccourci à droite (opacité .55, plus de mono). Texte `#1D1D1F` par défaut ; « Ouvrir debriefMeet » en `font-weight:600` (pas de fond permanent) ; « Quitter » en `#FF3B30`. Séparateurs `rgba(0,0,0,.08)`. **Survol : fond bleu système `#0A6CFF`, tout le contenu de la ligne (texte, icône, raccourci) passe en blanc** — comportement standard des menus macOS.

### 8.9 Boîtes de dialogue — gabarit unifié

Remplace **toute** boîte native (`QMessageBox`, `QInputDialog`, `QDialog` par défaut) par ce même gabarit maison. **Toutes** les boîtes de l'app — confirmation de suppression, vidage du log, association BlueMind (§8.11), mapping des locuteurs, saisie, information, erreur — partagent la même coquille. Un seul gabarit, réutilisé partout ; aucune boîte système (icône point d'interrogation grise, boutons Yes/OK/Cancel natifs) ne doit subsister.

**Coquille commune :** overlay + carte + **en-tête** (tuile icône 40×40 + titre 15 px/700 `ink-900` + description 13 px `ink-500`) + **pied** (bouton **Annuler** secondaire à gauche du bouton d'action, alignés à droite). Le corps varie selon le type (texte de confirmation, formulaire…).

**Couleur du bouton d'action = intention :**
- **Destructif** (Supprimer, Vider, Ignorer l'audio) → plein rouge `#B42318` (survol `#96190F`), tuile d'en-tête `#FEF3F2` / bordure `#F4C9C7`, icône `#B42318`.
- **Neutre / positif** (Associer, Enregistrer, Choisir) → plein **accent** `accent` (survol `accent-ink`), tuile d'en-tête `accent-soft`, icône `accent-ink`.
Le libellé du bouton décrit l'action (« Supprimer », « Vider », « Associer ») — **jamais** générique « Yes / OK ».

- **Superposition :** fond `rgba(16,24,40,.45)` couvrant la fenêtre, dialogue centré.
- **Carte :** largeur 380 px, fond `surface`, rayon 12 px, ombre popover (§4), padding 22 px, `display:flex; flex-direction:column; gap:18px`.
- **En-tête :** tuile icône 40×40, rayon 10 px, fond `#FEF3F2`, bordure `1px solid #F4C9C7`, icône `ph-trash` 19 px `#B42318` ; à droite, titre 15 px/700 `ink-900` (« Supprimer « Titre » ? ») + description 13 px `ink-500` (ligne 1.55) précisant ce qui est perdu (transcription, audio, etc.).
- **Actions (alignées à droite) :** bouton **Annuler** = secondaire (§8.3) ; bouton d'action = plein selon l'intention (§8.9 : rouge `#B42318` destructif / accent neutre-positif) / texte blanc / rayon 9 px. Le libellé du bouton s'adapte à l'action (« Supprimer », « Vider », « Associer »), jamais générique « Yes / OK ». *(La variante rouge de dialogue `#B42318` est à distinguer du bouton « Danger plein » `#FF3B30` réservé à Arrêter l'enregistrement.)*
- Aucune icône de titlebar / feux tricolores sur ce dialogue : c'est une superposition dans la fenêtre, pas une fenêtre OS séparée.

**Qt :** implémenter en `QDialog` frameless (ou `QMessageBox` entièrement restylé en QSS + icône custom substituée à l'icône standard), jamais la boîte native par défaut.

```css
QDialog#confirmDialog { background: #fff; border-radius: 12px; }
QDialog#confirmDialog QLabel#title { font-family: "IBM Plex Sans"; font-size: 15px; font-weight: 700; color: #1A1D23; }
QDialog#confirmDialog QLabel#desc  { font-family: "IBM Plex Sans"; font-size: 13px; color: #667085; }
QDialog#confirmDialog QPushButton#destructive {
    background: #B42318; color: #fff; border: none; border-radius: 9px;
    padding: 9px 16px; font-weight: 600;
}
QDialog#confirmDialog QPushButton#destructive:hover { background: #96190F; }
```

### 8.10 Barre d'auto-enregistrement (Préférences)
Remplace les boutons OK/Annuler modaux. Bas de panneau, fond `surface-header`, filet haut `border` : `ph-check-circle` vert + « Modifications enregistrées automatiquement » (`ink-500`, 12.5 px).

### 8.11 Dialogue d'association BlueMind (F1)
Instance du gabarit §8.9, **variante accent** (positif, pas destructif). Ouvert depuis la colonne lien calendrier (§8.6.2) ou le menu ⋯, quand un événement du calendrier correspond à l'enregistrement.
- **En-tête :** tuile `accent-soft` + `ph-calendar-check` `accent-ink` ; titre « Associer à un événement » ; description « Un événement du calendrier BlueMind correspond à cette réunion. »
- **Page de choix** (uniquement si **plusieurs** correspondances) : liste des événements (`{titre} — {HH:MM}`) ; la sélection mène au récapitulatif.
- **Récapitulatif :** « **Titre :** {event} » (13.5 px `ink-900`) + date/heure (mono 12 px `ink-500`) ; case à cocher **« Appliquer ce titre à la réunion »** (cochée par défaut si la réunion n'a pas encore de titre) ; libellé de section mono **PARTICIPANTS** ; **liste des invités cochables** (case §8.5) — `{nom} <{email}> — {rôle}`, rôle = « organisateur » ou statut de participation (`part_status`), **tous cochés par défaut**.
- **Pied :** **Annuler** (secondaire) + **Associer** (plein accent). À la validation : `finaliser_association` écrit l'association (event/cal uid, titre, début, invités cochés) et applique le titre si demandé, puis recharge la ligne (qui passe à l'état *Associé*).

---

## 9. États d'une entrée d'historique

Chaque ligne porte **un** état, rendu en badge (§8.7). L'état décrit le résultat de la capture :

| État | Signification | Couleur / fond | Icône |
|---|---|---|---|
| **En cours** | Enregistrement actif (ligne du haut) | `#FF3B30` / `#FFECEA` | `ph-record-fill` |
| **Transcrit** | Transcription live effectuée et disponible | `#1F9D6B` / `#E7F6EF` | `ph-check-circle` |
| **Audio seul** | Piste enregistrée sans transcription live | `#7A828F` / `#F1F2F5` | `ph-waveform` |
| **Locuteurs** | Diarization disponible (séparation des intervenants) | `#3B5BDB` / `#EEF1FE` | `ph-users-three` |

> « Transcrit » et « Locuteurs » ne sont pas exclusifs conceptuellement ; si les deux s'appliquent, afficher **Locuteurs** (information la plus riche). Une entrée « En cours » bascule vers son état final à l'arrêt.

---

## 10. Règles cross-platform

- **Look identique** sur les trois OS (design maison). Concessions système ci-dessous.
- **Titlebar :** chrome neutre. Sur macOS, feux tricolores natifs à gauche ; sur Windows/Linux, boutons système à droite. Le titre reste centré et discret (`ink-600`, 12.5 px/600).
- **Icône tray :** fournir une variante **template monochrome** (repos) pour l'auto-inversion clair/sombre de la barre de menus macOS ; sur Windows (barre des tâches) et Linux (`StatusNotifier`), fournir la version colorée selon l'état.
- **Raccourcis :** afficher les libellés natifs — `⌃⌥⌘` sur macOS, `Ctrl+Alt+…` sur Windows/Linux. Ne jamais coder en dur les glyphes mac dans les autres builds.
- **Polices :** embarquer IBM Plex Sans/Mono dans le bundle Qt (ne pas dépendre des polices système) pour un rendu identique partout. **Exception : le menu du tray (§8.8) utilise la police système native** (SF Pro sur macOS, Segoe UI sur Windows, etc.) et un fond vibrancy/translucide, pour se fondre dans les menus contextuels de l'OS plutôt que d'imposer le look maison.
- **Densité :** conserver les hauteurs de ligne (52 px) et cibles tactiles ≥ 44 px là où c'est cliquable.

---

## 11. Correspondance Qt

Mapping indicatif entre les composants du design et l'implémentation Qt Widgets.

| Design | Qt |
|---|---|
| Fenêtre unifiée | `QMainWindow` (sans `QStatusBar` natif ; barre auto-save custom) |
| Barre d'outils | `QToolBar` non déplaçable, ou `QWidget` custom en `setMenuWidget` |
| Navigation 3 onglets (Dictée/Réunion/Journal) + engrenage Préférences | `QStackedWidget` piloté par 3 `QToolButton` checkable exclusifs + un `QToolButton` icône (Préférences) à droite de la toolbar |
| Bouton Démarrer/Arrêter de section | `QPushButton` bascule (`#primary` → `#danger`) en tête de chaque page de capture ; chrono + puce pulsante en `QLabel` adjacents pendant la capture |
| Tableau d'historique (par type) | `QTableView` + `QAbstractTableModel` (un modèle par type) ; badge d'état via un `QStyledItemDelegate` (`paint()`) ; `setSelectionMode(ExtendedSelection)` + `setSelectionBehavior(SelectRows)` pour la sélection multiple (Ctrl/Cmd bascule, Maj plage — natif Qt) |
| Barre d'actions en masse | `QWidget` custom inséré après le bouton Démarrer, visible si `selectionModel()->selectedRows().count() >= 2` (`selectionChanged`) : label compteur + `QPushButton#secondary` **Ignorer l'audio** (Réunion seule) + `QPushButton#destructive` **Supprimer** + bouton icône ✕. Chaque action itère sur les lignes sélectionnées après une confirmation §8.9 unique portant le décompte |
| Colonne actions (Copier + ⋯) | `QToolButton` icône **Copier** + `QToolButton` **⋯** ouvrant un `QMenu` (restylé QSS) d'actions **libellées** ; items indisponibles via `QAction.setEnabled(False)` (grisés, non masqués), item destructif séparé (`addSeparator`). Remplace l'ancien `ActionsDelegate` à icônes multiples — conserver le fournisseur `ActionSpec` pour la logique/disponibilité |
| Colonne lien calendrier | `QStyledItemDelegate` (icône 28×28 alignée à droite) ou `QToolButton` ; clic à l'état « associable » → `DialogAssociationBluemind` |
| Dialogue d'association BlueMind | `QDialog` frameless sur le gabarit §8.9 (en-tête + bouton primaire **accent**) |
| Sous-nav des préférences | `QListWidget` (icône + texte) pilotant un `QStackedWidget` |
| Champs | `QLineEdit`, `QComboBox`, `QPlainTextEdit`, `QSpinBox` |
| Cases à cocher | `QCheckBox` restylé en QSS |
| Icône & menu tray | `QSystemTrayIcon` + `QMenu` ; clic gauche → `Trigger`, clic droit → `Context` |
| Chronomètre | `QTimer` (1 s) mettant à jour un `QLabel` mono |
| Icône d'app | `QIcon` ; variante tray en `QIcon` avec `setIsMask(true)` (template macOS) |

### 11.1 Palette Qt (extrait)

```cpp
// Accent
const QColor kAccent     ("#3B5BDB");
const QColor kAccentInk  ("#2A46B8");
const QColor kAccentSoft ("#EEF1FE");
// Texte
const QColor kInk900("#1A1D23"), kInk700("#344054"), kInk500("#667085"),
             kInk400("#7A828F"), kInk300("#98A2B3");
// Surfaces / bordures
const QColor kSurface("#FFFFFF"), kSunken("#F6F7F9"), kBorder("#E7E9EE"),
             kDivider("#F1F2F5");
// États
const QColor kRec("#FF3B30"),  kRecBg("#FFECEA");
const QColor kOk ("#1F9D6B"),  kOkBg ("#E7F6EF");
const QColor kMut("#7A828F"),  kMutBg("#F1F2F5");
const QColor kInfo(kAccent),   kInfoBg(kAccentSoft);
const QColor kDanger("#B42318");
// Tray
const QColor kTrayIdle("#3D4351"), kTrayRec("#FF3B30"),
             kTrayTranscribe("#FF9500"), kTrayDone("#34C759"), kTrayError("#8E8E93");
```

### 11.2 QSS (extrait)

```css
/* Champs */
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {
    background: #F6F7F9;
    border: 1px solid #E7E9EE;
    border-radius: 8px;
    padding: 10px 13px;
    font-family: "IBM Plex Sans";
    font-size: 14px;
    color: #1A1D23;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus {
    border-color: #3B5BDB;
}

/* Bouton primaire */
QPushButton#primary {
    background: #3B5BDB; color: #fff;
    border: none; border-radius: 9px;
    padding: 10px 18px; font-weight: 600;
}
QPushButton#primary:hover { background: #2A46B8; }

/* Bouton secondaire */
QPushButton#secondary {
    background: #fff; color: #344054;
    border: 1px solid #D6D9DE; border-radius: 9px;
    padding: 10px 18px; font-weight: 600;
}
QPushButton#secondary:hover { border-color: #3B5BDB; color: #2A46B8; }

/* Bouton destructif (Arrêter) */
QPushButton#danger {
    background: #FF3B30; color: #fff;
    border: none; border-radius: 9px; padding: 10px 20px; font-weight: 600;
}

/* Onglet de navigation actif */
QToolButton#navTab:checked {
    color: #2A46B8;
    border-bottom: 2px solid #3B5BDB;
}

/* Ligne sélectionnée du tableau */
QTableView { gridline-color: transparent; selection-background-color: #EEF1FE; }
QHeaderView::section {
    background: #FBFBFC; color: #98A2B3;
    font-family: "IBM Plex Mono"; font-size: 10px;
    text-transform: uppercase; border: none; padding: 9px 0;
}
```

> Les **badges d'état** (pilules colorées) et la **barre latérale d'accent** de la ligne sélectionnée se peignent dans un `QStyledItemDelegate` plutôt qu'en QSS, pour un contrôle précis du rayon et de l'icône.

---

## 12. Checklist d'implémentation

- [ ] IBM Plex Sans + Mono embarqués dans les ressources Qt.
- [ ] Palette et rayons centralisés (constantes / thème), pas de valeurs en dur dans les vues.
- [ ] Mono systématique pour dates, durées, chronos, chemins, raccourcis, versions.
- [ ] Icône tray : variante template (repos) + variantes colorées par état ; retour bref Terminé/Erreur.
- [ ] Clic gauche = ouvrir ; clic droit = menu.
- [ ] Un seul enregistrement à la fois ; l'état survit à la navigation.
- [ ] Délégué de badge d'état pour les 4 statuts d'historique.
- [ ] Colonne actions = **Copier** + menu **⋯** (deux emplacements fixes, alignés) ; plus aucune rangée d'icônes à nombre variable (§8.6.1).
- [ ] Sélection multiple des tableaux (Ctrl/Cmd bascule, Maj plage) ; barre d'actions en masse (**Ignorer l'audio** — Réunion seule — + **Supprimer** + désélectionner) affichée à partir de 2 lignes, après le bouton Démarrer ; confirmation §8.9 avec décompte (§8.6.4).
- [ ] Items de menu indisponibles **grisés** (non masqués) ; destructif séparé et en rouge.
- [ ] Colonne **lien calendrier** alignée (icône 28×28 à droite) : vert *associé* passif / accent *associable* cliquable / vide sinon (§8.6.2).
- [ ] **Toutes** les boîtes de dialogue sur le gabarit unifié §8.9 (aucune `QMessageBox`/`QInputDialog`/`QDialog` native) ; couleur du bouton = intention (rouge destructif / accent neutre-positif).
- [ ] Raccourcis affichés au format natif par OS.
