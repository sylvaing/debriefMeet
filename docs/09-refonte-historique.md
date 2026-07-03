# Spec — Refonte de l'écran Historique

> **Statut :** ✅ **implémentée et validée (macOS, 2026-06-26)** — listing filtré, colonne d'actions
> par ligne (icônes Tabler embarquées, encre atténuée), sélection multiple + suppression de masse,
> `GestionnaireDiarization` persistant, notification macOS + clic, rafraîchissement live
> (`QFileSystemWatcher`), fenêtre blanche. Tests : `test_historique_diarization.py` + `test_icones.py`
> + helpers `test_fichiers.py`. **Suite : 340 passed.** Validation GUI manuelle faite par l'utilisateur.
> Refonte de [`ui/historique.py`](../src/debrief_meet/ui/historique.py) : passage d'actions
> globales (boutons en bas, sélection unique) à une **colonne d'actions par ligne**, sélection
> multiple, diarization en tâche de fond persistante et rafraîchissement live du listing.

---

## 1. Objectifs

1. Lister **uniquement les transcriptions** (réunions et journal), pas les fichiers dérivés.
2. Une **colonne d'actions par ligne** (icônes + tooltips) au lieu des boutons globaux.
3. **Sélection multiple** (`⌘` / `⇧`) → suppression en masse.
4. Diarization **en arrière-plan** qui **survit à la fermeture** de la fenêtre + notification macOS.
5. **Rafraîchissement live** du listing (nouvelle réunion, génération terminée) sans changer
   d'onglet ni rouvrir.

---

## 2. Listing (panneau gauche)

- **Réunions** : les `.md` « bruts » du dossier réunions, **en excluant** les `*_locuteurs.md`
  et tout fichier audio (`.opus`/`.wav`). *(Aujourd'hui `lister_enregistrements` fait `glob("*.md")`
  → il faut filtrer les `_locuteurs.md`.)*
- **Journal** : les `.md` du dossier journal (inchangé).
- Tri du plus récent au plus ancien.
- **Onglets conservés** : Réunions / Journal.
- **Sélection multiple** : `ExtendedSelection` (`⌘`-clic = ajout/retrait, `⇧`-clic = plage).

### 2.1 Indicateurs d'état par ligne (réunions)

Chaque ligne montre d'un coup d'œil :

- 🎙️ **audio retenu présent** (au moins une piste `_moi`/`_systeme` existe à côté du `.md`) ;
- 👥 **locuteurs déjà générés** (`<stem>_locuteurs.md` existe).

Ces deux états pilotent le grisage des icônes (cf. §3.2).

---

## 3. Colonne d'actions (par ligne, à droite)

Icônes alignées à droite de chaque ligne, **tooltip au survol**. Ordre imposé :

| # | Action | Tooltip | Cible |
|---|---|---|---|
| 1 | **Copier la transcription** | « Copier la transcription » | presse-papier |
| 2 | **Générer les locuteurs** | « Générer les locuteurs » | diarization |
| 3 | **Ouvrir** | « Ouvrir la transcription » | `open` |
| 4 | **Révéler dans le Finder** | « Révéler dans le Finder » | `open -R` |
| 5 | **Supprimer l'audio retenu** | « Supprimer l'audio (garde le débrief) » | pistes `.opus`/`.wav` |
| 6 | **Tout supprimer** | « Tout supprimer (transcription + locuteurs + audio) » | `.md` + `_locuteurs.md` + audio |

