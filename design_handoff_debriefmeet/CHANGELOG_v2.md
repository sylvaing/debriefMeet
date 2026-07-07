# CHANGELOG v2 — Refonte de la navigation debriefMeet

> **Contexte.** La v1 de ce handoff a déjà été implémentée dans le codebase Qt/PySide6.
> Ce document décrit **uniquement les changements à appliquer** pour passer à la v2 (nouvelle
> architecture de l'information). Il **fait autorité** : partout où `README.md` ou
> `IMPLEMENTATION_SPEC.md` (rédigés pour la v1) le contredisent, **c'est la v2 qui gagne**.
> La source de vérité visuelle reste `debriefMeet-C.dc.html` (rafraîchi) + `DESIGN.md` (à jour).

Version de la maquette : **0.2.0**.

---

## Résumé du changement (le « pourquoi »)

La v1 avait deux onglets (**Historique**, **Préférences**), un **groupe de démarrage segmenté**
(Dictée/Réunion/Journal) à droite de la barre d'outils, et un **écran d'enregistrement plein écran**.

La v2 réorganise autour du **type de capture** :

- La navigation devient **3 onglets de type** — **Réunion · Dictée · Journal** — plus un bouton
  **Préférences** (engrenage, icône seule) à droite.
- **Il n'y a plus d'onglet « Historique » global** : chaque type porte **son propre historique**.
- **Le démarrage se fait dans chaque section** (bouton Démarrer/Arrêter au-dessus de l'historique),
  plus dans la barre d'outils.
- **L'écran d'enregistrement plein écran est supprimé** : l'enregistrement est signalé de façon
  légère (icône d'état + bouton Arrêter + chrono + ligne « En cours »).

---

## Deltas détaillés

### 1. Barre d'outils — navigation (remplace README §Screens/1, SPEC Étape 4.2)
- **Supprimer** les 2 onglets `navTab` « Historique » / « Préférences ».
- **Supprimer** le `StartButtonGroup` segmenté (Dictée/Réunion/Journal) à droite (SPEC Étape 3d — ce composant n'existe plus).
- **Ajouter** 3 onglets de type dans la barre, **dans cet ordre** : **Réunion** (`ph-users-three`) · **Dictée** (`ph-microphone`) · **Journal** (`ph-notebook`). Chaque onglet = icône 16 px + label 14 px/600 ; actif = `#2A46B8` + soulignement `2px #3B5BDB` ; inactif = `#8A919E`.
  - **Les onglets ne portent AUCUN indicateur d'enregistrement** (pas de point, pas de chrono) — contrairement à une version intermédiaire.
- **Préférences** = un **bouton icône engrenage seul** (`ph-gear`, 18 px, tuile 34×34, radius 8), placé **à droite** après le spacer, avant l'icône d'état. Actif : fond `#EEF1FE`, icône `#2A46B8` ; repos : icône `#8A919E`.
- **Badge version** : `0.2.0`. Pas de préfixe « v ». Pastille : `IBM Plex Mono` 10.5px, couleur `#98A2B3`, bordure `1px solid #E7E9EE`, `border-radius: 5px`, padding `1px 6px` — collée au wordmark avec `gap: 10px`. (Bug vu en implémentation : version encadrée différemment — police/couleur par défaut au lieu du style ci-dessus.)
- **Soulignement des onglets** : chaque onglet a un `border-bottom: 2px solid transparent` **par défaut** (pas de trait visible au repos) ; seul l'onglet actif passe cette bordure à `#3B5BDB`. (Bug vu en implémentation : un trait/bordure visible apparaît sous chaque onglet au repos — s'assurer que l'état inactif utilise bien `transparent` et non une couleur grise/bordure de séparation.)
- **En-têtes de colonnes des tableaux** (TITRE/DATE/DURÉE/ÉTAT) : alignées à gauche (`text-align: left`), alignées avec le contenu de leur colonne respective — jamais centrées. (Bug vu en implémentation : en-têtes centrées dans leur colonne.)
- **Survol des lignes d'historique** : chaque ligne (52px de haut) doit passer en fond `#FAFAFB` au `hover` (`QListView`/`QTableView` : `item:hover { background: #FAFAFB; }`, hors ligne sélectionnée qui reste `#EEF1FE`). (Bug vu en implémentation : pas de mouse over.)
- **Polices des lignes d'historique** — respecter la règle "Mono = données techniques" (`DESIGN.md` §Typographie) :
  - **Titre** : `IBM Plex Sans`, **700 (gras)**, 13.5px, `#1A1D23`.
  - **Date** et **Durée** : `IBM Plex Mono`, 400/500, 12px, `#667085` (gris) — jamais `IBM Plex Sans`.
  (Bug vu en implémentation : polices non respectées — même famille pour tout, titre pas en gras.)
- **Colonne Date** : doit inclure la date **et** l'heure de début, format `JJ/MM/AAAA · HH:MM` (ex. `06/07/2026 · 14:33`), en `IBM Plex Mono`. (Bug vu en implémentation : heure absente.)
- **Écran Préférences → onglet "Modèle"** (et par extension tous les onglets Préférences) : le contenu du panneau (label + champ) doit être **ancré en haut à gauche** de la zone de contenu, avec un padding `26px 30px`, **pas centré horizontalement/verticalement**. Structure en **colonne** (`flex-direction: column`, `gap: 6px`) : le **label est au-dessus** du champ (jamais à côté) — `"Modèle Whisper"` en 12.5px/600 `#344054`, puis le sélecteur juste en dessous (background `#F6F7F9`, bordure `1px solid #E7E9EE`, radius 8px, padding `10px 13px`, valeur en `IBM Plex Mono` 13.5px `#1A1D23`), puis le texte d'aide en 12px, `line-height: 1.7`, couleur `#8A919E`, `margin-top: 10px`. Largeur max du bloc : 540px. (Bug vu en implémentation : label et champ côte à côte et centrés dans la zone, tailles de police non respectées.)
- **Sous-navigation Préférences (colonne de gauche)** : la surbrillance de l'item actif (ex. « Modèle ») doit couvrir **toute la largeur** de la colonne (208px, moins le padding du conteneur `14px 10px`), pas seulement la largeur du texte/icône — bouton avec `width: 100%`, padding `8px 11px`, radius 8px, fond `#EEF1FE` actif. (Bug vu en implémentation : surbrillance trop étroite.)
- **Tous les onglets Préférences (Modèle, Audio, Dossiers, Prompts, Général, Raccourcis, Journalisation)** : même règle d'alignement — le contenu est **ancré en haut à gauche** de la zone de contenu (padding `26px 30px`), en colonne verticale, labels au-dessus/à hauteur fixe à gauche des champs mais **jamais centré horizontalement dans la page**. (Bug vu en implémentation : panneau "Audio" avec tous les champs centrés horizontalement au milieu de la fenêtre au lieu d'être callés à gauche avec la marge de 30px.)
- **Disposition des champs Préférences — Audio (et modèle général pour tous les onglets)** : chaque champ est un **bloc vertical** (`label` au-dessus de son champ, `gap: 6px`), **pas** un formulaire deux-colonnes (label à gauche / champ à droite). Les blocs s'empilent avec `gap: 20px`. **Largeurs des champs, ne pas les laisser s'étirer** :
  - `Microphone` : combo `max-width: 600px` (prend la largeur du bloc, pas plus), padding `10px 13px`, hauteur ~38px, texte 13.5px.
  - `Intervalle réunion` : combo **compacte**, `max-width: 180px` (pas la même largeur que Microphone), padding `8px 13px`, valeur en `IBM Plex Mono` 13.5px.
  - Cases à cocher (Transcription / Annulation d'écho / Rétention audio) : `gap: 11px` entre elles, case 19×19px, label 13.5px à côté.
  (Bug vu en implémentation : disposition différente du modèle — labels à gauche des champs au lieu d'au-dessus, combo box surdimensionnées/toutes à la même largeur au lieu des largeurs ciblées ci-dessus.)
- **Onglet Préférences → "Dossiers"** : **aucune carte/panneau gris** autour de chaque champ (Réunions, Journal) — pas de fond arrondi gris englobant label + chemin + bouton. Structure plate, `max-width: 620px`, blocs empilés avec `gap: 20px` :
  - Label seul au-dessus (12.5px/600, `#344054`), pas de fond.
  - Ligne en dessous : `display: flex; gap: 8px` — champ chemin (`flex: 1`, fond `#F6F7F9`, bordure `1px solid #E7E9EE`, radius 8px, padding `10px 13px`, texte en `IBM Plex Mono` 12.5px, couleur `#475467` — pas noir) + bouton **« Choisir… »** à droite (fond **blanc** `#fff`, pas gris, bordure `1px solid #D6D9DE`, radius 7px, padding `0 15px`, texte 12.5px/600 `#344054`, hover : bordure `#3B5BDB`).
  (Bug vu en implémentation : trop de gris — cartes englobantes grisées autour de chaque dossier au lieu de champs plats sur fond blanc de la page.)
- **Onglet Préférences → "Prompts"** — disposition en 2 colonnes, `gap: 20px`, hauteur pleine :
  - **Colonne gauche (200px fixe)** : liste des prompts dans un cadre `border: 1px solid #E7E9EE`, `border-radius: 8px` (pas plus large que 200px, pas la moitié du panneau). Chaque ligne : padding `9px 12px`, 13px, séparateur `1px solid #EFF1F4` entre lignes. **Item actif** = fond `#EEF1FE`, texte `#2A46B8` **gras**, avec une **coche bleue** (`ph-check`, `#2A46B8`) alignée à droite de la ligne (pas de coche ✓ texte brute) ; items inactifs = fond blanc, texte `#1A1D23` normal. Sous la liste, 2 **petits boutons carrés** `+`/`–` (32×28px, fond blanc, bordure `1px solid #D6D9DE`, radius 7px, icônes Phosphor) côte à côte à gauche — pas des symboles `+`/`−` nus centrés sous toute la liste.
  - **Colonne droite (flex: 1)** : label **« Titre »** (12.5px/600) au-dessus d'un champ input (fond `#F6F7F9`, bordure `1px solid #E7E9EE`, radius 8px, padding `9px 13px`, 13.5px) ; puis label **« Contenu »** au-dessus d'un `textarea` (même fond `#F6F7F9`/bordure, radius 8px, padding `11px 13px`, police **`IBM Plex Mono` 12.5px**, `line-height: 1.6`, couleur `#344054` — pas une police système plus grande sur fond blanc).
  - En bas : case à cocher **« Utiliser ce prompt à la copie »** = case **remplie indigo `#3B5BDB`** avec coche blanche quand cochée (même style que les cases à cocher de Journalisation), pas une case vide à contour gris.
  (Bug vu en implémentation : liste trop large sans cadre net, sélection en gris plat sans coche ni texte en gras, boutons +/− en texte nu au lieu de boutons carrés, champs Titre/Contenu en police système large au lieu de Mono 12.5px sur fond gris clair, case à cocher vide au lieu de la case indigo remplie.)
- Ordre final de la barre : WaveMark + wordmark + version ┃ Réunion · Dictée · Journal ┃ *(spacer)* ┃ engrenage Préférences ┃ icône d'état WaveMark.

### 2. Section de capture — bouton Démarrer/Arrêter (nouveau ; remplace le StartButtonGroup)
Chaque page de type (Réunion / Dictée / Journal) a une **barre d'action** en tête (padding 14 20, filet bas `#EFF1F4`) :
- **Bouton Démarrer/Arrêter** à gauche (bascule) :
  - repos → **Démarrer** : bouton `#primary` (`#3B5BDB`, texte blanc, radius 9), icône du type + libellé « Démarrer la réunion / dictée / journal ».
  - en cours (ce type) → **Arrêter** : fond `#FF3B30`, texte blanc, icône `ph-stop-fill`, ombre `0 6px 16px -6px #FF3B30`.
  - **à côté du bouton Arrêter** (hors bouton) : un **point rouge pulsant** + le **chronomètre mono** (`#FF3B30`, 15 px).
  - un autre type enregistre → bouton **grisé** (`#F2F4F7`, texte `#98A2B3`, curseur défaut) + mention « Un enregistrement est déjà en cours. ».
- **Champ de recherche** à droite (260 px) **pour Réunion et Journal uniquement**.

### 3. Réunion (page par défaut ; remplace README §Screens/2, SPEC Étape 5)
- Tableau inchangé dans sa structure : `TITRE · DATE · DURÉE · ÉTAT · actions`, grille `40 | 1fr | 150 | 74 | 116 | 210`, ligne 52 px, en-tête mono sticky, sélection = fond `#EEF1FE` + barre d'accent gauche 3 px, hover `#FAFAFB`.
- **Ligne « En cours »** : quand une réunion s'enregistre, insérer **en tête** du tableau une ligne « Réunion en cours » avec le badge **En cours** (`#FF3B30` / `#FFECEA`, `ph-record-fill`) et la **durée = chronomètre live** ; pas de boutons d'action sur cette ligne. À l'arrêt, elle bascule vers son état final (Transcrit / Locuteurs / Audio seul).
- Recherche à droite (placeholder « Rechercher une réunion… »).

### 4. Dictée (nouveau comportement ; remplace l'ancien onglet Réunions/Journal côté dictée)
- **Pas d'historique, pas de recherche.**
- La section affiche uniquement le bouton **Démarrer la dictée** + un **état explicatif centré** :
  tuile micro 60×60 `#EEF1FE` (`ph-microphone` `#2A46B8`), titre « Dictée vocale » (16/700),
  puis le texte : **« Le texte transcrit est copié dans le presse-papiers. Cliquez sur Démarrer la dictée ou utilisez le raccourci ⌃⌥⌘D. »**
- **Comportement fonctionnel : la dictée copie le résultat dans le presse-papiers** (≠ v1 qui parlait d'insertion directe). À câbler côté capture : à l'arrêt de la dictée, mettre la transcription dans `QClipboard`.

### 5. Journal
- Inchangé : liste de fichiers (`icône notebook · nom fichier mono · note · actions`), avec recherche à droite. Toujours accessible via l'onglet de type « Journal ».

### 6. Écran d'enregistrement — SUPPRIMÉ (remplace README §Screens/5, SPEC Étape 7 `RecordingView`)
- **Supprimer entièrement** la vue « Enregistrement en cours » plein écran (pastille ENREGISTREMENT, titre, chrono 42 px, waveform, encart transcription live, bouton Arrêter isolé).
- Pendant l'enregistrement, l'utilisateur **reste sur la page du type** ; l'historique demeure visible. L'état est signalé par : (a) l'**icône d'état** de la barre (rouge), (b) le **bouton Arrêter + point + chrono** de la section, (c) la **ligne « En cours »** (réunion).
- **`RecordingController` reste nécessaire** (état global persistant, un seul enregistrement à la fois, `QTimer` 1 s, signaux `started/tick/stopped`). Seuls **les effets UI changent** : ne plus afficher de `RecordingView`, mais piloter le bouton Démarrer↔Arrêter de la section, le point/chrono, la ligne live et l'icône d'état. Le signal `showRequested` n'a plus de vue dédiée à afficher (au besoin : basculer sur l'onglet du type en cours).

### 7. Menu du tray (remplace README §Screens/6, SPEC Étape 8.4)
- **Supprimer l'item « Historique… »** (il n'y a plus d'historique global).
- Ordre du menu : Démarrer Dictée `⌃⌥⌘D` · Démarrer Réunion `⌃⌥⌘R` · Démarrer Journal `⌃⌥⌘J` — sép — **Ouvrir debriefMeet** (mis en avant) · Préférences… — sép — Quitter (`#B42318`).
- Icône du tray et cycle d'états : **inchangés**.

### 8. État applicatif (remplace README §State Management, SPEC Étape 7)
```
currentView   : 'reunion' | 'dictee' | 'journal' | 'preferences'   (défaut: 'reunion')
recordingType : null | 'dictee' | 'reunion' | 'journal'
elapsedSeconds: int
selectedRow   : int   (sélection dans la table Réunion)
```
- **Supprimé** : `currentView` ne contient plus `'historique'` ni `'recording'` ; **`historyTab` disparaît** (les anciens sous-onglets Réunions/Journal sont devenus des onglets de premier niveau).
- Logique de démarrage inchangée : re-clic du type actif = ré-afficher son onglet (sans relancer) ; autre type actif = ignorer ; sinon démarrer. `stop()` → `recordingType = null`.

---

## Impact par étape de `IMPLEMENTATION_SPEC.md`
- **Étape 3d (StartButtonGroup)** : ❌ supprimé. Remplacé par un simple bouton bascule Démarrer/Arrêter par section (§2 ci-dessus).
- **Étape 4 (Shell)** : toolbar = 3 onglets de type + engrenage Préférences ; `QStackedWidget` pages = `ReunionView`, `DicteeView`, `JournalView`, `PreferencesView` (❌ plus de `RecordingView`).
- **Étape 5 (Historique)** : éclaté en pages par type. `ReunionView` = table + barre d'action (Démarrer/Arrêter + recherche) + ligne « En cours ». `JournalView` = liste + barre d'action. `DicteeView` = barre d'action + état vide (pas de table, pas de recherche).
- **Étape 7 (Enregistrement)** : garder `RecordingController` ; ❌ supprimer `RecordingView` ; câbler les effets sur les boutons de section, la ligne live et l'icône d'état. Ajouter la copie presse-papiers pour la dictée.
- **Étape 8 (Tray)** : retirer l'item « Historique… ».
- Étapes 0, 1, 2, 6, 9, 10 : inchangées.

---

## Correctifs graphiques (constatés sur le build actuel, à corriger)

1. **Badge version** — actuellement un gros encart avec sa propre bordure/case. Doit être un badge mono discret, collé après le wordmark : `border: 1px solid #E7E9EE; border-radius: 5px; padding: 1px 5px; font-family: monospace; font-size: 10.5px; color: #98A2B3;` (pas de `QFrame`/case séparée).
2. **Bouton engrenage (Préférences) et icône d'état** — actuellement rendus avec le style `QToolButton` par défaut (cadre carré bordé). Doivent être des icônes nues : `border: none; background: transparent;`. L'engrenage prend un fond `#EEF1FE` (radius 8) uniquement quand la page Préférences est active ; l'icône d'état (WaveMark) n'a jamais de cadre. → forcer `QToolButton { border: none; background: transparent; }` dans le QSS de la toolbar.
3. **Padding gauche du tableau** — l'icône de type colle au bord gauche de la fenêtre. Chaque ligne et l'en-tête du tableau doivent avoir `padding: 0 20px` (colonne icône démarre à 20px du bord, pas 0).
4. **Filet de séparation entre lignes absent** — chaque ligne du tableau doit avoir un filet bas `border-bottom: 1px solid #F1F2F5` (et l'en-tête `border-bottom: 1px solid #EFF1F4`) pour séparer visuellement les enregistrements. Vérifier que le `QTableView`/delegate dessine bien ce filet (grid lines activées ou tracées dans le `paint()` du delegate) plutôt que de compter sur le style par défaut.
5. **Menu du tray natif, non stylé** — le build affiche le `QMenu` par défaut de l'OS (pas d'icônes, pas de raccourcis affichés, pas de mise en avant). Le design (§7 DESIGN.md) attend : icône Phosphor 15px + libellé à gauche de chaque item, raccourci clavier en mono gris à droite (`⌃⌥⌘D` etc.), séparateurs fins entre groupes, et l'item **« Ouvrir debriefMeet »** mis en avant (fond `#EEF1FE`, texte `#2A46B8` semi-bold) puisque c'est l'action par défaut. Nécessite un `QMenu` avec QSS custom (`icon-size`, `padding`, séparateurs stylés) plutôt que le rendu système ; les raccourcis doivent être positionnés à droite via `setShortcut` + QSS d'alignement, ou dessinés manuellement si Qt les pousse à gauche par défaut.
6. **Contour de focus natif sur le champ de recherche** — au focus, un liseré bleu système apparaît sur 3 côtés du champ. Le design n'a **aucun focus ring visible** sur ce champ (juste `background: #F6F7F9; border: 1px solid #E7E9EE`, inchangé au focus). Forcer `QLineEdit:focus { border: 1px solid #E7E9EE; outline: none; }` pour désactiver le style de focus par défaut de l'OS/Qt.
7. **Boutons d'action de ligne sans état hover/pressed** — les icônes de fin de ligne (copier, locuteurs, ouvrir le CR, dossier, ignorer, supprimer) n'ont ni survol ni retour visuel au clic. Le design attend : `QToolButton { border: none; background: transparent; border-radius: 7px; }` puis `:hover { background: #fff; color: #2A46B8; }` (avec l'ombre légère `0 1px 3px rgba(16,24,40,.14)` si possible) et un état `:pressed` légèrement assombri. Vérifier que ces boutons sont de vrais `QToolButton`/`QPushButton` cliquables avec `cursor: pointer`, pas des icônes statiques dessinées dans le delegate.
8. **Combobox Microphone / sélecteurs Préférences non stylés** — rendu `QComboBox` par défaut (police système, pas de chevron custom). Le design attend : `background: #F6F7F9; border: 1px solid #E7E9EE; border-radius: 8px; padding: 10px 13px;` avec le texte en `#1A1D23` (13.5px) et un chevron `ph-caret-up-down` (14px, `#98A2B3`) aligné à droite — pas les flèches système. Appliquer un QSS custom au `QComboBox` (item view compris) plutôt que le style natif.
9. **Bloc « Diarization configurée »** — actuellement une ligne `Diarization : ✅ configurée` (case à cocher verte + texte minuscule) + un gros bouton pleine largeur « Configurer la diarization... ». Le design attend une **pastille badge** compacte : icône `ph-check-circle` + texte « Diarization configurée » en `#1F9D6B` sur fond `#E7F6EF` (padding 6px 11px, radius 7px), **suivie sur la même ligne** d'un bouton secondaire discret « Configurer… » (fond blanc, bordure `#D6D9DE`, radius 7px, padding 6px 12px) — pas un gros bouton séparé en dessous.
10. **Champ « Intervalle réunion » non stylé** — rendu `QSpinBox` natif (flèches système, police par défaut). Le design attend : `background: #F6F7F9; border: 1px solid #E7E9EE; border-radius: 8px; padding: 8px 13px;`, valeur en mono 13.5px `#1A1D23`, et les flèches haut/bas custom (chevrons `ph-caret-up`/`ph-caret-down` 10px `#98A2B3` empilés) plutôt que les boutons `QSpinBox` par défaut — nécessite un `QAbstractSpinBox` avec boutons custom ou QSS ciblant `::up-button`/`::down-button`.
11. **Menu du tray — vibrancy trop grise/opaque** (suite au correctif du point 5) — première passe encore trop grise et trop foncée par rapport à un vrai menu contextuel macOS (comparer aux menus système : fond quasi blanc, peu teinté, très translucide mais lumineux). Valeurs corrigées, à appliquer telles quelles : fond `rgba(247,248,250,.93)` + flou `blur(40px) saturate(150%)` ; bordure `.5px solid rgba(0,0,0,.09)` ; séparateurs `rgba(0,0,0,.08)`. Police système `-apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif` (déjà correct, à conserver). Voir §8.8 `DESIGN.md` (mis à jour).

## Ce qui NE change PAS
Tokens (couleurs, typo IBM Plex, rayons, ombres, espacements), système d'états des lignes et de l'icône tray, logo WaveMark, assets `icons/`, préférences (7 sections + auto-save), raccourcis globaux, thème centralisé (`theme.py` / `theme.qss`), packaging cross-platform.
