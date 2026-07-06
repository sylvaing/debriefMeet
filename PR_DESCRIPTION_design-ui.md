# Refonte visuelle complète — design-ui → portageWindows

## Résumé

Implémente `design_handoff_debriefmeet/IMPLEMENTATION_SPEC.md` (maquettes HTML,
palette indigo, IBM Plex Sans/Mono, icônes Phosphor) étape par étape (Étapes
0→9 sur 10, un commit par étape). L'app passe d'un tray-only avec dialogues
indépendants (Historique, Préférences) à une fenêtre unique (`FenetrePrincipale`)
avec toolbar, navigation par onglets et vue d'enregistrement dédiée.

176 fichiers modifiés, +8310/-2067 lignes. Suite de tests : 589 → ~760 tests
(dont plusieurs dizaines nouveaux pour les composants et vues créés).

## Ce qui change pour l'utilisateur

- Une seule fenêtre (`Cmd+clic tray` ou menu) au lieu de deux dialogues séparés,
  avec toolbar (marque, onglets Historique/Préférences, boutons Dictée/Réunion/
  Journal, icône d'état) au-dessus du contenu.
- Historique en table dense (au lieu d'une liste) avec recherche, badges
  d'état colorés, actions par ligne.
- Préférences en sous-nav verticale avec **auto-save** (suppression du bouton
  Appliquer/Annuler — chaque champ persiste immédiatement).
- Démarrer un enregistrement affiche une vue dédiée (pastille, chrono,
  waveform décorative, bouton Arrêter) sans perdre l'onglet actif ; re-cliquer
  le bouton du mode déjà actif ré-affiche cette vue sans relancer
  l'enregistrement (raccourci clavier = toggle réel, inchangé).
- Menu du tray réordonné (« Ouvrir debriefMeet » en action par défaut) ; clic
  gauche ouvre la fenêtre, clic droit ouvre le menu (au lieu du menu sur les
  deux, limite Qt/macOS contournée).

## Architecture

- Nouveaux modules `ui/` : `theme.py`, `polices.py`, `wavemark.py`,
  `status_pill.py`, `segmented.py`, `start_group.py`, `pulsing_dot.py`,
  `capture_model.py`, `actions_delegate.py`, `history_view.py`,
  `preferences_view.py`, `recording_view.py`, `recording_controller.py`,
  `waveform_widget.py`, `etat_icone.py`, `fenetre_principale.py`.
- Supprimés (remplacés, plus aucun consommateur) : `ui/historique.py`,
  `ui/preferences.py`, glyphes Tabler dans `ui/icones.py`, police
  `tabler-icons.ttf`.
- **Décision** : réutilise l'enum `Mode`/`MachineEtats` existants plutôt que
  le `RecType`/`RecordingController`-état parallèle suggéré par la spec —
  évite deux machines à états qui divergent. `RecordingController` (nouveau)
  est une fine couche de câblage UI (StartButtonGroup ↔ MachineEtats), pas
  une state machine.
- Icônes Phosphor : Qt (`QSvgRenderer`) ne résout pas `fill="currentColor"`
  (rendu noir) → substitution texte du SVG avant rendu
  (`icones.icone_svg_teintee`).
- Deux vrais bugs trouvés et corrigés en testant l'autosave/les raccourcis :
  détection de doublon de raccourci cassée par le réordonnancement des
  modificateurs de `QKeySequence.toString()`, et les défauts du bouton
  « Réinitialiser » qui auraient réintroduit la touche Windows (Meta) dans un
  raccourci sur Windows.
- Un crash natif (segfault) diagnostiqué et corrigé : un `QTimer` répétitif
  sur un `QObject` sans parent (`MachineEtats`) pouvait tirer sur un objet
  garbage-collecté plus tard dans une suite de tests partageant la même
  `QApplication`. Le ticking a été déplacé côté UI (`RecordingController`/
  `RecordingView`), chacun avec un timer borné à son propre cycle de vie.

## Ce qui n'est PAS fait (Étape 10, bloqué)

- **Cibles tactiles ≥44px** (spec §10.4) : les boutons d'action de
  l'Historique font 30×30px — pas changé sans pouvoir vérifier visuellement
  le rendu résultant.
- **Vérification visuelle finale** face aux maquettes HTML — nécessite de
  lancer l'app avec un affichage, impossible depuis l'environnement où cette
  branche a été développée.
- **Build réel non exécuté** : les icônes de packaging (macOS `.icns`,
  Windows `.ico`) ont été branchées dans les `.spec`/Inno Setup mais aucun
  build macOS signé ni build sur la VM Windows n'a été relancé pour valider.

## Notes indépendantes de cette branche

- Correctif « ouvrir/révéler compatible Windows/Linux » dans `history_view.py`
  (commit `56cb48f`) — `subprocess.Popen(["open", ...])` macOS-only cassait
  sur Windows, trouvé en test interactif réel sur la VM. Inclus ici car porté
  en même temps que la réécriture de cette vue, mais sans lien avec le design.
- **Bug pré-existant découvert, hors scope, PAS corrigé ici** :
  `tests/test_reunion.py` peut geler indéfiniment ou segfaulter
  (`QTimerInfoList::activateTimers`) — reproduit à l'identique sur
  `portageWindows` avant cette branche, donc sans rapport avec la refonte.
  Investigation lancée séparément (tâche dédiée).

## Plan de test

- [x] `make test` : ~760 passed, aucune régression, vérifié stable sur
      plusieurs passages consécutifs (hors `test_reunion.py`, cf. ci-dessus).
- [ ] Lancer l'app (`make run`) et comparer visuellement chaque écran aux
      maquettes (`design_handoff_debriefmeet/debriefMeet-C.dc.html`).
- [ ] Rebuild macOS + re-signature, vérifier `codesign -dv` (même Authority
      qu'avant) et les permissions TCC (Micro, Enregistrement écran).
- [ ] Rebuild Windows sur la VM (`scripts/build_app_windows_vm.sh`), fumée
      installeur (`scripts/fumee_setup_vm.sh`).