- **Icônes : fonte Tabler embarquée (✅ implémentées 2026-06-26)** : ni icônes Qt standard
  (rendu inadapté), ni dessins `QPainter` (jamais exactement l'aperçu validé) → on peint les
  glyphes de la **fonte Tabler outline** (`ui/assets/tabler-icons.ttf`, **licence MIT**, ~2,8 Mo),
  ce qui reproduit **exactement** l'aperçu. API dans [`ui/icones.py`](../src/debrief_meet/ui/icones.py) :
  `icone_glyphe(nom, intensite=0.72)` (boutons — peint dans la **couleur de texte du thème à 72 %
  d'opacité** pour un trait perçu plus léger ; *pas* de `isMask`, donc couleur figée à la création ;
  Qt grise quand même l'état désactivé) et `pixmap_glyphe(nom, alpha=0.55)` (indicateurs, plus
  discrets). La fonte est chargée une fois via
  `QFontDatabase.addApplicationFont`. Codepoints Tabler : micro=`U+EAF0`, personnes=`U+EBF2`,
  copier=`U+EA7A`, note=`U+EAA2`, dossier=`U+FAF7`, muet (volume-off)=`U+F1C3`,
  corbeille=`U+EB41`, attente (loader-2)=`U+F226`.
  L'icône **du tray** (carré arrondi+onde) reste dessinée maison — c'est l'identité de l'app, pas une action.
  Aperçu : [`assets/apercu-icones-historique.html`](assets/apercu-icones-historique.html).
  *(Packaging Phase 4 : embarquer le `.ttf` — déjà déclaré `artifacts=["*.ttf"]` dans pyproject ;
  prévoir `--add-data` PyInstaller.)*

### 2bis. Style de la liste et des boutons (alignés sur l'aperçu validé)

- **Boutons d'action plats** : `QToolButton` sans cadre (`_STYLE_BOUTON`), fond léger au survol,
  curseur main, `iconSize` 20.
- **Liste** : conteneur **arrondi** (border-radius 12, hairline), **séparateurs fins** entre lignes,
  **pas de zébrage** (`setAlternatingRowColors(False)`), sélection discrète bleutée (`_STYLE_LISTE`).
- **Lignes** : marges confortables (≈12/9 px) pour des rangées aérées comme l'aperçu.

  | # / rôle | Élément | Glyphe |
  |---|---|---|
  | Indicateur | Enregistrement (audio) présent | **micro** |
  | Indicateur | Locuteurs générés | **deux personnes** |
  | #1 | Copier la transcription | **deux feuillets décalés** |
  | #2 | Générer les locuteurs | **deux personnes** *(même glyphe que l'indicateur — confirmé : le contexte les distingue, indicateur gris à gauche vs bouton)* |
  | #3 | Ouvrir la transcription | **feuille de texte** (page avec lignes) |
  | #4 | Révéler dans le Finder | **dossier ouvert** |
  | #5 | Supprimer l'audio | **haut-parleur barré** |
  | #6 | Tout supprimer | **corbeille** |

  - **Spécs de dessin** : repère logique commun (≈100×100 comme `icone_pour_etat`), épaisseur de
    trait calée sur l'icône du tray, rendu haute résolution (devicePixelRatio), **jamais de
    couleur ni de remplissage plein** (sauf petits aplats type tête de personne si besoin).
  - **État « work in progress »** (#2 pendant un job) : indicateur de progression circulaire
    (arc/spinner) **animé**, monochrome, non cliquable — glyphe à finaliser au dessin.
  - **Réf. visuelle** : le document d'aperçu rend ces glyphes via la fonte Tabler (outline) comme
    *proxy* du style ; les fichiers définitifs sont les versions `QPainter` ci-dessus.

> Noms de glyphes (`ui/icones.py`) : `micro`, `personnes`, `copier`, `note`, `dossier`, `muet`,
> `corbeille`, `attente` (spinner). Tests : `test_icones.py` (rendu non vide, template, distincts).

### 3.1 Sémantique des actions

- **#1 Copier** : copie le contenu texte. **Si `<stem>_locuteurs.md` existe → on copie la
  version locuteurs** ; sinon le `.md` brut.
- **#5 Supprimer l'audio** : supprime les pistes retenues, **garde** le `.md` et le
  `_locuteurs.md`. La diarization ne sera plus regénérable.
- **#6 Tout supprimer** : supprime le `.md`, le `_locuteurs.md` (si présent) **et** l'audio.

### 3.2 Règles de grisage (réunions)

| Icône | Grisée (désactivée) quand | Tooltip alternatif |
|---|---|---|
| #2 Générer locuteurs | locuteurs **déjà générés** *(déjà dispo)* **ou** aucun audio retenu | « Locuteurs déjà générés » / « Aucun audio retenu » |
| #5 Supprimer l'audio | **aucun** audio retenu | « Aucun audio à supprimer » |
| #1, #3, #4, #6 | jamais (toujours actives) | — |

> **Conséquence à noter** : #2 grisée une fois les locuteurs générés ⇒ **pas de régénération**
> par l'icône. Pour régénérer, l'utilisateur supprime d'abord `_locuteurs.md` (via #6 partiel ?
> ou suppression manuelle). *À surveiller à l'usage ; on pourra ajouter un menu contextuel
> « Régénérer » plus tard si le besoin se confirme.*

### 3.3 Onglet Journal — colonne réduite

Le Journal n'a ni audio ni locuteurs → colonne **réduite** : **#1 Copier**, **#3 Ouvrir**,
**#4 Révéler**, **#6 Tout supprimer** (ici « tout supprimer » = le seul `.md`). Pas de #2 ni #5.

---

## 4. Génération des locuteurs — état visuel

- Clic sur **#2** d'une ligne → cette icône devient **non cliquable** et est remplacée par une
  **icône « work in progress »** (sablier/spinner animé) pendant tout le job.
- **Un seul job à la fois** (contrainte moteur actuelle) : pendant un job, les icônes #2 de
  **toutes** les autres lignes sont **désactivées** (pas de file d'attente en v1).
- À la fin : la ligne se rafraîchit (👥 locuteurs générés ⇒ #2 grisée, cf. §3.2), l'icône WIP
  redevient l'icône normale grisée.

---

## 5. Continuité en tâche de fond + notification

- **Fermer l'Historique n'interrompt pas** une génération en cours.
- **Architecture** : le job de diarization ne doit plus appartenir à la fenêtre (`QThread(self)`
  meurt à la fermeture). On introduit un **gestionnaire persistant** vivant dans
  `__main__` (ou un orchestrateur), p. ex. `GestionnaireDiarization(QObject)` :
  - détient l'unique worker/thread et l'état « job en cours sur `<chemin_md>` » ;
  - signaux : `demarre(chemin_md)`, `termine(chemin_md, sortie)`, `echoue(chemin_md, message)` ;
  - méthode `lancer(chemin_md)` (refuse si un job tourne déjà) et `job_en_cours() -> Path | None`.
- La **fenêtre Historique observe** ce gestionnaire :
  - à l'ouverture, elle interroge `job_en_cours()` pour **restaurer l'état WIP** sur la bonne ligne ;
  - elle se connecte aux signaux pour rafraîchir en direct (cf. §6).
- **Notification système macOS** à la fin d'un job :
  - via `QSystemTrayIcon.showMessage(...)` (le tray existe déjà, aucune dépendance ajoutée) →
    s'affiche dans le Centre de notifications ;
  - émise **toujours** ; particulièrement utile quand la fenêtre est fermée.
  - **Clic sur la notification (décision actée)** : **ouvre la fenêtre Historique** (la crée si
    fermée, la ramène au premier plan sinon), bascule sur l'onglet **Réunions** et **sélectionne
    la ligne** de la réunion concernée (le `.md` source). *Ne pas* ouvrir directement le
    `_locuteurs.md` : on amène l'utilisateur dans l'Historique, ligne pré-sélectionnée.
  - **Implémentation** : `QSystemTrayIcon.messageClicked` n'indique pas *quelle* notification a
    été cliquée → le `GestionnaireDiarization` mémorise le **dernier job terminé** (`chemin_md`)
    et le fournit au handler de clic pour cibler la bonne ligne (suffisant puisqu'un seul job à
    la fois). Le handler vit hors de la fenêtre (dans `__main__`/le gestionnaire) pour fonctionner
    même Historique fermé.

---

## 6. Rafraîchissement live du listing

Le listing doit se mettre à jour **sans changer d'onglet ni rouvrir** quand :

- une **nouvelle réunion** se termine (un `.md` apparaît) ;
- une **génération de locuteurs** se termine (👥 passe à « généré ») ;
- de l'audio est supprimé (#5) ou un enregistrement supprimé (#6).

**Mécanisme** : `QFileSystemWatcher` sur les dossiers réunions + journal → sur changement,
recharge la liste de l'onglet concerné. Avantage : capte aussi les modifications externes
(suppression dans le Finder). Alternative/complément : le `OrchestrateurReunion` émet un signal
de finalisation que l'Historique écoute (couplage plus direct mais moins universel).

**Contraintes du rafraîchissement** :

- **préserver la sélection** courante (par chemin, pas par index) ;
- **préserver l'état WIP** d'une ligne en cours de génération (ne pas réinitialiser l'icône) ;
- éviter le rechargement en rafale (anti-rebond léger si nécessaire, cf. `SurveillantPeripheriques`).

---

## 7. Suppression en masse

- Avec **plusieurs lignes sélectionnées**, une suppression s'applique à **toute la sélection**,
  avec **une seule confirmation** récapitulant le nombre d'éléments concernés.
- Actions « de masse » : **#5 (supprimer audio)** et **#6 (tout supprimer)**. Les actions
  #1–#4 (copier/ouvrir/révéler) restent **mono-ligne** (pas de sens en masse).
- Raccourci clavier **`Suppr`** = **#6** (tout supprimer) sur la sélection.
- La confirmation distingue les cas (« Supprimer N enregistrement(s) ? » vs « Supprimer
  l'audio de N réunion(s) ? »).

---

## 8. Découpage proposé (implémentation, plus tard)

1. **Modèle de listing** : filtrer les `_locuteurs.md` ; helper « état » par réunion
   (audio présent ?, locuteurs générés ?). Tests purs.
2. **Ligne avec colonne d'actions** : widget de ligne (`setItemWidget` sur `QListWidget`, ou
   `QTableView` + delegate) ; icônes + tooltips + règles de grisage. Tests qtbot (présence,
   activation/désactivation selon état).
3. **Sélection multiple + suppression de masse** : `ExtendedSelection`, confirmation unique,
   touche `Suppr`. Tests (sélection de N, suppression, rechargement).
4. **`GestionnaireDiarization` persistant** (hors fenêtre) + signaux + restauration WIP à
   l'ouverture + notification macOS. Tests (un seul job, états émis, restauration).
5. **Rafraîchissement live** (`QFileSystemWatcher`) avec préservation sélection/WIP. Tests
   (apparition d'un `.md`, fin de génération → ligne mise à jour).

> Definition of Done habituelle : `pytest -m "not integration"` vert + notice « Comment tester »
> (ouvrir l'Historique, lancer une réunion en parallèle → la liste s'actualise ; générer les
> locuteurs, fermer la fenêtre → notification à la fin ; sélection multiple → suppression de masse).
