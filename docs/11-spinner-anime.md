# Plan d'action — Spinner animé pour les jobs en arrière-plan

> **Statut :** ✅ **implémenté & testé** — 376 tests verts (+9), stable. Validation manuelle (voir le spinner tourner pendant un job) restant à jouer par l'utilisateur.
> **Besoin :** quand une tâche de fond tourne (transcription différée OU diarization), le bouton
> d'action « en cours » doit afficher un spinner **animé** (qui tourne), au lieu de l'icône
> figée actuelle. Remplace l'idée de barre de progression (écartée — jobs sans % fiable).

---

## 1. Décisions actées

- **Élément animé :** le **bouton d'action n°2** en mode « en cours » (Transcrire / Générer locuteurs), dans `historique.py`. Pas l'indicateur près du nom.
- **Technique :** rotation programmatique du glyphe existant `attente` (ti-loader-2) — **pas de GIF** (reste monochrome et adaptatif clair/sombre, aucun asset à ajouter).
- **Intégration :** approche (a) — on **garde le `QToolButton` WIP désactivé** existant et on **anime son icône** ; le layout et la suite de tests (`_boutons()` voit toujours un QToolButton au même index) restent intacts.
- **Portée :** couvre les **deux** types de jobs (même gestionnaire).

---

## 2. Conception

### 2.1 Rendu du glyphe pivoté (`ui/icones.py`)
- Ajouter un paramètre d'angle au rendu du glyphe (ex. `pixmap_glyphe(nom, taille, alpha, angle=0)` ou une variante dédiée) : applique une `QTransform().rotate(angle)` autour du centre avant de peindre le glyphe. Renvoie un `QPixmap` (→ `QIcon`).

### 2.2 Animation du bouton (`ui/historique.py`)
- Un helper `_bouton_attente_anime(tooltip)` : crée le `QToolButton` désactivé (comme aujourd'hui) **+** installe un `QTimer` **enfant du bouton** (~80 ms, angle += 30° → look loader classique, 12 positions/tour). À chaque tick : `bouton.setIcon(icone "attente" pivotée de angle)`.
- Le timer étant enfant du bouton, il est **détruit avec lui** → l'animation s'arrête seule quand la ligne est reconstruite (fin de job) ou la fenêtre fermée. Aucun timer orphelin.
- Remplace les deux usages actuels de `self._bouton(_ICONE_WIP, …)` (dans `_bouton_transcrire` et `_bouton_diarization`) par ce helper.

### 2.3 Cycle de vie
- Inchangé : la ligne (et donc le bouton animé) est créée sur `demarre`, retirée sur `termine`/`echoue` (signaux + rechargement déjà en place). Pendant le job, la ligne reste stable → l'animation tourne sans interruption.

---

## 3. Tests prévus
- `icones.py` : le rendu pivoté produit un `QPixmap` non nul pour angle 0 et 90 (et tailles attendues).
- `historique.py` : le bouton « en cours » est bien désactivé, porte un `QTimer` actif (animation installée), tooltip « …en cours… » ; pour les deux types de jobs.
- Non-régression : `_boutons()` voit toujours le même nombre de `QToolButton` au même index (le WIP reste un QToolButton).

---

## 4. Hors périmètre
- Pas de barre de progression (écartée).
- Pas d'animation de l'indicateur près du nom (seulement le bouton d'action).
- Pas de progression chiffrée (les jobs restent des « boîtes noires »).
