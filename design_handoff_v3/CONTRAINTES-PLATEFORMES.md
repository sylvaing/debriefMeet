# Contraintes techniques et divergences par système

> Annexe du `README.md`. Deux parties : ce que Qt/QSS permet réellement (§1–2), puis les
> endroits où l'interface **diverge d'un OS à l'autre**, avec la raison de chaque divergence
> (§3). Chaque point marqué 🩹 est le résultat d'un bug constaté chez un utilisateur réel —
> ne pas le défaire sans lire `NE-PAS-REGRESSER.md`.

---

## 1. Ce que Qt Widgets sait et ne sait pas faire

L'interface est en **Qt Widgets** (pas QML) : une feuille de style globale
(`ui/assets/theme.qss`, 143 lignes), **~70 appels à `setStyleSheet`** posés en Python sur des widgets
précis (dont plusieurs rejoués au survol, faute de `:hover` fiable), et une douzaine de **délégués** qui peignent les cellules et les items de
menu au pinceau (`QPainter`).

### Ce qui marche en QSS

Fond, bordure (largeur entière), rayon, padding, police, couleur, `:hover` / `:checked` /
`:focus` / `:disabled` sur un widget, sous-contrôles standard (`::drop-down`, `::up-button`,
`::indicator`, `::section`, `::item`), images de fond et icônes par `url(...)`.

### Ce qui ne marche pas — et son coût

| Envie de design | Réalité Qt | Coût actuel |
|---|---|---|
| `backdrop-filter: blur()` | aucun équivalent | le menu du tray se contente d'un fond translucide `rgba(247,248,250,.93)`, sans flou réel |
| Bordure `0.5px` | QSS n'accepte que des entiers | arrondie à 1 px |
| `box-shadow` | pas en QSS | `QGraphicsDropShadowEffect` sur le widget (utilisé pour la carte de dialogue) — coûteux, réservé à quelques éléments |
| Styler **un** item de menu (couleur permanente, survol qui recolore icône + texte) | `QMenu::item` ne cible pas un item précis | **tous** nos menus riches (⋯, tray) sont des `QWidgetAction` avec widget maison et `enterEvent`/`leaveEvent` écrits à la main |
| `transition` / `animation` CSS | inexistant | `QPropertyAnimation` (le point rouge pulsant : opacité 1 → 0,35, 700 ms aller-retour, sinus) |
| `currentColor` dans un SVG | `QSvgRenderer` ne le résout pas (rendu noir) | la couleur est **substituée dans le texte du SVG** avant rendu, à chaque teinte et chaque taille |
| Survol sur un widget composite | le pseudo-état `:hover` d'un widget à enfants ne se réévalue pas de façon fiable | fond et couleurs pilotés en Python |
| Poser une feuille de style sur un conteneur pour styler ses enfants | casse la résolution des pseudo-états des enfants sous le style natif macOS 🩹 | tout passe par des sélecteurs nominatifs (`#toolbar`, `#navTab`…) |

### Rendu et densité

- Les icônes sont rendues à `devicePixelRatio` explicite — nets en Retina, à condition de
  passer par les fabriques existantes.
- Les tableaux ont une **hauteur de ligne fixe** (52 px) : le design ne peut pas supposer une
  ligne qui grandit avec son contenu sans revoir tous les délégués.
- Il n'existe **aucun thème sombre** : le QSS global et tous les styles locaux sont écrits en couleurs
  claires en dur.

---

## 2. Ce qui est identique partout

Look, palette, typographie embarquée, iconographie, géométrie : **tout est calculé en Python
ou imposé en QSS**, donc identique au pixel sur les trois OS. Les seules divergences sont
celles listées ci-dessous — elles sont toutes **subies**, jamais décoratives.

---

## 3. Divergences par système

### 3.1 Tableau récapitulatif

