# 38 — Vibrancy native pour le menu du tray (macOS)

> **Statut :** limitation connue et acceptée pour l'instant. Pas de correctif appliqué —
> à traiter plus tard si besoin (décision prise en session, 2026-07-07 : rester sur le
> fond QSS translucide actuel, mais documenter la vraie solution pour y revenir).

## 1. Symptôme observé

Comparaison directe entre le menu du tray de debriefMeet et un menu contextuel macOS
natif (capture d'une autre application, Antidote) au même endroit de l'écran : le menu
natif laisse voir le contenu **flouté** derrière lui (vrai effet de verre dépoli,
« vibrancy ») ; le menu debriefMeet affiche un panneau **plat, semi-opaque**, sans aucun
flou du contenu situé derrière — juste une teinte translucide unie.

Le réglage des couleurs (`docs/CHANGELOG_v2.md` correctif #11, `theme.qss` §Menu du
tray) a corrigé la teinte (moins grise, plus proche du blanc), mais ne peut pas corriger
ce symptôme : ce n'est pas un problème de couleur, c'est une limitation d'API.

## 2. Cause

**Qt Style Sheets (QSS) n'ont pas d'équivalent à `backdrop-filter`.** Le CSS du design
(`debriefMeet-C.dc.html` §Tray, `DESIGN.md` §8.8) spécifie :

```css
background: rgba(247,248,250,.93);
backdrop-filter: blur(40px) saturate(150%);
-webkit-backdrop-filter: blur(40px) saturate(150%);
border: .5px solid rgba(0,0,0,.09);
```

`background` + `border` se traduisent directement en QSS (`theme.qss:98-108`, avec la
bordure arrondie à 1px — QSS n'accepte que des largeurs entières). **`backdrop-filter`
n'a aucun équivalent** : Qt ne peut pas flouter dynamiquement ce qui se trouve
géométriquement derrière une fenêtre. Le rendu actuel (`rgba(247,248,250,.93)` posé sur
un `QMenu`) est donc un compromis — un panneau clair, translucide, mais sans flou —
documenté comme « best-effort » dans le commentaire QSS au-dessus de la règle
`QMenu#trayMenu`.

Vérifié empiriquement (rendu réel via `QWidget.grab()`, cf. session du 2026-07-07) :
les valeurs `rgba(...)` s'appliquent bien pixel pour pixel (fond + alpha corrects), la
transparence fonctionne — c'est bien l'absence de flou qui crée l'écart visuel avec un
vrai menu système.

## 3. Solution correcte (non implémentée)

Le vrai effet de vibrancy macOS repose sur `NSVisualEffectView` (AppKit), qui applique
un flou GPU en temps réel au contenu de l'écran situé sous la vue. Pour l'obtenir
derrière une `QMenu` Qt, il faut :

1. Récupérer le handle natif de la fenêtre du menu (`QMenu.winId()` → `NSView*`/`NSWindow*`
   sous macOS).
2. Insérer un `NSVisualEffectView` (matériau `.popover` ou `.menu`, `state: .active`)
   comme vue de fond de cette fenêtre, sous le contenu peint par Qt.
3. Rendre le `QMenu` lui-même transparent (`Qt.WA_TranslucentBackground` + fond QSS
   `transparent`) pour laisser transparaître la vue native en dessous.

Cette manipulation nécessite du code Objective-C/Cocoa, via **PyObjC**
(`pyobjc-framework-Cocoa`), qui **n'est pas une dépendance actuelle du projet**.

## 4. Pourquoi ce n'est pas un simple ajout QSS

Conforme à la règle d'or de `CLAUDE.md` (« la couche `core/` n'importe jamais de module
OS-spécifique (mlx, AppKit, ctypes…). Toute dépendance plateforme passe par les
interfaces de `platform/interfaces.py` »), cette solution ne peut pas être posée
directement dans `src/debrief_meet/ui/tray.py` (code partagé cross-platform) :

- Nouvelle dépendance **macOS uniquement** (`pyobjc-framework-Cocoa`) — à ajouter dans
  le groupe `[project.optional-dependencies] macos` de `pyproject.toml`, jamais dans les
  dépendances de base (Windows/Linux n'ont pas de vibrancy à reproduire : sur ces OS, le
  fond QSS translucide actuel reste la bonne solution, ou un fond opaque simple).
- Nouvelle interface dans `platform/interfaces.py` (ex. `EffetVibrancyMenu` avec une
  méthode `appliquer(menu: QMenu) -> None`), implémentée dans `platform/macos/` (no-op
  ailleurs), suivant le même schéma que les adaptateurs existants (raccourcis Carbon,
  capture SCK).
- `tray.py` appellerait l'interface au lieu de connaître AppKit.

## 5. Effort estimé et risques

- Code natif difficile à tester hors d'une vraie session interactive macOS (comme pour
  `docs/37`, `QWidget.grab()` en environnement headless ne reflète pas fidèlement le
  rendu réel avec fenêtre système — la vibrancy en particulier n'existe que via le vrai
  compositeur de fenêtres, invisible en test automatisé).
- Risque de régression sur le cycle de vie de la `QMenu` (fermeture, changement de light/dark
  mode système — `NSVisualEffectView` doit suivre `NSAppearance` dynamiquement).
- Aucun équivalent Windows/Linux : resterait une divergence cross-platform assumée
  (cf. `DESIGN.md` §10 "concessions aux conventions système" — le menu tray est déjà une
  exception documentée à la règle "look identique sur les 3 OS").

## 6. Décision actuelle

Rester sur le fond QSS `rgba(247,248,250,.93)` (translucide, sans flou) tant que le
besoin n'est pas jugé prioritaire. Revenir sur ce document si l'écart visuel devient
gênant en usage réel ou si une session dédiée au polish macOS est planifiée.

## 7. Localisation

- `src/debrief_meet/ui/assets/theme.qss` — règles `QMenu#trayMenu` (commentaire au-dessus
  documentant déjà l'absence de `backdrop-filter`).
- `src/debrief_meet/ui/tray.py` — construction du `QMenu` (`_construire_menu`).
- `design_handoff_debriefmeet/DESIGN.md` §8.8, `debriefMeet-C.dc.html` (section TRAY) —
  spec visuelle de référence.
