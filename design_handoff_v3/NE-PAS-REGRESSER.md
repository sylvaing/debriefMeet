# Ne pas régresser — journal des correctifs, défauts ouverts, contrats testés

> Annexe du `README.md`. §1 : ce qui a **déjà été cassé puis réparé** — presque tout vient
> d'un retour terrain, et une refonte qui refait le geste d'origine rejouera le bug.
> §2 : ce qui est **encore ouvert** et mérite une décision de design.
> §3 : ce que des **tests figent** — le modifier n'est pas interdit, mais doit être annoncé.

---

## 1. Correctifs graphiques déjà passés

### 1.1 Série initiale (implémentation de la maquette, 2026-07)

Onze correctifs listés dans `../design_handoff_debriefmeet/CHANGELOG_v2.md`, tous appliqués et
encore en vigueur. Les cinq qui piègent systématiquement :

| # | Le piège | La règle qui en est sortie |
|---|---|---|
| 2 | `QToolButton` rendu avec son cadre natif | `QToolButton { border: none; background: transparent; }` global ; l'engrenage ne prend un fond que `:checked` |
| 4 | Filets de séparation absents entre les lignes | le filet est porté par `QTableView::item { border-bottom }` **et** doit être redessiné par tout délégué qui peint lui-même (voir §2.1 : ce n'est toujours pas complet) |
| 5 / 11 | Menu du tray rendu en natif, puis trop gris | `QMenu#trayMenu` stylé, fond `rgba(247,248,250,.93)` — pas de flou réel possible |
| 6 | Liseré de focus système sur le champ de recherche | `QLineEdit#searchField:focus` neutralisé explicitement |
| 8 / 10 | `QComboBox` / `QSpinBox` natifs | chevrons Phosphor custom via `::down-arrow`, `::up-button`, `::down-button` |

Deux pièges structurels trouvés au passage, toujours d'actualité :

- **Ne pas poser de feuille de style locale sur un ancêtre** (ici le `QWidget` de la toolbar) :
  sous le style natif macOS, elle casse la résolution des pseudo-états `:checked` des enfants.
  Tout passe par des sélecteurs nominatifs dans la feuille globale.
- **`QSvgRenderer` ne résout pas `fill="currentColor"`** (rendu noir) : la couleur est
  substituée dans le texte du SVG avant rendu.

### 1.2 Journal daté

| Date | Symptôme constaté | Cause réelle | Ce qui protège aujourd'hui |
|---|---|---|---|
| 2026-07-27 | La réunion en cours apparaissait **deux fois** dans le tableau | son `transcription.md` existe dès le démarrage, et la ligne « en cours » la représentait déjà | la réunion active est exclue du listing tant qu'elle enregistre |
| 2026-08-04 | **Crash de l'application** juste après un export de diagnostic réussi | un nom d'icône inventé (`file-zip`), absent des SVG embarqués, lu sans garde | test statique (analyse AST) : toute icône référencée dans le code doit exister |
| 2026-08-05 | En-têtes du tableau Lexique **tronqués des deux côtés** | Qt centre puis tronque un en-tête plus large que sa colonne | libellés courts (« Entendu », « À écrire »), explication déplacée en note et en infobulle |
| 2026-08-10 | Texte **invisible pendant la saisie** d'une cellule | l'éditeur du délégué est un `QLineEdit` sans `objectName` : il héritait du style des champs de formulaire (padding 10 px, 14 px → hauteur 42 px) écrasé dans une ligne de 30 px | règle dédiée `QAbstractItemView QLineEdit` (padding 0 4, 13 px, hauteur libre) |
| 2026-08-14 | Sous GNOME : icône de tray **illisible**, **aucune action** au clic, fenêtre **sans contour** | `setIsMask` est un mécanisme macOS ignoré ailleurs ; StatusNotifierItem n'appelle jamais `Activate` ; Wayland ne dessine pas d'ombre | trois branches Linux explicites (voir `CONTRAINTES-PLATEFORMES.md` §3.4) |
| 2026-08-18 | Icône de tray Linux = **carré blanc uni**, sans la marque | corrigée en « blanc **plein** » : le WaveMark rempli peint ses barres en blanc sur le carré | une icône monochrome claire s'obtient **en contour**, jamais en plein |
| 2026-08-20 | Dialogue d'association **sans aucun bouton visible** sur un événement à ~34 invités | la carte débordait de l'écran ; `AlignCenter` sert le `sizeHint` sans borner | hauteur de carte plafonnée, **corps défilant** entre en-tête et pied fixes ; carte élargie à 580 ; « Tout cocher » + compteur ; pré-cochage limité à 8 personnes |
| 2026-08-20 | Rectangle gris dans la carte, **invisible sur macOS** | sous Fusion, le viewport d'une zone défilante peint son fond ; une palette est écrasée par le `QWidget {…}` global | feuille de style posée **sur le viewport seul** |
| 2026-08-21 | Aucun retour visuel pendant les traitements lancés depuis l'historique | seuls les enregistrements pilotaient l'icône | arbitre central : rouge enregistrement > flash de fin > orange job > repos |
| **2026-08-24** | Le bouton « Générer le CR » **peint par-dessus l'icône calendrier** (macOS, Windows, Linux) | la largeur de colonne était restée calée sur 2 boutons après l'ajout d'un 3ᵉ ; le délégué construit ses zones depuis le bord droit **sans clipper** | largeur **dérivée** de `NB_BOUTONS_REUNION` / `NB_FLECHES_REUNION`, plus un test qui compare les `visualRect` réels des deux colonnes |
| 2026-08-24 | Une erreur **à chaque frappe clavier** (Windows) quand la cellule courante est dans la colonne d'actions | Qt route aussi les `QKeyEvent` vers `editorEvent`, qui lisait une position de souris | filtrage du type d'événement **avant** toute lecture de position |
| 2026-08-24 | « Quitter » **inerte** sous Linux : plus aucune sortie de l'app | DBusMenu ne transporte pas de `QWidgetAction` | `QAction` simple sous Linux, signal `triggered` branché dans les deux cas |
| 2026-08-26 | Un CR collé dans une note Pipedrive affichait `**gras**` en clair | un éditeur riche ne met en forme que ce qu'il reçoit **déjà en HTML** | copie riche + le bouton de copie devient un *split button* (clic = mis en forme, flèche = choix du format) |
| 2026-09-02 | Dans les deux assistants, le bouton « Créer un compte » ne **se voyait pas comme cliquable** | c'étaient les 2 seuls `QPushButton` sans `objectName` de tout `ui/` ; la feuille de style ne donne fond et bordure qu'aux boutons nommés | tout bouton de page d'assistant doit porter un nom de style **et** une icône (test sur les pages réelles) |
| 2026-09-02 | La maquette de dernière étape affirmait « Diarization activée » **pendant** le téléchargement et **après un échec** | l'illustration d'arrivée était toujours visible | elle n'apparaît qu'au succès ; un ressort de centrage évite la barre de progression seule en haut du vide |

> **Méthode qui a sorti les deux derniers** : *rendre les écrans en offscreen et les regarder*,
> pas relire le code. Les scripts `rendre_captures*.py` de ce paquet font exactement ça.

---

## 2. Défauts encore ouverts — à trancher par la refonte

Les points 2.1 à 2.5 sont **visibles dans les captures jointes**. Les suivants viennent de la
lecture du code.

### 2.1 Le filet de séparation s'arrête au milieu du tableau
Visible sur `captures/01-reunion-liste.png` : la ligne grise sous chaque réunion s'interrompt
après la colonne DURÉE. Les colonnes ÉTAT, calendrier et actions sont peintes par des délégués
qui ne dessinent pas le `border-bottom` du QSS. Soit le filet devient l'affaire du fond de
ligne partagé, soit le design assume un filet partiel — mais pas par accident.

### 2.2 Les ascenseurs ne sont jamais stylés
Aucun `QScrollBar` dans la feuille de style : partout où ça défile (pages de Préférences, liste
des prompts, tableau du lexique, corps de dialogue), l'ascenseur est celui du système — épais
et gris sous Fusion/Linux, discret sous macOS. C'est aujourd'hui l'élément le plus « hors
charte » de l'interface.

### 2.3 Le tableau du Lexique ne suit pas la charte des autres tableaux
`captures/06-preferences-6-lexique.png` : grille visible, en-têtes **centrées** (alors que les
tableaux d'historique sont sans grille et alignés à gauche), lignes de hauteur native. C'est un
`QTableWidget` brut, sans les délégués maison.

### 2.4 La barre d'auto-enregistrement affiche un « ✓ » textuel
La spécification demandait une icône `check-circle` verte ; c'est un caractère dans le libellé,
donc gris et dépendant de la police.

### 2.5 Rectangles de focus visibles sous Fusion
Item sélectionné de la nav des Préférences, cellule courante d'un tableau : un cadre de focus
apparaît (visible sur les captures, rendues en Fusion comme sous Linux). Il n'y a **aucun style
de focus clavier** défini par ailleurs — ni pour les boutons, ni pour les champs (seule la
bordure de champ change de couleur). L'accessibilité clavier est un angle mort complet.

### 2.6 Aucun état vide
Il n'y a pas d'écran « aucune réunion pour l'instant », ni « aucun résultat » quand la recherche
ne trouve rien : le tableau se vide et laisse un grand blanc. Seule la page Dictée a un état
vide — et son texte se casse en lignes très courtes (`captures/04-dictee.png`), la largeur du
paragraphe étant mal contrainte.

### 2.7 Une barre de navigation à un seul onglet
En mode distant — **le défaut, donc le cas de la majorité des postes** — la barre ne contient
que « Réunion » et l'engrenage. Un onglet unique est une affordance douteuse. Faut-il masquer
la barre d'onglets, la remplacer par un titre de page, ou assumer l'onglet seul ?

### 2.8 La colonne d'actions est muette
Quatre icônes 30 × 30 par ligne, sans libellé : « Générer le CR », « Copier le CR », « Copier le
fichier », « ⋯ ». Le sens n'est accessible qu'en infobulle, et deux d'entre elles portent la même
icône `copy`. C'est la zone la plus utilisée de l'app, et la moins lisible.

### 2.9 Les jobs longs n'ont ni progression ni annulation
Un CR Mistral dure plusieurs minutes. Le seul retour est l'icône d'état orange, l'icône de
l'opération sur la ligne, et une infobulle. Pas de barre, pas d'estimation, pas de bouton
« Annuler », et le résultat arrive dans un dialogue modal qui peut surgir pendant autre chose.

### 2.10 La colonne « lien calendrier » est une colonne fantôme
34 px, en-tête vide, invisible tant que BlueMind n'est pas configuré, et porteuse de trois états
différents (associé / associable / rien) qu'aucune légende n'explique.

### 2.11 Divers
- **Infobulles** : celles de Qt, non stylées, sur toute l'application.
- **Titres longs** : élidés dans la colonne TITRE, sans infobulle pour lire la suite.
- **Pas de titlebar maison** : la constante `TITLEBAR_H = 40` ne sert plus. La fenêtre n'a donc
  aucune identité en haut sous Windows/Linux, où le bandeau système est neutre.
- **Deux identités d'icône** : l'icône d'application est un carré **bleu dégradé**, la marque
  dans l'app un carré **indigo plat**. Personne n'a tranché.
- **Aucun compteur** : pas de « 73 réunions », pas de repère de volume dans l'historique.
- **Mode sombre inexistant** — et coûteux à ajouter (§1 de `CONTRAINTES-PLATEFORMES.md`).

---

## 3. Ce que des tests figent

Ces contrats sont vérifiés à chaque livraison (~1 730 tests, dont une trentaine de fichiers
d'interface). Les changer est possible, mais doit être **explicite** dans la proposition — un
test rouge bloque la livraison.

| Contrat | Pourquoi il existe |
|---|---|
| Toute icône référencée existe dans les 40 SVG embarqués | un nom inventé a planté l'app en production |
| La largeur de la colonne d'actions couvre le **nombre réel** de boutons produits, et les `visualRect` des colonnes voisines ne se chevauchent pas | la régression du 2026-08-24 |
| Chaque page d'assistant n'a que des boutons **nommés et porteurs d'icône** | les boutons invisibles du 2026-09-02 |
| L'illustration d'arrivée d'un assistant est **invisible** en attente et en échec (test sur `isVisibleTo`, pas sur la présence d'un pixmap) | la maquette qui mentait |
| Les états de l'icône de tray sont comparés **sur l'image rendue**, pas sur l'objet `QIcon` | fige la forme *et* la teinte (donc *quelle* opération est signalée) |
| Chaque signal de fin d'un gestionnaire de job est déclaré à l'arbitre d'état | sinon l'icône reste orange jusqu'à la fin de la session, sans erreur |
| Les tests de menus portent sur l'**effet** d'une activation, pas sur le libellé | deux tests d'ordre de menu sont restés verts pendant tout le temps où « Quitter » était mort |
| Le QSS global se charge et ses jetons d'icônes sont substitués | le chargement du thème est un point de passage unique |
| Le sélecteur de modèles de CR n'énumère jamais une valeur absente de la liste centrale | un modèle proposé mais refusé au démarrage suivant |

### Deux réflexes de travail qui ont fait leurs preuves ici

1. **Rendre l'écran et le regarder** (`QT_QPA_PLATFORM=offscreen`, `widget.grab().save(...)`) :
   les deux derniers défauts d'affordance étaient invisibles à la lecture du code.
2. **Vérifier un garde-fou par régression simulée** : casser volontairement le code et
   s'assurer que le test échoue. Plusieurs tests « verts pour de mauvaises raisons » ont été
   trouvés comme ça.
