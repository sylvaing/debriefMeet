# Handoff : Refonte design de debriefMeet

## Overview
debriefMeet est un assistant de transcription qui vit dans la barre d'état système (tray). Il permet de lancer trois types de captures — **Dictée**, **Réunion**, **Journal** — puis de consulter l'**Historique** des captures et d'ajuster les **Préférences**. Cette refonte unifie l'app en **une seule fenêtre** (navigation Historique ↔ Préférences sans repasser par le tray), repense le **menu du tray** (clic gauche = ouvrir, clic droit = actions), et introduit un **système d'états** signalé par la couleur de l'icône et par des badges d'état sur les lignes d'historique.

L'application cible est développée en **Qt** et doit tourner sur **macOS, Windows et Linux**.

## About the Design Files
Les fichiers de ce paquet sont des **références de design réalisées en HTML** — des prototypes qui montrent l'apparence et le comportement voulus, **pas du code de production à copier tel quel**. La tâche est de **recréer ces designs dans le codebase Qt existant**, avec ses patterns habituels (QWidget/QML, QSS, modèles/délégués), et non d'embarquer le HTML.

> ⚠️ Les fichiers `.dc.html` utilisent un petit runtime maison (`support.js`) : template `{{ }}` + une classe `Component`. C'est uniquement pour l'aperçu. **Ne pas porter ce runtime.** Lire le HTML comme une spec visuelle ; les valeurs de style (couleurs, tailles, rayons, espacements) sont inline et exactes.
>
> **Point de départ recommandé :** ouvrir `Guide-Design.dc.html` dans un navigateur (styleguide visuel) et lire `DESIGN.md` (tokens + correspondance Qt/QSS). Tout est déjà là.

## Fidelity
**Haute fidélité (hifi).** Couleurs, typographie, espacements, rayons et interactions sont définitifs. Recréer l'UI au pixel près avec les composants Qt du projet. Les valeurs hex et les tailles du `DESIGN.md` font foi.

## Direction retenue
Trois directions visuelles ont été explorées ; **la direction à implémenter est la C** :
- **Typographie :** IBM Plex Sans (UI) + IBM Plex Mono (données techniques).
- **Accent :** indigo `#3B5BDB`.
- **Structure :** barre d'outils horizontale en haut + tableau dense pour l'historique.

Fichier de référence principal : **`debriefMeet-C.dc.html`**.
(Les fichiers `debriefMeet.dc.html` = direction A/sidebar et `debriefMeet-B.dc.html` = direction B/teal sont fournis pour contexte uniquement — ne pas implémenter.)

---

## Screens / Views

Toutes les vues vivent dans **une seule fenêtre** (1000 × 660 px dans la maquette ; la fenêtre réelle est redimensionnable). Structure verticale : **Titlebar (40 px)** → **Barre d'outils (58 px)** → **Contenu** (Historique OU Préférences OU Enregistrement).

### 1. Barre d'outils (persistante, en haut)
- **Layout :** hauteur 58 px, fond blanc, bordure basse `#E7E9EE`, padding horizontal 20 px, éléments en ligne avec `gap`.
- **Composants, de gauche à droite :**
  1. **Logo WaveMark** (26 px, carré indigo rempli) + wordmark « debriefMeet » (15 px / 700, `#1A1D23`) + badge version mono (`0.1.0`, 10.5 px, bordure `#E7E9EE`, radius 5 px).
  2. **Onglets de navigation** : « Historique » et « Préférences » (14 px / 600). Actif = `#2A46B8` + soulignement `2px #3B5BDB`. Inactif = `#7A828F`.
  3. *(spacer flex)*
  4. **Groupe de démarrage segmenté** : 3 boutons accolés (Dictée / Réunion / Journal) dans un conteneur bordé `#E7E9EE`, radius 9 px. Voir « Groupe de démarrage » plus bas.
  5. **Icône d'état** (WaveMark 24 px) reflétant l'activité d'enregistrement.

