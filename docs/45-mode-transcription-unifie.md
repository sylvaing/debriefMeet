# Mode de transcription unifié — un seul build, un réglage dans les Préférences

**Statut : 🔄 code + tests terminés (2026-08-04) — reste : build VM + fumée du setup
unifié, validation manuelle de la relance sur les 3 environnements (dev macOS, .app
figée, .exe Windows), et une transition réelle depuis un poste lite (Alix).**

Remplace les deux éditions compilées de docs/44 (`complete`/`lite`) par **un seul
build** et un réglage utilisateur `mode_transcription` :

- **`distant`** (défaut) : enregistrement Opus seul, transcription + CR délégués à
  l'API Mistral — l'ancien comportement lite ;
- **`local`** : moteur Whisper embarqué (live, différé), diarization, modes
  Dictée/Journal — l'ancien comportement complete.

Le CR était déjà Mistral dans les deux éditions : le mode ne pilote que la **source
de la transcription** et ce qui en dépend.

## 1. Décisions

| # | Décision | Pourquoi |
|---|----------|----------|
| D1 | Défaut `distant` **pour tous**, pas d'heuristique de migration | Simple et prévisible ; le bénéfice clé du lite (aucun modèle ~1,5 Go téléchargé au 1ᵉʳ lancement) est conservé par construction |
| D2 | Écran de bienvenue (`accueil_fait`) joué aussi sur les installations existantes | C'est ce qui rend D1 acceptable : la clé est absente des config.json antérieurs, donc un poste en édition complète voit l'écran une fois après la MAJ et choisit « local » en un clic — personne ne perd la transcription locale sans un choix explicite |
| D3 | Mode **figé pour la durée du process** ; changer = dialogue « Redémarrer maintenant / Plus tard » | Le moteur (factory), le tray, la fenêtre, les raccourcis sont construits au démarrage — un rechargement à chaud multiplierait les risques (QThread, registre OS) pour un réglage qu'on change une fois |
| D4 | Les **9 sections** de Préférences existent dans les deux modes | Découvrabilité : « Sur cet ordinateur » doit rester visible depuis le mode distant ; seul le contenu de « Transcription » varie |
| D5 | Override env `DEBRIEFMEET_MODE` **bidirectionnel** (dev seulement) | L'ancienne monotonie de `DEBRIEFMEET_EDITION` protégeait un bundle physiquement privé de faster-whisper ; le bundle unifié contient toute la pile, le danger MoteurStub a disparu |

## 2. Architecture

### `core/mode_transcription.py`

Reprend les **trois prédicats aux mêmes noms** qu'`edition.py`
(`avec_transcription_locale`, `avec_diarization`, `avec_dictee_journal`) — les 17
sites de gating n'ont changé que d'import. Différence de fond : l'état est un
**module global posé une fois** par `initialiser(config)` (env > config > distant),
appelé dans `__main__` juste après l'écran de bienvenue et **avant**
`configurer_logs` (le mode est loggé en 1ʳᵉ ligne) et toute construction gatée.
Non initialisé → `distant` : le pire cas est une fonctionnalité masquée, jamais un
moteur fantôme.

Invariants conservés tels quels :

- `core/reunion.py::_demarrer` reste le **SEUL site** à neutraliser
  `transcription_live` (la clé garde sa valeur pour un retour en local) ;
- la **garde IPC** de `__main__` (`--toggle`/`--toggle-journal` ignorés hors mode
  local) reste : un raccourci bureau créé en mode local survit à la bascule ;
- `core/raccourcis.actions()` reste le point d'étranglement unique (enregistrement
  OS + éditeurs de Préférences) ;
- `platform/factory.py` gate toujours sur le mode, **jamais** sur `ImportError`
  (`moteur_faster_whisper` n'importe faster_whisper qu'en sous-processus).

### Préférences (`ui/preferences_view.py`)

