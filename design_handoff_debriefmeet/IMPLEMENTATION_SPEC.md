# Spec d'implémentation — Refonte debriefMeet (pour Claude Code / Sonnet)

> **But de ce document.** Fournir un plan de build **ordonné, exact et exécutable étape par étape**. Chaque étape a : un *objectif*, les *fichiers* à créer/modifier, le *contenu/exigences* précis, et des *critères d'acceptation*. Faire les étapes **dans l'ordre** ; ne pas commencer une vue avant que le thème centralisé (Étape 2) soit en place. Commiter après chaque étape.

## Hypothèses & adaptation
- **Cible : PySide6 (Qt for Python) Widgets + QSS.** Toutes les valeurs viennent de `DESIGN.md` et des maquettes (`debriefMeet-C.dc.html` = référence).
- **Imports PySide6** : `from PySide6.QtWidgets import ...`, `from PySide6.QtGui import ...`, `from PySide6.QtCore import ...`. Signaux/slots : `Signal`, `Slot` depuis `PySide6.QtCore`. Ressources : préférer des **chemins de fichiers** (`Path(__file__).parent / "resources" / ...`) ou un module `.qrc` compilé avec `pyside6-rcc` ; les exemples ci-dessous utilisent le préfixe `:/` en supposant un `.qrc` compilé — adapter en chemins directs si le projet n'utilise pas `.qrc`.
- Le fichier **`theme.qss` est réutilisable tel quel** (le QSS est identique en Python).
- **Avant de commencer**, exécuter l'Étape 0 (découverte) et **confirmer la structure** du projet (packages, entrée `main`, gestion des captures).

---

## Étape 0 — Découverte & préconditions
**Objectif :** comprendre le codebase existant avant d'écrire quoi que ce soit.