### 2. Historique — onglet Réunions (vue par défaut)
- **Sous-en-tête** (padding 14 px 20 px, bordure basse `#EFF1F4`) : segment **Réunions | Journal** (à gauche) + champ de **recherche** 260 px (à droite : fond `#F6F7F9`, bordure `#E7E9EE`, radius 8 px, icône `ph-magnifying-glass` `#98A2B3`).
- **Tableau** :
  - En-tête de colonnes : fond `#FBFBFC`, `sticky`, libellés **mono 10.5 px MAJUSCULES** `letter-spacing:.06em` couleur `#98A2B3` : `TITRE · DATE · DURÉE · ÉTAT`.
  - Grille : `40px | 1fr | 150px | 74px | 116px | 210px`, `column-gap: 12px`. (colonnes : icône type · titre · date · durée · état · actions)
  - **Ligne** : hauteur **52 px**, filet bas `#F1F2F5`.
    - Icône de type : `ph-microphone` (audio) ou `ph-users-three` (avec locuteurs), `#6B7A78`, 17 px.
    - Titre : 13.5 px / 600 `#1A1D23`, ellipsis.
    - Date : **mono 12 px** `#667085` (ex. `03/07/2026 · 14:22`).
    - Durée : **mono 12 px** `#667085` (ex. `17 min`).
    - État : **badge pilule** (voir §États).
    - Actions (alignées à droite, révélées au survol) : boutons 30×30, radius 7 px, icône 16 px `#98A2B3`, survol → fond blanc + `#2A46B8` + ombre `0 1px 3px rgba(16,24,40,.14)`. Actions : `ph-copy` (copier transcription), `ph-users` (débrief locuteurs), `ph-file-text` (ouvrir CR), `ph-folder` (ouvrir dossier), `ph-microphone-slash` (ignorer), `ph-trash` (supprimer).
  - **Ligne sélectionnée** : fond `#EEF1FE` + barre latérale gauche `3px #3B5BDB`.
  - **Survol** : fond `#FAFAFB`.

### 3. Historique — onglet Journal
- Même tableau, grille `40px | 1fr | 130px | 232px`. Colonnes : icône `ph-notebook` · **nom de fichier mono** (ex. `2026-07-02.md`) · note (ex. « 3 notes ») · actions (`ph-copy`, `ph-file-text`, `ph-folder`, `ph-trash`).