| Sujet | macOS | Windows | Linux (GNOME / Wayland) |
|---|---|---|---|
| Décoration de fenêtre | feux tricolores à gauche, ombre système | boutons à droite, ombre système | **aucune ombre** → liseré 1 px maison 🩹 |
| Ouverture du menu du tray | popup manuel au **clic droit** ; clic gauche = ouvrir la fenêtre | idem macOS | **menu attaché obligatoire** ; le clic gauche ouvre le menu 🩹 |
| Rendu du menu du tray | dessiné par Qt, stylé en QSS | dessiné par Qt, stylé en QSS | **exporté en DBusMenu**, redessiné par l'hôte : ni QSS, ni widget maison 🩹 |
| Police du menu du tray | `.AppleSystemUIFont` (SF Pro) | Segoe UI | police du thème système |
| Item « Quitter » rouge | widget maison rouge permanent | idem | **impossible** : `QAction` simple, couleur de l'hôte 🩹 |
| Icône de tray au repos | contour `#3D4351`, *template* (macOS la reteinte) | contour `#3D4351` | **contour blanc** — le bandeau GNOME est noir même en thème clair 🩹 |
| Style de widgets | style natif macOS | style natif Windows | **Fusion** (rectangles de focus visibles, ascenseurs épais) |
| Raccourcis globaux | ⌃⌥⌘ D/R/J (Carbon) | Ctrl+Alt+D/R/J (pas de touche Windows) | **aucun** (Wayland) — tout passe par le tray |
| Ouvrir un fichier | `open` | `os.startfile` 🩹 | `xdg-open` |
| Révéler dans le dossier | `open -R` | `explorer /select,` | `xdg-open` du dossier parent |
| Copier un fichier | `osascript` → POSIX file | `QMimeData` URLs → CF_HDROP | `QMimeData` URLs → `text/uri-list` |
| Copier en HTML | `QMimeData` (pas `pbcopy`) | `QMimeData` → CF_HTML | `QMimeData` → `text/html` |
| Mode local (Whisper) | oui (MLX) | oui (faster-whisper CPU) | **non** — mode distant seul en v1 |
| Sélecteur de micro | liste simple | **suffixe d'API** (« — WASAPI », « — MME ») : le même casque apparaît 3 fois 🩹 | liste simple |

### 3.2 macOS

- **Ne jamais appeler `setContextMenu()`** : un menu attaché s'ouvre au clic **gauche comme
  droit**, ce qui rend impossible « clic gauche = ouvrir la fenêtre ». Le menu est affiché
  manuellement sur le clic droit.
- L'icône de tray au repos est un **template** (`setIsMask`) : macOS la reteint selon sa barre
  de menus, correcte en clair comme en sombre. C'est la seule raison pour laquelle l'état repos
  est un **contour** et non un aplat.
- Le menu du tray est le seul endroit où l'app abandonne IBM Plex pour la police système — il
  doit se fondre dans les menus de la barre, pas afficher notre identité.
- Qt masque par défaut les raccourcis dans un menu affiché en *popup* : il faut les forcer.
- L'icône d'application (`.icns`) suit les règles du Dock (carré arrondi, marge ~20 %) et n'est
  **pas** le WaveMark de la marque.
- Permissions TCC (micro, enregistrement de l'écran) : un refus ne casse pas l'UI mais produit
  une réunion muette — d'où la notification « Aucun son capté ».

### 3.3 Windows

- `open` n'existe pas : trois plantages `[WinError 2]` ont été trouvés en test réel sur la VM.
  Tout accès au système de fichiers passe par une branche par OS. 🩹
- Les défauts de raccourcis évitent **Meta** (touche Windows), réservée par l'OS pour beaucoup
  de combinaisons ; le champ de saisie refuse aussi de la réintroduire.
- Le démarrage d'une capture peut prendre plusieurs secondes à froid : le bouton affiche un
  état transitoire « Démarrage… » et force un repaint, sinon il reste figé.
- Un même micro est listé plusieurs fois (MME / DirectSound / WASAPI) : le libellé porte le nom
  de l'API, et l'entrée « par défaut » dit quel périphérique elle résout réellement. 🩹
- Le rendu Windows est proche de macOS ; c'est surtout le **chrome de fenêtre** et la barre des
  tâches qui diffèrent. Windows 11 en thème sombre affiche une barre de titre sombre au-dessus
  d'un contenu clair — aujourd'hui non traité.

### 3.4 Linux — Ubuntu 26.04, GNOME, Wayland

C'est le système le plus contraignant, et le plus récemment supporté (v1 : **mode distant
seul**, `.deb` amd64).