**À faire :**
1. Confirmer : PySide6 (version), gestionnaire de deps (pip/poetry/uv), packaging (PyInstaller/briefcase/…), Widgets (attendu).
2. Repérer où sont créés `QApplication`, la fenêtre principale, et l'éventuel `QSystemTrayIcon` actuel.
3. Repérer le fichier de ressources `.qrc` (ou en prévoir un).
4. Lister les vues existantes (les 2 écrans actuels : Historique, Préférences) et comment elles sont instanciées.
5. Noter les patterns du projet (nommage, organisation des dossiers, gestion d'état, modèles de données des captures).

**Critères d'acceptation :** un court compte-rendu en tête de PR indiquant stack détectée, emplacement des points d'ancrage, et le plan d'insertion. **Ne rien styliser en dur** dans les vues : tout passe par le thème (Étape 2).

---

## Étape 1 — Assets & ressources
**Objectif :** rendre disponibles polices et icônes via le système de ressources Qt.

**Fichiers :**
- `resources/fonts/` : IBM Plex Sans (400/500/600/700) + IBM Plex Mono (400/500) en `.ttf` (OFL, https://github.com/IBM/plex).
- `resources/icons/` : copier le dossier `icons/` du handoff (SVG d'états tray, `app-icon.*`, `tray-template.*`, `debriefMeet.icns`, `debriefMeet.ico`).
- Icônes UI **Phosphor** (Regular) en SVG dans `resources/icons/phosphor/` (jeu utilisé : `microphone`, `users-three`, `notebook`, `clock-counter-clockwise`, `gear`, `magnifying-glass`, `copy`, `users`, `file-text`, `folder`, `microphone-slash`, `trash`, `caret-up-down`, `caret-up`, `caret-down`, `check`, `check-circle`, `record-fill`, `waveform`, `stop`, `plus`, `minus`, `brain`, `folders`, `chat-text`, `sliders-horizontal`, `keyboard`, `bug`, `arrow-square-out`, `sign-out`, `cursor-click`, `list`, `warning-circle`).
3. `resources/app.qrc` : enregistrer polices, icônes et `theme.qss`, puis compiler avec **`pyside6-rcc app.qrc -o resources_rc.py`** et l'importer une fois au démarrage. *(Alternative sans `.qrc` : référencer les fichiers par chemin absolu construit avec `pathlib.Path`.)*

**À faire :**
1. Charger les polices au démarrage, **après** `QApplication` et **avant** toute création de widget :
   ```python
   from PySide6.QtGui import QFontDatabase, QFont, QIcon
   for f in ["IBMPlexSans-Regular.ttf", "IBMPlexSans-Medium.ttf",
             "IBMPlexSans-SemiBold.ttf", "IBMPlexSans-Bold.ttf",
             "IBMPlexMono-Regular.ttf", "IBMPlexMono-Medium.ttf"]:
       QFontDatabase.addApplicationFont(str(FONT_DIR / f))
   app.setFont(QFont("IBM Plex Sans", 10))  # taille de base en pt, ajuster selon l'OS
   ```
2. Icône d'application : `app.setWindowIcon(QIcon(str(ICON_DIR / "app-icon-256.png")))` ; `.icns` pour le bundle macOS et `.ico` pour l'exe Windows au packaging (Étape 10).

**Critères d'acceptation :** `QFontDatabase.families()` contient « IBM Plex Sans » et « IBM Plex Mono » ; les ressources se chargent sans warning.

---

## Étape 2 — Thème centralisé (À FAIRE EN PREMIER, avant les écrans)
**Objectif :** une **source unique** pour couleurs, métriques et QSS. Aucune valeur hex/px en dur ailleurs dans le code.

### 2a. `src/ui/theme.py` — palette & métriques (PySide6)
Créer exactement (module unique importé partout ; `QColor` créé paresseusement pour éviter d'instancier avant `QApplication` — ici on stocke les hex en constantes et on expose des helpers) :
```python
"""Thème centralisé debriefMeet — source unique de vérité. Aucune valeur en dur ailleurs."""
from PySide6.QtGui import QColor

class C:  # ----- Couleurs (hex) -----
    # Accent (indigo)
    ACCENT = "#3B5BDB"; ACCENT_INK = "#2A46B8"; ACCENT_SOFT = "#EEF1FE"
    # Texte
    INK900 = "#1A1D23"; INK700 = "#344054"; INK600 = "#475467"
    INK500 = "#667085"; INK400 = "#7A828F"; INK350 = "#8A919E"
    INK300 = "#98A2B3"; INK200 = "#B0B7C0"
    # Surfaces & bordures
    SURFACE = "#FFFFFF"; SUNKEN = "#F6F7F9"; HEADER = "#FBFBFC"
    HOVER = "#FAFAFB"; BORDER = "#E7E9EE"; BORDER_SOFT = "#EFF1F4"; DIVIDER = "#F1F2F5"
    # États sémantiques (texte/icône + fond pastille)
    REC = "#FF3B30"; REC_BG = "#FFECEA"
    SUCCESS = "#1F9D6B"; SUCCESS_BG = "#E7F6EF"
    NEUTRAL = "#7A828F"; NEUTRAL_BG = "#F1F2F5"
    INFO = "#3B5BDB"; INFO_BG = "#EEF1FE"
    DANGER = "#B42318"; DANGER_BG = "#FEF3F2"
    # Icône tray par état d'activité
    TRAY_IDLE = "#3D4351"        # contour monochrome (template)
    TRAY_RECORDING = "#FF3B30"; TRAY_TRANSCRIBE = "#FF9500"
    TRAY_DONE = "#34C759"; TRAY_ERROR = "#8E8E93"

def color(hex_str: str) -> QColor:
    """QColor depuis un hex du thème (à appeler après QApplication)."""
    return QColor(hex_str)

class M:  # ----- Métriques (px) -----
    TITLEBAR_H = 40; TOOLBAR_H = 58; ROW_H = 52
    PAD_CONTENT = 20; PAD_FORM = 30; PREF_NAV_W = 208
    # Rayons
    R_WINDOW = 12; R_CARD = 9; R_BUTTON = 9; R_TILE = 7; R_PILL = 20; R_CHECK = 5
    # Espacement (× 4) : 4 8 12 16 20 24 28 32

SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"
```

### 2b. `resources/theme.qss` — styles QSS globaux
Créer exactement (chargé à l'Étape 2c). Ce QSS couvre ce qui est stylisable par feuille ; le reste (badges, barre d'accent de ligne, icône tray) est peint par délégué/générateur (Étapes 3/5/8).
```css
/* ---------- Base ---------- */
QWidget { font-family: "IBM Plex Sans"; font-size: 13px; color: #1A1D23; }
QMainWindow, QDialog { background: #FFFFFF; }

/* ---------- Champs ---------- */
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QAbstractSpinBox {
  background: #F6F7F9; border: 1px solid #E7E9EE; border-radius: 8px;
  padding: 10px 13px; font-size: 14px; color: #1A1D23; selection-background-color: #EEF1FE;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QAbstractSpinBox:focus { border-color: #3B5BDB; }
QComboBox::drop-down { border: none; width: 24px; }
QPlainTextEdit#promptEditor { font-family: "IBM Plex Mono"; font-size: 12.5px; }

/* ---------- Boutons ---------- */
QPushButton { font-size: 13.5px; font-weight: 600; border-radius: 9px; padding: 10px 18px; }
QPushButton#primary   { background: #3B5BDB; color: #fff; border: none; }
QPushButton#primary:hover { background: #2A46B8; }
QPushButton#secondary { background: #fff; color: #344054; border: 1px solid #D6D9DE; }
QPushButton#secondary:hover { border-color: #3B5BDB; color: #2A46B8; }
QPushButton#danger    { background: #FF3B30; color: #fff; border: none; padding: 10px 20px; }
QPushButton#danger:hover { background: #E0342A; }
QPushButton#destructive { background: #fff; color: #B42318; border: 1px solid #F4C9C7; }
QPushButton#destructive:hover { background: #FEF3F2; }

/* ---------- Onglets de navigation (toolbar) ---------- */
QToolButton#navTab { background: transparent; border: none; padding: 0 4px;
  font-size: 14px; font-weight: 600; color: #7A828F; }
QToolButton#navTab:checked { color: #2A46B8; border-bottom: 2px solid #3B5BDB; }

/* ---------- En-tête de tableau ---------- */
QHeaderView::section { background: #FBFBFC; color: #98A2B3; font-family: "IBM Plex Mono";
  font-size: 10px; text-transform: uppercase; border: none; padding: 9px 0; }
QTableView { background: #fff; border: none; gridline-color: transparent;
  selection-background-color: #EEF1FE; selection-color: #1A1D23; }

/* ---------- Sous-nav des préférences ---------- */
QListWidget#prefNav { background: #FBFBFC; border: none; border-right: 1px solid #EFF1F4; }
QListWidget#prefNav::item { padding: 8px 11px; border-radius: 8px; margin: 1px 8px;
  color: #667085; font-size: 13.5px; font-weight: 600; }
QListWidget#prefNav::item:selected { background: #EEF1FE; color: #2A46B8; }

/* ---------- Cases à cocher ---------- */
QCheckBox { font-size: 13.5px; spacing: 10px; }
QCheckBox::indicator { width: 19px; height: 19px; border-radius: 5px;
  border: 1.5px solid #CDD2DA; background: #fff; }
QCheckBox::indicator:checked { background: #3B5BDB; border-color: #3B5BDB;
  image: url(:/icons/phosphor/check-white.svg); }

/* ---------- Barre auto-save (préférences) ---------- */
QLabel#autosaveBar { background: #FBFBFC; border-top: 1px solid #E7E9EE;
  color: #667085; font-size: 12.5px; padding: 10px 20px; }
```

### 2c. Chargement du thème
Dans le `main` (après `QApplication`, après les polices) :
```python
from PySide6.QtCore import QFile, QIODevice
qss = QFile(":/theme.qss")            # ou open(THEME_QSS_PATH).read() si pas de .qrc
qss.open(QIODevice.ReadOnly)
app.setStyleSheet(bytes(qss.readAll()).decode("utf-8"))
```

**Critères d'acceptation :** le QSS se charge sans erreur ; un `QPushButton` avec `setObjectName("primary")` s'affiche indigo ; **aucune couleur hex n'apparaît ailleurs que dans `theme.py`/`theme.qss`**. Ajouter un `check-white.svg` (glyphe check blanc) dans les ressources pour l'indicateur coché.

---

## Étape 3 — Composants réutilisables
**Objectif :** briques transverses utilisées par plusieurs écrans.

**Fichiers (suggestion) :** `wavemark.py` (générateur d'icône), `status_pill.py` (util + délégué), `segmented.py`, `start_group.py` — adapter aux packages du projet.

**3a. Générateur d'icône WaveMark** — fonction `wavemark_icon(size, hex_color, filled) -> QIcon` produisant un `QPixmap` peint avec `QPainter`, pour l'icône d'état de la toolbar et du tray.
- Géométrie (carré de côté `S`) : rayon `0.27·S`, largeur barre `0.088·S`, gap `0.072·S`, épaisseur contour `0.06·S`, hauteurs des 4 barres = `0.29 · 0.50 · 0.235 · 0.41 × S`, barres centrées, rayon barre = largeur/2.
- **Rempli :** carré arrondi plein `color`, barres blanches.
- **Contour (template) :** fond transparent, carré arrondi `stroke color`, barres `color`.
- Peindre avec `QPainter` + `QPainterPath::addRoundedRect`, `Antialiasing`. *(Alternative : charger les SVG `resources/icons/tray-*.svg` déjà fournis et les teinter — mais le générateur permet la couleur exacte par état.)*

**3b. Badge d'état (pilule)** — préférer un **`QStyledItemDelegate`** (voir Étape 5) plutôt qu'un widget, pour l'usage tableau. Prévoir une petite fonction util qui, pour un `enum HistoryState { EnCours, Transcrit, AudioSeul, Locuteurs }`, renvoie `{ label, fg, bg, iconPath }` :
  - EnCours → « En cours », `Rec` / `RecBg`, `record-fill`
  - Transcrit → « Transcrit », `Success` / `SuccessBg`, `check-circle`
  - AudioSeul → « Audio seul », `Neutral` / `NeutralBg`, `waveform`
  - Locuteurs → « Locuteurs », `Info` / `InfoBg`, `users-three`
  - Rendu pilule : `radius 20`, padding `3 9 3 7`, `gap 6`, icône 13 px, texte 12 px/600.

**3c. Segmented control** (Réunions | Journal ; et onglets barre d'outils si besoin) — conteneur bordé `Border` radius 9, boutons `checkable` exclusifs ; actif = fond `Accent` texte blanc (segment) ou soulignement (onglets toolbar).

**3d. StartButtonGroup** — 3 boutons accolés (Dictée/Réunion/Journal) dans un `QFrame` bordé, séparateurs `Border`. États pilotés par l'état d'enregistrement global (Étape 7) :
  - repos : icône `Accent` + label `Ink700`, fond blanc ; hover fond `AccentSoft`.
  - actif (ce type) : fond `RecBg`, texte `Rec`, **point pulsant** rouge (petit `QWidget` animé via `QPropertyAnimation` sur l'opacité, 1.4 s, boucle) à la place de l'icône, **chrono mono** à droite.
  - désactivé (un autre enregistre) : `opacity .55` (via `QGraphicsOpacityEffect`), non cliquable.

**Critères d'acceptation :** un mini-harnais affiche : les 5 icônes d'état WaveMark, les 4 badges, le segmented control, et le StartButtonGroup dans ses 3 états. Comparer visuellement à la section 04/05 de `Guide-Design.dc.html`.

---

## Étape 4 — Coquille de la fenêtre (shell)
**Objectif :** fenêtre unique = Titlebar + Toolbar + zone de contenu empilée.

**Fichiers :** `src/ui/MainWindow.h/.cpp`.

**À faire :**
1. `QMainWindow` sans `QStatusBar` natif. Fenêtre redimensionnable ; taille par défaut ≈ 1000×660.
2. **Barre d'outils** (`QWidget` custom, hauteur 58, fond `Surface`, bordure basse `Border`, `QHBoxLayout` marges 0 20) contenant, dans l'ordre :
   - WaveMark 26 px (rempli, `Accent`) + label « debriefMeet » (15 px/700) + badge version mono (`0.1.0`, 10.5 px, bordure `Border`, radius 5).
   - 2 `QToolButton#navTab` checkable exclusifs : « Historique », « Préférences ».
   - `addStretch()`.
   - `StartButtonGroup` (Étape 3d).
   - Icône d'état WaveMark 24 px (reflète l'état d'enregistrement).
3. **Zone de contenu** : `QStackedWidget` avec 3 pages : `HistoryView`, `PreferencesView`, `RecordingView` (Étapes 5/6/7).
4. **Navigation** : les onglets basculent Historique/Préférences ; démarrer un enregistrement affiche `RecordingView` (sans changer l'onglet checké).
5. **Titlebar** : conserver la barre native de l'OS (titre discret). Ne pas réimplémenter de titlebar custom sauf si le projet le fait déjà.

**Critères d'acceptation :** la fenêtre s'ouvre, on bascule Historique↔Préférences via la toolbar sans passer par le tray ; le layout correspond aux maquettes.

---

## Étape 5 — Vue Historique
**Objectif :** tableau dense Réunions/Journal avec recherche et badges d'état.

**Fichiers :** `src/ui/HistoryView.*`, `src/model/CaptureModel.*` (hérite `QAbstractTableModel`), `src/ui/StatusPillDelegate.*`.

**À faire :**
1. **Sous-en-tête** (padding 14 20, bordure basse `BorderSoft`) : segmented « Réunions | Journal » à gauche ; `addStretch()` ; champ recherche 260 px (fond `SurfaceSunken`, bordure `Border`, radius 8, icône `magnifying-glass` `Ink300`, placeholder « Rechercher une réunion… »). La recherche filtre via un `QSortFilterProxyModel`.
2. **Modèle Réunions** : colonnes `type · titre · date · durée · état · actions`. `date`/`durée` en **mono** `Ink500`. `titre` 13.5/600 `Ink900` (ellipsis). `type` = `microphone` ou `users-three` `#6B7A78`.
3. **QTableView** :
   - Largeurs : type 40, titre `Stretch`, date 150, durée 74, état 116, actions 210 ; `column-gap` visuel via marges de cellule ~12. Hauteur de ligne **52** (`verticalHeader()->setDefaultSectionSize(52)`), en-têtes vertical masqué, sélection par ligne, pas de grille.
   - En-tête horizontal : styles QSS (Étape 2b), libellés `TITRE/DATE/DURÉE/ÉTAT`, sticky par défaut.
   - **Ligne sélectionnée** : fond `AccentSoft` + **barre latérale gauche 3 px `Accent`** — peinte dans le délégué (ou un délégué de première colonne). Hover : `SurfaceHover`.
   - **Colonne état** : `StatusPillDelegate` (peint la pilule via `enum HistoryState`, cf. 3b).
   - **Colonne actions** : délégué peignant des boutons 30×30 (icônes 16 `Ink300`) révélés au survol de la ligne ; hover d'un bouton → fond blanc + `AccentInk` + ombre légère. Actions Réunion : copier transcription, débrief locuteurs, ouvrir CR, ouvrir dossier, ignorer, supprimer.
4. **Onglet Journal** : même table, colonnes `icône notebook · nom fichier (mono) · note · actions` (copier, ouvrir, ouvrir dossier, supprimer).
5. **Ligne « En cours »** : quand un enregistrement de réunion est actif, la ligne du haut affiche l'état **En cours** (rouge) + durée live ; à l'arrêt elle bascule vers l'état final.

**Critères d'acceptation :** les 4 états s'affichent avec la bonne couleur/icône ; sélection = fond `AccentSoft` + barre d'accent ; recherche filtre ; actions visibles au survol.

---

## Étape 6 — Vue Préférences
**Objectif :** sous-nav verticale + pages empilées + auto-save.

**Fichiers :** `src/ui/PreferencesView.*` (+ une classe/page par section ou un `QStackedWidget` interne).

**À faire :**
1. Layout horizontal : `QListWidget#prefNav` (largeur 208, items icône+texte) à gauche pilotant un `QStackedWidget` à droite (padding 26 30, défilable via `QScrollArea`).
2. Sections (icônes entre parenthèses) et contenu — reproduire fidèlement (voir README §Préférences pour le détail) :
   - **Modèle** (`brain`) : combo `large-v3-turbo` (mono) + aide.
   - **Audio** (`waveform`) : combo micro, spin « Intervalle réunion » (`30 s`), 3 cases, badge « Diarization configurée » + bouton « Configurer… ».
   - **Dossiers** (`folders`) : 2 champs chemin (mono) + « Choisir… » + note.
   - **Prompts** (`chat-text`) : liste sélectionnable + éditeur titre / contenu (`QPlainTextEdit#promptEditor` mono) + case « Utiliser à la copie » + boutons +/−.
   - **Général** (`sliders-horizontal`) : combo langue, 2 cases (démarrage session, notifications).
   - **Raccourcis** (`keyboard`) : 3 capteurs de raccourci (affichage mono) + « Réinitialiser les défauts » + note.
   - **Journalisation** (`bug`) : 2 cases + emplacement mono + « Ouvrir le log » + « Vider le log » (`#destructive`).
3. **Barre d'auto-save** en bas (`QLabel#autosaveBar` : `check-circle` vert + « Modifications enregistrées automatiquement »). **Pas de boutons OK/Annuler.** Chaque changement persiste immédiatement (via `QSettings` ou le mécanisme existant).

**Critères d'acceptation :** navigation entre les 7 sections ; modifier une valeur la persiste sans validation ; la barre auto-save est visible en bas.

---

## Étape 7 — Enregistrement + machine d'état globale (cœur du comportement)
**Objectif :** l'enregistrement est un **état global persistant**, indépendant de la vue.

**Fichiers :** `src/core/RecordingController.*` (QObject singleton), `src/ui/RecordingView.*`.

**État & API (PySide6) :**
```python
from enum import Enum
from PySide6.QtCore import QObject, Signal, Slot, QTimer

class RecType(Enum):
    NONE = 0; DICTEE = 1; REUNION = 2; JOURNAL = 3

class RecordingController(QObject):
    started = Signal(RecType)
    tick = Signal(int)            # secondes écoulées (QTimer 1 s)
    stopped = Signal(RecType)
    showRequested = Signal()      # demander l'affichage de RecordingView

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = RecType.NONE
        self._elapsed = 0
        self._timer = QTimer(self); self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    def current(self) -> RecType: return self._current
    def elapsed_seconds(self) -> int: return self._elapsed

    @Slot(RecType)
    def start(self, t: RecType):
        if self._current == t:            # déjà en cours de ce type
            self.showRequested.emit(); return    # ne PAS relancer
        if self._current != RecType.NONE: # un autre type est actif
            return                         # ignorer (un seul à la fois)
        self._current = t; self._elapsed = 0
        # ... démarrer la capture audio ...
        self._timer.start(); self.started.emit(t); self.showRequested.emit()

    @Slot()
    def stop(self):
        if self._current == RecType.NONE: return
        self._timer.stop()
        # ... arrêter la capture ; la ligne « En cours » bascule vers son état final ...
        t, self._current = self._current, RecType.NONE
        self.stopped.emit(t)

    def _on_tick(self):
        self._elapsed += 1; self.tick.emit(self._elapsed)
```
**Logique `start(t)` (identique aux maquettes) :** déjà encodée ci-dessus — re-clic du type actif = ré-affichage sans relance ; autre type actif = ignoré ; sinon démarrage.

**Effets à câbler sur ces signaux :**
- **StartButtonGroup** : bouton du type actif en mode enregistrement (point pulsant + chrono) ; autres grisés/non cliquables ; retour normal à `stopped`.
- **Icône d'état** (toolbar + tray) : couleur = état (Étape 8).
- **Navigation libre** : pendant l'enregistrement, l'utilisateur peut ouvrir Historique/Préférences ; le timer continue ; re-cliquer le bouton actif ré-affiche `RecordingView`.
- **Un seul enregistrement à la fois** (garanti par la logique `start`).

**`RecordingView` (empilé, gap 24, centré) :**
1. Pastille « ENREGISTREMENT » : point rouge **pulsant** (`QPropertyAnimation` opacité 1→.35 + scale, 1.4 s boucle) + label mono 11 `letter-spacing` `Rec`.
2. Titre 20/700 selon type (« Réunion/Dictée/Journal en cours ») + **chrono mono 42/500** (mise à jour sur `tick`).
3. **Waveform** : ~44 barres 4 px `Accent`, animation `scaleY` (0.12→1, 0.9 s, alterné, délais échelonnés) — remplacer par le vrai niveau audio si disponible.
4. Encart transcription live (fond `SurfaceSunken`, bordure `Border`, radius 10) : label mono « TRANSCRIPTION EN DIRECT » + texte avec curseur.
5. **Bouton Arrêter uniquement** (`#danger`, icône `stop`). **Aucun bouton Pause.**

3. **Point pulsant** : petit `QWidget` avec `QGraphicsOpacityEffect` + `QPropertyAnimation` sur `opacity` (1→.35, 1400 ms, `setLoopCount(-1)`, `QEasingCurve.InOutSine`). Griser un bouton = `QGraphicsOpacityEffect` à 0.55 + `setEnabled(False)`.

**Critères d'acceptation :** démarrer Réunion → bouton en mode enreg + icônes rouges + autres grisés ; naviguer vers Historique → chrono continue ; re-clic Réunion → ré-affiche sans relancer ; Arrêter → retour Historique, ligne passe à l'état final.

---

## Étape 8 — Icône & menu du tray
**Objectif :** présence tray avec icône colorée par état et comportements de clic.

**Fichiers :** `src/core/TrayController.*`.

**À faire :**
1. `QSystemTrayIcon` + `QMenu`.
2. **Icône = état d'activité** (via `wavemark_icon`, Étape 3a) :
   - Repos → contour `C.TRAY_IDLE`. **macOS** : variante **template** (`QIcon.setIsMask(True)` ou l'asset `tray-template.svg`) pour l'auto-inversion clair/sombre. **Windows/Linux** : version colorée.
   - Enregistrement `C.TRAY_RECORDING` (rempli) · Transcription `C.TRAY_TRANSCRIBE` · Terminé `C.TRAY_DONE` (~1,5 s via `QTimer.singleShot` puis retour repos) · Erreur `C.TRAY_ERROR` (bref puis repos).
   - **Cycles** : Dictée/Journal → Repos → 🔴 → 🟠 → 🟢 → Repos ; Réunion → 🔴 continu, 🟢 bref à l'arrêt. Câbler sur `RecordingController` + l'étape de transcription.
3. **Comportements de clic** :
   - **Clic gauche** (`QSystemTrayIcon.ActivationReason.Trigger`) → afficher / premier plan : `w.showNormal(); w.raise(); w.activateWindow()`.
   - **Clic droit** (`Context`) → afficher le `QMenu`.
   *(sur macOS, `QSystemTrayIcon` ouvre le menu sur clic gauche par défaut ; implémenter le comportement gauche=ouvrir / droit=menu en gérant `activated(reason)` et en n'attachant pas le menu par défaut, ou via un menu contextuel séparé.)*
4. **Menu** (ordre exact) : Démarrer Dictée `⌃⌥⌘D` · Démarrer Réunion `⌃⌥⌘R` · Démarrer Journal `⌃⌥⌘J` — sép — **Ouvrir debriefMeet** (mis en avant) · Historique… · Préférences… — sép — Quitter. Les libellés de raccourci sont **natifs par OS** (Étape 9).

**Critères d'acceptation :** l'icône change de couleur selon l'état ; clic gauche ouvre la fenêtre ; clic droit ouvre le menu ; sur macOS l'icône repos s'inverse en barre sombre.

---

## Étape 9 — Raccourcis globaux
**Objectif :** démarrer/arrêter chaque capture même sans focus, avec libellés par OS.

**À faire :**
1. Raccourcis globaux système : Dictée `Ctrl+Alt+Cmd+D`, Réunion `…+R`, Journal `…+J` (mapper `Cmd`→`Meta` sur macOS). **PySide6 n'a pas de hotkey global natif** : utiliser le mécanisme déjà présent dans le projet s'il existe, sinon une lib (`pynput`, `pyqthotkey`, ou API par OS). **Demander validation avant d'ajouter une dépendance.** Sur macOS, un hotkey global nécessite l'autorisation Accessibilité — le documenter.
2. **Affichage des libellés** : `⌃⌥⌘…` sur macOS, `Ctrl+Alt+…` sur Windows/Linux — ne jamais coder en dur les glyphes mac ailleurs. Centraliser une fonction `shortcutLabel()` par OS.
3. Un raccourci **démarre/arrête** l'action correspondante (toggle). Champ vide en préférences = désactivé.

**Critères d'acceptation :** presser le raccourci hors focus démarre la capture ; les libellés affichés correspondent à l'OS courant.

---

## Étape 10 — Packaging cross-platform & finitions
**Objectif :** rendu et intégration identiques sur les 3 OS.

**À faire :**
1. **Icônes d'app** : `.icns` (bundle macOS), `.ico` (exe Windows), PNG (Linux `.desktop` / `setWindowIcon`). Fichiers fournis dans `icons/`. Packaging Python : PyInstaller (`--icon debriefMeet.icns`/`.ico`), briefcase ou l'outil déjà utilisé par le projet.
2. **Polices embarquées** (Étape 1) — ne pas dépendre des polices système.
3. **Titlebar** : titre discret centré ; laisser les contrôles natifs (feux macOS à gauche / boutons Windows-Linux à droite).
4. **Cibles tactiles** ≥ 44 px là où cliquable ; hauteurs de ligne 52 conservées.
5. **Vérification finale** vue par vue contre `Guide-Design.dc.html` et `debriefMeet-C.dc.html` (couleurs, tailles, espacements, états).

**Critères d'acceptation :** build OK sur les 3 OS ; icônes correctes ; aucune police manquante ; parité visuelle avec les maquettes.

---

## Règles transverses (rappel)
- **Aucune valeur de style en dur** hors `theme.py` / `theme.qss`.
- **Mono obligatoire** pour dates, durées, chronos, chemins, noms de fichiers, raccourcis, versions.
- **Rouge `#FF3B30`** = activité d'enregistrement uniquement ; **`#B42318`** = destructif uniquement.
- Badges d'état et barre d'accent de ligne : **délégués**, pas QSS.
- Commit + court récap à chaque étape ; ne pas sauter d'étape.

## Ordre d'exécution résumé
0 Découverte → **2 Thème (palette + QSS)** *(après 1 Assets)* → 1 Assets → 3 Composants → 4 Shell → 5 Historique → 6 Préférences → 7 Enregistrement+état → 8 Tray → 9 Raccourcis → 10 Packaging.

> Note : faire **1 (assets)** puis **2 (thème)** en tout premier — le thème dépend des polices. Ensuite tout le reste consomme le thème.