### 4. Préférences
- **Sous-navigation verticale** à gauche (208 px, fond `#FBFBFC`, bordure droite `#EFF1F4`) : liste d'items icône + texte (13.5 px / 600). Actif = fond `#EEF1FE`, texte `#2A46B8`. Sections : **Modèle** (`ph-brain`), **Audio** (`ph-waveform`), **Dossiers** (`ph-folders`), **Prompts** (`ph-chat-text`), **Général** (`ph-sliders-horizontal`), **Raccourcis** (`ph-keyboard`), **Journalisation** (`ph-bug`).
- **Panneau** à droite (padding 26 px 30 px), défilable.
- **Barre d'auto-enregistrement** en bas (fond `#FBFBFC`, filet haut `#E7E9EE`) : `ph-check-circle` vert `#1F9D6B` + « Modifications enregistrées automatiquement » (12.5 px `#667085`). **Remplace les boutons OK/Annuler** — les préférences se sauvent automatiquement.
- **Contenu de chaque section** (résumé) :
  - *Modèle* : select `large-v3-turbo` (mono) + texte d'aide (tiny/small rapides, large-v3-turbo recommandé ≈1,6 Go, large-v3 ≈3 Go, téléchargé au 1er usage).
  - *Audio* : select micro, spinner « Intervalle réunion » (`30 s`), 3 cases (Transcrire pendant l'enregistrement / Annuler l'écho des haut-parleurs / Conserver l'audio des réunions), statut « Diarization configurée » (badge vert) + bouton « Configurer… ».
  - *Dossiers* : 2 champs chemin (mono) Réunions / Journal + bouton « Choisir… » ; note « changer un dossier ne déplace pas les fichiers déjà produits ».
  - *Prompts* : liste de prompts (sélectionnable) + éditeur titre/contenu (textarea **mono**) + case « Utiliser ce prompt à la copie » + boutons +/−.
  - *Général* : select langue (Détection automatique), case « Lancer au démarrage de session », case « Activer les notifications ».
  - *Raccourcis* : 3 champs (Dictée / Réunion / Journal) affichant les combinaisons **mono** + bouton « Réinitialiser les défauts ». Note : un raccourci démarre/arrête même sans focus ; champ vide = désactivé.
  - *Journalisation* : 2 cases (Activer journalisation debug / Logs détaillés) + emplacement mono + boutons « Ouvrir le fichier de log » et « Vider le log » (destructif).

### 5. Enregistrement en cours
- Vue centrée (remplace le contenu, la barre d'outils reste visible avec l'état actif).
- **Éléments empilés (gap 24 px) :**
  1. Pastille « ENREGISTREMENT » : point rouge `#FF3B30` **pulsant** (opacité 1→.35, scale 1→.82, 1.4 s) + label mono 11 px `letter-spacing:.1em` `#FF3B30`.
  2. Titre 20 px / 700 (« Réunion en cours » / « Dictée en cours » / « Journal en cours ») + **chronomètre mono 42 px / 500**.
  3. **Waveform animée** : ~44 barres de 4 px, indigo `#3B5BDB`, `scaleY` animé (0.12→1, 0.9 s, `alternate`, délais échelonnés). *(décoratif — piloter avec le vrai niveau audio si possible.)*
  4. Encart transcription live : fond `#F6F7F9`, bordure `#E7E9EE`, radius 10 px ; label mono « TRANSCRIPTION EN DIRECT » + texte avec curseur `▍`.
  5. **Bouton Arrêter uniquement** : fond `#FF3B30`, texte blanc, `ph-stop`, ombre `0 6px 16px -6px #FF3B30`. *(pas de bouton Pause — retiré volontairement.)*

### 6. Menu du tray
- **Icône dans la barre d'état** : WaveMark dont la **couleur = l'état** (voir §États icône tray).
- **Clic gauche** → ouvre / met au premier plan la fenêtre.
- **Clic droit** → menu popover : fond `rgba(255,255,255,.95)`, bordure `rgba(16,24,40,.09)`, radius 11 px, ombre `0 20px 44px -14px rgba(16,24,40,.40)`. Items (padding 7px 10px, radius 7px, icône 15 px + label 13 px + raccourci mono à droite) :
  - Démarrer Dictée `⌃⌥⌘D` · Démarrer Réunion `⌃⌥⌘R` · Démarrer Journal `⌃⌥⌘J`
  - — séparateur —
  - **Ouvrir debriefMeet** (mis en avant : fond `#EEF1FE`, texte `#2A46B8`)
  - Historique… · Préférences…
  - — séparateur —
  - Quitter (`#B42318`)

---

## Interactions & Behavior

### Démarrage d'un enregistrement (comportement clé)
L'enregistrement est un **état global persistant**, indépendant de l'écran affiché :
1. Clic sur **Réunion** (ou Dictée / Journal), ou raccourci global, ou item du menu tray → démarre la capture et affiche l'écran « Enregistrement en cours ».
2. Le **bouton correspondant** de la barre d'outils passe en **mode enregistrement** : fond `#FFECEA`, texte `#FF3B30`, **point pulsant** rouge à la place de l'icône, **chronomètre mono** à droite du label.
3. L'**icône d'état** (barre d'outils + tray) devient rouge.
4. **Un seul enregistrement à la fois** : les deux autres boutons se **grisent** (`opacity: .55`, curseur par défaut, non cliquables).
5. Pendant l'enregistrement, l'utilisateur peut **naviguer** vers Historique ou Préférences → le chrono continue, rien ne s'interrompt.
6. **Re-cliquer le bouton actif** ré-affiche l'écran d'enregistrement (statut) **sans relancer** de capture.
7. Clic sur **Arrêter** → stoppe, revient à l'Historique ; la ligne passe de « En cours » à son état final.

### Navigation
- Onglets « Historique » / « Préférences » de la barre d'outils basculent le contenu (type `QStackedWidget`).
- Segment « Réunions » / « Journal » bascule le contenu du tableau.
- Le menu tray peut ouvrir directement l'Historique ou les Préférences.

### États & transitions
- Hover : lignes de tableau, boutons d'action, boutons.
- Focus champ : bordure passe à `#3B5BDB`.
- Chronomètre : +1 s / seconde tant que l'enregistrement est actif.
- Préférences : **auto-save** (pas de validation manuelle).

### Raccourcis globaux (fonctionnent sans focus)
`Dictée = ⌃⌥⌘D`, `Réunion = ⌃⌥⌘R`, `Journal = ⌃⌥⌘J` sur macOS. **Afficher les libellés natifs par OS** : `Ctrl+Alt+…` sur Windows/Linux. Ne pas coder en dur les glyphes mac ailleurs.

---

## State Management
Variables d'état minimales :
- `currentView` : `historique` | `preferences` | `recording`.
- `historyTab` : `reunions` | `journal`.
- `prefSection` : `modele` | `audio` | `dossiers` | `prompts` | `general` | `journalisation` | `raccourcis`.
- `recordingType` : `null` | `dictee` | `reunion` | `journal` (null = aucun enregistrement).
- `elapsedSeconds` : compteur du chrono.
- `selectedRow` : index de la ligne sélectionnée dans l'historique.

Transitions : `onStart(type)` → si `recordingType === type` ré-affiche l'écran ; si un autre enregistrement est actif, ne rien faire ; sinon démarre. `stop()` → `recordingType = null`, retour Historique.

Données : liste des captures (titre, date, durée, type, état), liste des fichiers de journal, prompts, préférences persistées.

---

## Design Tokens
Repris intégralement de `DESIGN.md` (§2 à §4). Résumé :

**Accent :** `#3B5BDB` (accent) · `#2A46B8` (ink/hover) · `#EEF1FE` (soft).
**Texte :** `#1A1D23` · `#344054` · `#475467` · `#667085` · `#7A828F` · `#98A2B3` · `#B0B7C0`.
**Surfaces/bordures :** `#FFFFFF` · `#F6F7F9` (champs) · `#FBFBFC` (en-tête) · `#FAFAFB` (hover) · `#E7E9EE` (bordure) · `#EFF1F4` · `#F1F2F5` (filets).
**États :** rec `#FF3B30`/`#FFECEA` · succès `#1F9D6B`/`#E7F6EF` · neutre `#7A828F`/`#F1F2F5` · info `#3B5BDB`/`#EEF1FE` · danger `#B42318`/`#FEF3F2`.
**Icône tray :** repos `#3D4351` (contour) · enregistrement `#FF3B30` · transcription `#FF9500` · terminé `#34C759` · erreur `#8E8E93`.
**Typo :** IBM Plex Sans (400/500/600/700) + IBM Plex Mono (400/500). Mono obligatoire pour dates/durées/chronos/chemins/raccourcis/versions.
**Espacement :** multiples de 4 (4 · 8 · 12 · 16 · 20 · 24 · 28 · 32).
**Rayons :** fenêtre 12 · cartes/champs 8–9 · boutons 7–9 · tuiles 7 · badges (pilule) 20 · cases 5.
**Ombres :** fenêtre `0 30px 70px -24px rgba(16,24,40,.42)` ; popover `0 20px 44px -14px rgba(16,24,40,.40)`.

### États d'une ligne d'historique (badge pilule)
`display:inline-flex; gap:6px; padding:3px 9px 3px 7px; border-radius:20px; font:600 12px` + icône 13 px.
| État | Signification | Texte/icône | Fond | Icône |
|---|---|---|---|---|
| En cours | enregistrement actif | `#FF3B30` | `#FFECEA` | `ph-record-fill` |
| Transcrit | transcription live OK | `#1F9D6B` | `#E7F6EF` | `ph-check-circle` |
| Audio seul | enregistré sans transcription live | `#7A828F` | `#F1F2F5` | `ph-waveform` |
| Locuteurs | diarization disponible | `#3B5BDB` | `#EEF1FE` | `ph-users-three` |

### États de l'icône du tray
| État | Couleur | Traitement |
|---|---|---|
| Repos | `#3D4351` | contour monochrome (template — s'adapte clair/sombre) |
| Enregistrement | `#FF3B30` | rempli |
| Transcription | `#FF9500` | rempli |
| Terminé (bref ~1,5 s) | `#34C759` | rempli puis retour repos |
| Erreur (bref) | `#8E8E93` | rempli puis retour repos |
Cycles : Dictée/Journal → Repos → 🔴 → 🟠 → 🟢 → Repos. Réunion → 🔴 continu, 🟢 bref à l'arrêt.

---

## Assets
Dossier **`icons/`** — icônes prêtes à intégrer, générées depuis le logo WaveMark :
- **App / Dock / barre des tâches :** `app-icon.svg` + `app-icon-256/512/1024.png` (carré indigo rempli, ondes blanches).
- **Tray par état :** `tray-idle` (contour), `tray-recording`, `tray-transcribing`, `tray-done`, `tray-error` — chacun en `.svg` + PNG 16/32/64/128.
- **Masque macOS :** `tray-template.svg` (+ PNG) — icône monochrome noire pour `QIcon::setIsMask(true)` / template image de la barre de menus.

**Polices :** IBM Plex Sans + IBM Plex Mono ([Google Fonts](https://fonts.google.com/specimen/IBM+Plex+Sans) / [IBM Plex](https://github.com/IBM/plex), licence OFL). **Embarquer dans les ressources Qt** (ne pas dépendre des polices système) pour un rendu identique sur les 3 OS.

**Icônes UI :** [Phosphor Icons](https://phosphoricons.com/) style Regular (le poids Fill est réservé à l'icône tray active et à `ph-record-fill`). Utiliser un jeu SVG Phosphor dans les ressources Qt.

Empaqueter ensuite en `.icns` (macOS) et `.ico` (Windows) à partir des PNG.

---

## Files
Dans ce paquet :
- **`IMPLEMENTATION_SPEC.md`** — ⭐ **plan de build ordonné, étape par étape, pour Claude Code** (commence par le thème centralisé palette + QSS, puis chaque écran, avec critères d'acceptation). **Point d'entrée pour l'implémentation.**
- **`DESIGN.md`** — guide de design complet : tokens, typo, composants, états, **correspondance Qt (widgets + palette C++ + extraits QSS)** et checklist. **À lire en premier.**
- **`Guide-Design.dc.html`** — styleguide visuel (ouvrir dans un navigateur pour voir les couleurs, la typo, les composants et la planche d'icônes).
- **`debriefMeet-C.dc.html`** — ⭐ **maquette de référence à implémenter** (direction C).
- `debriefMeet.dc.html` (direction A) et `debriefMeet-B.dc.html` (direction B) — contexte uniquement, ne pas implémenter.
- `WaveMark.dc.html` / `Swatch.dc.html` — composants d'aperçu utilisés par les maquettes.
- `support.js` — runtime d'aperçu (nécessaire seulement pour ouvrir les `.dc.html` dans un navigateur ; **ne pas porter**).
- **`icons/`** — tous les assets d'icônes.

### Comment lire une maquette `.dc.html`
Ouvrir le fichier dans un navigateur pour le rendu. Pour la spec exacte : lire le template (markup entre les `<x-dc>`) — tous les styles sont inline et exacts — et la classe `Component` en bas pour les données et la logique d'état (mapping des états, cycle du chrono, comportement `onStart`). Ignorer la mécanique `{{ }}` / `sc-for` / `sc-if` : c'est juste du templating d'aperçu.