Nouvel ordre, du plus structurant au plus technique : **Général, Transcription,
IA en ligne (ex-« Remote IA »), Audio, BlueMind, Prompts, Dossiers, Raccourcis,
Journalisation**. La section Transcription porte les 2 radios + le sous-bloc local
(ex-« Modèle » + `transcription_live` + `retention_audio` + diarization, retirés
d'Audio), montré/caché à chaud selon le **radio** (= la config), pas le mode figé.
Garde-fou : avertissement visible si mode distant et clé Mistral vide, recalculé à
chaque navigation. Audio ne contient plus que le matériel (micro, intervalle, AEC).

### Relance (`core/redemarrage.py`)

`demander()` pose un drapeau ; `__main__` appelle `relancer()` **après** le retour
d'`app.exec()`. Deux courses interdisent tout spawn anticipé : le **mutex Win32**
(`instance_unique.py`, libéré à la mort du process) et le **QLocalServer IPC** (un
fils trop tôt se verrait « déjà en cours »). D'où : relanceur détaché avec délai
(`/bin/sh -c 'sleep 1; exec …'` + `start_new_session` ; Windows `ping -n 3 … &
start` détaché), pas d'`os.execv` (fd/mutex hérités). Échec de spawn = log ERROR,
jamais bloquant. Frozen : `sys.executable` seul ; dev : `python -m debrief_meet`.

### Premier lancement (`ui/premier_lancement.py`)

CarteFlottante : 2 radios (distant recommandé / local), champ clé Mistral optionnel
+ « Obtenir une clé… » (réutilise `AssistantMistral`, qui teste et persiste
lui-même). Fermer sans choisir = distant + `accueil_fait=True`.

## 3. Packaging — chaîne d'éditions retirée

- `generer_version.py` : plus d'`--edition` ; `_version.py` et `version.iss` sont
  réécrits intégralement (purge des reliquats lite sur la VM) ;
- `debriefMeet.spec` : plus d'`EXCLUDES_LITE` ni de lecture d'édition ; pile locale
  (`faster_whisper`, `ctranslate2`, `huggingface_hub`, `tokenizers`) et
  `_fw_worker` inconditionnels ;
- `debriefMeet.iss` : nom/fichier inlinés (`debriefMeet` / `debriefMeet-setup`).
  **AppId, AppMutex, `[UninstallDelete]` inchangés** ; `[InstallDelete]` conservé
  intégralement, y compris « debriefMeet Lite.lnk » — c'est lui qui rend propre la
  MAJ d'un poste lite existant (même AppId ⇒ traitée comme une mise à jour) ;
- `build_app.cmd` sans argument, `build_app_windows_vm.sh` sans `--lite` (les 2
  globs de purge `dist\` restent le temps que les reliquats lite disparaissent des
  VM), `fumee_setup_vm.sh` sans phase B′ (remplacée par « pile locale présente
  dans `_internal` » + « pas de raccourci lite historique ») ;
- `pyproject.toml` : extra `windows-lite` supprimé.

Coût assumé : le setup Windows unique repasse à ~159 Mo (116 pour l'ex-lite). Le
premier lancement reste sans téléchargement de modèle tant que le mode est distant
(`precharger_au_demarrage` gaté sur `moteur is not None`, inchangé).

## 4. Tests

- `tests/conftest.py` : fixtures `mode_local`/`mode_distant`
  (`monkeypatch.setattr(mode_transcription, "_mode", …)`, jamais de reload) +
  **autouse global** épinglant `local` (l'ancien défaut « complete » sous lequel la
  suite a été écrite) sauf pour les tests `mode_distant`. La suite est déterministe
  quel que soit `DEBRIEFMEET_MODE` — la gate « suite en lite » de docs/44 disparaît
  par construction (plus de bundle privé de paquets), le comportement distant est
  couvert par les tests `mode_distant` explicites.
- Nouveaux : `test_mode_transcription.py`, `test_redemarrage.py`,
  `test_premier_lancement.py`, tests d'ordre/visibilité/garde-fou/redémarrage dans
  `test_preferences_view.py`.
- Supprimés : `test_edition.py`, `TestSpecWindowsEditions` (remplacé par
  `TestSpecWindows` : pile locale collectée, zéro résidu d'édition, invariants .iss).

Mesuré le 2026-08-04 : **1228 passed** en clone partiel (2 échecs d'environnement
habituels : helper Swift non compilé, audio canonique du benchmark).

## 5. Reste à faire

1. `scripts/build_app_windows_vm.sh` (gate pytest VM = seule gate restante) puis
   `scripts/fumee_setup_vm.sh` sur le setup unifié ;
2. une fois : installer le setup unifié **par-dessus** l'installation lite réelle
   (poste de Alix) — vérifier l'écran de bienvenue, le mode distant conservé, le
   raccourci « debriefMeet Lite » remplacé ;
3. valider la **relance** à la main sur les 3 environnements (dev macOS, `.app`
   figée, `.exe` VM) — repli acceptable si fragile : bouton « Quitter maintenant » ;
4. macOS de Sylvain : après MAJ, écran de bienvenue → choisir « Sur cet
   ordinateur » (D1/D2).