- **`setContextMenu()` est obligatoire.** Le tray passe par StatusNotifierItem ; l'hôte
  (GNOME + extension AppIndicator) **n'appelle jamais `Activate`** — sans menu attaché, ni le
  clic gauche ni le clic droit ne produisent quoi que ce soit. Le premier utilisateur Linux
  n'avait accès à aucune action. 🩹
  Conséquence assumée : **le clic gauche ouvre le menu** au lieu de la fenêtre ; « Ouvrir
  debriefMeet » est l'action par défaut du menu, en tête et en gras.
- **DBusMenu ne transporte que libellé / icône / état.** Aucun `QWidgetAction` n'y a de
  représentation : l'item « Quitter » rouge maison s'y affichait par son seul texte, et
  l'activation passait par un signal auquel rien n'était branché — item inerte, et **aucune
  autre porte de sortie de l'application**. 🩹 Conclusion pour le design : **tout menu de tray
  riche est macOS/Windows uniquement**, Linux reçoit la version système.
- **Le bandeau GNOME est noir même en thème clair.** L'icône de repos y est blanche — et ce
  choix **ne doit pas** être dérivé du thème clair/sombre de l'application, qui ne dit rien de
  la couleur du bandeau. 🩹
- **Wayland ne dessine pas d'ombre portée** autour de la fenêtre (le plugin de décoration Qt
  `adwaita` n'en trace aucune, contrairement aux applications GTK) : une fenêtre blanche
  devient indiscernable d'un fond blanc. On trace donc un **liseré 1 px `#B0B7C0`** autour de
  la zone client, avec 1 px de marge (à marge nulle, les enfants peignent par-dessus et seul le
  bord haut survit). 🩹 **Limite acceptée : le bandeau de titre reste sans contour** — il est
  peint par `libadwaita`, hors de portée de toute feuille de style ou `paintEvent` de l'app.
- **Style Fusion** : les rectangles de focus sont visibles (nav des Préférences, cellule
  courante d'un tableau), les ascenseurs sont natifs et épais, et certains fonds gris
  apparaissent là où macOS ne montrait rien — par exemple le viewport d'une zone défilante, qui
  doit être neutralisé par une feuille de style posée **sur le viewport seul** (sur le
  `QScrollArea`, elle bascule aussi l'ascenseur sur un rendu fantôme ; une palette, elle, est
  écrasée par le `QWidget {…}` global). 🩹
- **Pas de raccourcis globaux** : `XGrabKey` ne fonctionne pas sous Wayland, la voie propre est
  le portail XDG `GlobalShortcuts` (hors v1). En mode distant, seul le toggle Réunion perd son
  raccourci — le tray le couvre.
- **Pas de moteur local** : Dictée et Journal n'existent donc jamais sur Linux aujourd'hui.
  L'interface Linux, c'est **un onglet Réunion + l'engrenage**.
- Dépendances du paquet : `ffmpeg`, `libportaudio2`, `libgtk-3-0t64`, `adwaita-icon-theme`.
  Un tray fonctionnel suppose l'extension AppIndicator côté GNOME.

### 3.5 Règles transverses à conserver

1. **Jamais de glyphe macOS codé en dur** (⌃⌥⌘) hors macOS : les libellés de raccourcis
   passent par la conversion native de Qt (`NativeText`), qui rend « Ctrl+T » ou « ⌘T » selon
   l'OS à partir d'une seule séquence portable.
2. **Toute branche par OS se décide sur `sys.platform`**, jamais sur un `ImportError` ni sur le
   thème clair/sombre de l'application.
3. **Les polices sont embarquées** — ne jamais dépendre d'une police système, sauf pour le menu
   du tray, où c'est justement l'effet recherché.
4. Les chemins, dossiers et emplacements de logs **ne sont jamais écrits en dur** dans un
   libellé : ils diffèrent par OS et ont déjà été affichés faux.
