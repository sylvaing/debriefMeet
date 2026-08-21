# debriefMeet — contexte pour Claude Code

Application de transcription vocale locale (dictée, réunion, journal).
Stack : Python + PySide6 (Qt 6), moteur Whisper accéléré par OS.

## Architecture en couches

```
UI (PySide6)  →  Cœur métier (Python pur)  →  Adaptateurs (1 implémentation/OS)
```

- `src/debrief_meet/core/` — logique partagée (config, modes, modèles, logs)
- `src/debrief_meet/ui/` — tray, préférences, historique
- `src/debrief_meet/platform/` — interfaces ABC + fabrique + adaptateurs par OS
- `benchmark/` — outil de mesure RTF/WER, indépendant de l'app
- `spike/` — explorations isolées (ne pas modifier `benchmark/` depuis ici)
- `helpers/macos/sck-audio/` — helper Swift pour la capture ScreenCaptureKit
- `packaging/` — spec PyInstaller + scripts de signature macOS

**Règle d'or :** la couche `core/` n'importe jamais de module OS-spécifique (mlx, AppKit, ctypes…). Toute dépendance plateforme passe par les interfaces de `platform/interfaces.py`.

## Stockage des réunions (docs/43)

Depuis docs/43, **1 dossier par réunion** dans `dossier_reunions` (Préférences) :
`AAAA-MM-JJ_HH-MM-SS[_slug-titre]/` contenant `transcription.md` (le handle utilisé
partout dans l'app), `moi.opus`/`systeme.opus` (ou `.wav`), `locuteurs.md`, `CR.md`,
`bluemind.json` — noms **génériques**, fixes. Le dossier est renommé à chaque
changement de titre (édition manuelle ou association BlueMind) via
`core/fichiers.renommer_dossier_reunion`. Supprimer une réunion = `shutil.rmtree`
du dossier — plus aucun artefact ne peut rester orphelin. Le **journal**
(`AAAA-MM-JJ.md`) reste inchangé (à plat, 1 fichier/jour).

**Secondes obligatoires dans le nom de dossier.** La migration des réunions à plat
d'avant docs/43 a tourné une fois sur le seul poste concerné puis son code a été
retiré ; les dossiers qu'elle avait laissés en précision minute ont ensuite été
**normalisés en `HH-MM-00`** (et le compteur de collision `-2` en `-02`), ce qui a
permis de retirer tout le code de compatibilité (docs/43 §7). `_MOTIF_HORODATAGE`
exige donc les secondes : un dossier nommé `AAAA-MM-JJ_HH-MM` seul serait listé
mais sans date ni durée (`date_heure_reunion` → `None`). Un éventuel compteur de
collision en fin de nom (`-2`, `-3`…) est ignoré à la lecture.

**Réunion active exclue du listing** : son `transcription.md` est créé dès le démarrage
de l'enregistrement, et elle est déjà représentée par la ligne « en cours » → sans
exclusion elle s'affiche **deux fois** (bug pré-existant, constaté en test manuel le
2026-07-27). `reunion_view.definir_reunion_active` (câblée sur
`OrchestrateurReunion.reunion_demarree`) pose le chemin actif à la fois sur le watcher
(§9) et sur `CaptureModel.definir_chemin_actif` ; le retour à `Mode.IDLE` le remet à None.

## Mode de transcription (docs/45) — remplace les éditions de docs/44

**Un seul build** ; le comportement est piloté par la clé de config
`mode_transcription` : `distant` (défaut — Opus seul, transcription + CR via l'API
Mistral) ou `local` (Whisper embarqué + diarization + Dictée/Journal). Le mode est
**figé au démarrage** par `core/mode_transcription.initialiser(config)` (appelé dans
`__main__` après l'écran de bienvenue, AVANT `configurer_logs` et toute construction
gatée) ; en changer dans Préférences › Transcription propose un redémarrage
(`core/redemarrage.py` — relance détachée avec délai APRÈS `app.exec()`, jamais
avant : mutex Windows + QLocalServer IPC vivent jusqu'à la mort du process).
**Jamais `mode()` directement dans le code métier, toujours les prédicats
`avec_transcription_locale()` / `avec_diarization()` / `avec_dictee_journal()`**.

1. **Toute garantie s'applique au point d'usage, jamais par un défaut** : un
   `transcription_live: true` hérité d'un passage en local est neutralisé par
   `core/reunion.py::_demarrer` (SEUL site à gater), pas par `_DEFAUTS`. De même la
   garde IPC de `__main__` ignore `--toggle`/`--toggle-journal` en mode distant (un
   raccourci bureau créé en mode local survit à la bascule).
2. **Gater sur le mode, jamais sur `ImportError`.** `moteur_faster_whisper.py`
   n'importe `faster_whisper` nulle part au niveau module (c'est le worker qui le
   fait) : un moteur construit à tort ne mourrait qu'à la première transcription,
   chez l'utilisateur.
3. **Premier lancement** : `accueil_fait` absent/faux ⇒ écran de bienvenue
   (`ui/premier_lancement.py`) — joue aussi une fois sur les installations
   antérieures, c'est ce qui rend le défaut « distant pour tous » acceptable.

En dev : `DEBRIEFMEET_MODE=local|distant make run` (bidirectionnel — le bundle
unifié contient toute la pile). Les tests, eux, sont déterministes quel que soit
l'env : autouse global « local » dans `tests/conftest.py`, fixtures
`mode_local`/`mode_distant`.

## Commandes essentielles

```bash
make setup          # venv .venv (Python dev) + deps + build helper Swift
make test           # pytest sans matériel (~5 s) ← toujours lancer avant livraison
make test-all       # suite complète (intégration incluse)
make build-helpers  # recompiler le helper Swift SCKAudioCapture
make run            # lancer l'app
```

Suite attendue : **889 passed** en environnement dev partiel — sans les extras
`macos` (mlx-whisper, pyannote.audio) ni le helper Swift compilé — après l'interco
BlueMind (docs/40, 2026-07-09). Avec ces extras installés, 14 tests supplémentaires
passent (`test_diarization.py`, `test_moteur_faster_whisper.py`, `test_build.py`).
Avec extras macOS complets **et** `.venv-build`/`packaging/vendor/ffmpeg` construits
(après docs/16, 2026-07-12) : **939 passed** (`pytest -m "not integration"`), 949 en
suite complète — seul `test_audio_canonique_present` échoue sur un clone frais
(fixture WAV du benchmark, non liée au packaging, cf. docs/08 § « Audio de test »).
Après l'interco Mistral (docs/42, 2026-07-21) : +85 tests unitaires (`test_mistral_*.py`,
`test_generateur_cr_mistral.py`, `test_testeur_connexion_mistral.py`,
`test_remote_ia_view.py`, `test_assistant_mistral.py`, + correctifs annexes dans
`test_fichiers.py`/`test_reunion.py`/`test_reunion_view.py`) — **1042 passed** en
environnement extras macOS + pyannote complets, sans `.venv-build`/`packaging/vendor/ffmpeg`
(2 échecs attendus : helper Swift non compilé, audio canonique absent sur ce clone).
Après l'édition lite Windows (docs/44, 2026-07-30) : **1153 passed** en édition
complète *et* en édition lite (`DEBRIEFMEET_EDITION=lite`), avec les 2 échecs
d'environnement habituels sur un clone partiel (helper Swift non compilé, audio
canonique du benchmark). La gate VM lite (lite **+ sans `huggingface_hub`**, commande
exacte de `build_app.cmd [4/6]`) : **951 passed, 11 skipped, 0 échec** — les 11 sautés
sont ceux qui importent `huggingface_hub` dans leur corps (`importorskip`).
Nouveaux : `test_edition.py`, `test_export_diagnostic.py`,
`TestSpecWindowsEditions` (1ᵉʳˢ tests du dépôt sur le spec et le `.iss`), + ~18 tests
lite explicites.

Après la réorganisation 1 dossier/réunion (docs/43, 2026-07-27) : **1099 passed** sur
`main` (0 échec, environnement complet) — tests étendus de `test_fichiers.py` (slug,
nom de dossier, renommage), adaptation du layout dans tous les tests touchant des
réunions (fixtures désormais en sous-dossier), + 6 tests d'exclusion de la réunion
active (ligne en double, cf. § ci-dessous). Le pic à 1113 incluait les 14 tests du
module de migration, retiré depuis (docs/43 §7).

Après la proposition d'association BlueMind avant le CR Mistral (docs/42 §4.1,
2026-08-04) : **1222 passed** sur `main` (0 échec, environnement complet) — +29 tests,
dont `test_attente_sync_bluemind.py` (nouveau) et les 3 sorties du dialogue F1 en
variante `contexte_cr`. Mesuré à **1215 passed** en clone partiel, en édition complète
*et* lite.

Après le mode de transcription unifié (docs/45, 2026-08-04) : **1228 passed** en
clone partiel (2 échecs d'environnement habituels). La double passe complète/lite et
la gate « lite sans huggingface_hub » disparaissent par construction (un seul bundle) ;
le comportement distant est couvert par les tests `mode_distant` explicites.
Nouveaux : `test_mode_transcription.py`, `test_redemarrage.py`,
`test_premier_lancement.py` ; supprimés : `test_edition.py`,
`TestSpecWindowsEditions` (→ `TestSpecWindows`).

Après la refonte des actions de l'Historique réunions (2026-08-05, validée
manuellement) : **1254 passed** sur `main` (0 échec, environnement complet).
`ActionsDelegate` généralisé — le contrat « specs[0] = Copier » devient
`ActionsLigne(boutons, menu)` avec `BoutonSpec` (split button via
`menu_deroulant`, boutons inactifs peints grisés + infobulle, `largeur_colonne()`
pour dimensionner les colonnes). Ligne de réunion : menu ⋯ **exhaustif** (Copier
la transcription en tête, item CR Mistral **grisé** — plus masqué — sans clé API)
+ 2 boutons dédiés « Générer le CR ▾ » (flèche = choix **ponctuel** du prompt,
visible à partir de 2 prompts exploitables ; `lancer(chemin, prompt=…)` traverse
jusqu'au pipeline sans toucher `prompt_actif`) et « Copier le CR » (copie brute,
sans préfixe de prompt). Régénérer un CR existant demande confirmation
(« Remplacer le CR existant ? », sous le garde-fou anti-réentrance). L'icône
calendrier BlueMind reste **cliquable tant que non associée** (raccourci, l'action
est aussi dans le menu ⋯).

Après le lexique de corrections (docs/46, fusionné le 2026-08-05) : **1285 passed,
0 échec** sur `main` en environnement complet (+33 tests — `test_lexique.py` nouveau
+ extensions pipeline/vues/config). Préférences passées à **10 sections** (« Lexique »
entre Prompts et Dossiers). Le flaky `test_selecteur_micro_distingue_les_api_audio`
révélé pendant ce chantier (l'index d'entrée réel du poste indexait la liste mockée)
a été figé à part (`0e2b8f3` : `sd.default.device` mocké).

Après les prompts par défaut révisés + migration config v2 (fusionné le 2026-08-05) :
**1297 passed, 0 échec** sur `main` en environnement complet. Défauts à **3 prompts**
(« CR simple » réécrit, « CR Pipedrive », « CR full .md » — les 2 CR BlueMind
partagent `_CR_BLUEMIND_CORPS`, seuls intro et format de sortie diffèrent).
**`VERSION_COURANTE` passe à 2** : la migration met à jour le CR simple *seulement*
s'il est resté identique à l'ancien défaut (`CR_SIMPLE_CONTENU_V1`), ajoute les 2 CR
BlueMind si leurs titres manquent, et **resauvegarde la config après migration** (le
bump de version ne persistait pas avant). Une liste de prompts vidée par l'utilisateur
reste vide (la clé existante prime sur les défauts) ; le pipeline CR retombe alors
sur `CR_SIMPLE_CONTENU` codé en dur.

Après le recalage AEC sur inefficacité + dédoublonnage par inclusion (docs/48 §8,
2026-08-18) : **1423 passed, 2 skipped** en clone partiel avec `packaging/vendor/ffmpeg`
construit — **1420 passed, 5 skipped** sans lui — et dans les deux cas les 2 échecs
d'environnement habituels (helper Swift non compilé, audio canonique du benchmark). +9 tests : 4 dans
`test_aec.py` (recalage déclenché par l'inefficacité qui retrouve le délai d'un coup,
budget borné, budget réarmé par `demarrer()`/`recalibrer()`), 5 dans `test_fichiers.py`
(inclusion, sens unique de l'inclusion, plancher de 6 mots, et **2 tests de limite**
qui figent les contre-exemples mesurés : le doublon à 0,70 qu'on laisse passer et le
tour légitime à 0,71 qu'on refuse de jeter). `test_derive_residus_discordants_jamais_appliques`
passe d'un moteur identité à un moteur qui atténue — sinon l'inefficacité constatée
déclencherait, à raison, un recalage, et le test ne parlerait plus de la fuite de
dérive qu'il documente.

Après la retouche boutons/menus de l'Historique (2026-08-21) : **1466 passed** en
environnement complet. Livré en 4 commits : « Copier la transcription » copie
désormais **brut** (plus jamais de préfixe prompt/lexique — le prompt actif et le
lexique ne servent plus qu'au CR Mistral) ; nouvelle action « Copier le fichier de
la transcription » (bouton dédié + menu ⋯, toujours `transcription.md`, via
`PressePapiers.copier_fichier()` — osascript POSIX file sur macOS, QMimeData/URLs
ailleurs ; icône Phosphor `file-arrow-up` ajoutée) ; « Tout supprimer » renommé
« Supprimer » ; et `ui/arbitre_etat_visuel.py` — l'icône passe **orange pendant les
jobs de l'Historique** (transcription locale, locuteurs, CR Mistral), rouge
enregistrement prioritaire, flash vert/gris en fin de job (les orchestrateurs ne
sont plus câblés en direct sur tray/fenêtre : tout passe par l'arbitre dans
`__main__`). **Validé manuellement** par Sylvain le 2026-08-21 (collage Finder de
`copier_fichier` compris). Nouveau : `test_arbitre_etat_visuel.py` (8 tests).

## Environnements Python — ne pas confondre

| Venv | Python | Usage |
|------|--------|-------|
| `.venv` | 3.14 | développement quotidien |
| `.venv-build` | **3.13** | PyInstaller (3.14 non supporté) |

Pour le build packaging : `.venv-build/bin/pyinstaller packaging/debriefMeet.spec --noconfirm --distpath dist --workpath build/work`

## Tests

```bash
pytest -m "not integration"   # rapide, sans matériel
pytest                        # complet
```

Marqueur `integration` = tests nécessitant vrai micro, permissions TCC, visio en cours.
L'agent exécute les tests et rapporte la sortie avant toute livraison.

## État des phases (au 2026-07-03)

| Phase | Statut |
|-------|--------|
| 0 — Socle + archi | ✅ |
| 0.5 — Spike audio système (SCK retenu) | ✅ |
| 1→3 — Dictée, Réunion, Journal macOS | ✅ |
| **4 — Packaging macOS** | 🔄 build réel fait (2026-07-12) — `.app`+`.dmg` signés produits et lancés avec succès, cf. `docs/16` §5 ; reste uniquement §6 (validation TCC manuelle) |
| **4b — Modèle large-v3-turbo** | ✅ TERMINÉ (2026-06-30, turbo = modèle par défaut) |
| **5 — Spike backends Windows** | 🔄 code terminé (505 tests), build VM à lancer — **ne bloque plus la Phase 5** (v1 = CPU, cf. docs/30) |
| **5 — Portage Windows** | 🔄 EN COURS (docs/30→35, ordre docs/30 §6) — prérequis §5 ✅, docs/31 ✅, docs/34 ✅, docs/32 (packaging) ✅ PREMIER BUILD RÉUSSI (2026-07-04, `dist/debriefMeet-setup-0.2.0+20260704.4029f0d.exe`, 125 Mo, gate pytest VM 506 passed), docs/37 (fumée SSH) ✅ TERMINÉ (2026-07-04, `scripts/fumee_setup_vm.sh`, 2 runs verts) — corrigés au passage : `platformdirs appauthor=False` (cf. § dédié), crash QThread access violation (`gestionnaire_diarization.py`), 3 usages de `subprocess.Popen(["open", ...])` macOS-only cassant sur Windows (`preferences_view.py`, `reunion_view.py`) trouvés en **test interactif réel sur la VM** et corrigés ; désinstallation interactive **validée propre** par Sylvain (dossier app+données+Registre supprimés, Documents préservé — cf. docs/37 §7, limite confirmée propre à SSH) ; reste : docs/35 (livraison)
| **Correctifs fuites CoreAudio (docs/23)** | ✅ TERMINÉ (2026-07-02, 530 passed) |
| **Robustesse micro hot-plug (docs/25)** | ✅ TERMINÉ (2026-07-02, 542 passed) |
| **Fix dictée/journal muets (docs/27)** | ✅ TERMINÉ (2026-07-02, 556 passed) |
| **Raccourcis globaux paramétrables (docs/28)** | ✅ TERMINÉ + validé manuellement (2026-07-02, 573 passed) |
| **Fix diarization pyannote 4.x (docs/29)** | ✅ TERMINÉ + validé manuellement (2026-07-02, 576 passed) — offline via `HF_HUB_OFFLINE`, `local_files_only` supprimé |
| **Fix crash QThread à l'arrêt (docs/26)** | ✅ TERMINÉ (2026-07-03, 589 passed) — registre workers MLX + kill forcé, helper `arreter_thread`/`proteger_thread` |
| **Interco BlueMind — calendrier, invités, notifications (docs/40)** | 🔄 code + tests unitaires ✅ TERMINÉS (2026-07-09, 889 passed sans réseau) — reste : tests d'intégration (`BM_TEST_URL/TOKEN/EMAIL`) et validation manuelle avec Sylvain sur serveur réel (docs/40 §10). **Fix 2026-07-27** : réunions **récurrentes** invisibles à l'association — `_search` renvoie la série maître, pas les occurrences ; ajout de `core/bluemind/recurrence.py` (expansion `rrule`/`exdate`/exceptions, DST-safe, dép. `python-dateutil`), synchro passée en resync complète (incrémental retiré). Validé en réel (clé API temporaire) sur « point commerce Bastien ». cf. docs/40 §5.2 |
| **ffmpeg embarqué Windows — rétention Opus garantie (docs/41)** | ✅ TERMINÉ (2026-07-12, 938 passed Mac + 780 passed VM) — build+fumée réels validés, setup 159 Mo |
| **Interco Mistral — CR cloud adaptatif, transcription Voxtral (docs/42)** | ✅ TERMINÉ + **fusionné dans `main`** (2026-07-21) — code + tests (1046 passed sur `main`) + validation manuelle clé API réelle OK. **Complété le 2026-08-04** : le flux « Générer le CR (Mistral) » **propose l'association BlueMind avant l'envoi** quand un événement correspond (le CR n'étant jamais régénéré, c'est le dernier moment pour enrichir sujet/date/participants + `context_bias` Voxtral) — resync forcée et **attendue**, dialogue F1 à 3 sorties (Associer / Sans association / Annuler), association **avant** la confirmation de confidentialité. ⚠️ « Associer » applique le titre donc **renomme le dossier** : le job doit partir sur `dlg.chemin_md`. Fusionné (`56a4462`), validé manuellement, 1222 passed. **2026-08-05** : « Générer le CR » devient un **bouton dédié** de la ligne avec flèche de choix ponctuel du prompt + bouton « Copier le CR », menu ⋯ exhaustif, confirmation avant remplacement d'un CR existant (cf. § tests du 2026-08-05). cf. docs/42 §4.1 |
| **Édition lite Windows — enregistrement Opus + IA distante (docs/44)** | 🔄 code + tests + **builds réels + fumée** ✅ (2026-07-30) — `debriefMeet-lite-setup-0.2.0+20260730.59fa002.exe` **116 Mo** contre 159 Mo pour la complète (−27 %), **aucun modèle téléchargé** au 1ᵉʳ lancement. Gates VM : **982 passed/5 skipped** (complète) et **971/16** (lite) — l'écart de 11 dans les 2 sens = les `importorskip("huggingface_hub")`. Fumée **0 échec** sur les 2 setups, dont l'assertion décisive « ctranslate2 retiré par le passage à lite » (valide `[InstallDelete]`). **Livrée et utilisée en réel** chez une utilisatrice Windows (docs/44 §8) : CR Voxtral produit avec une vraie clé API. Embarque un bouton « Exporter les logs (.zip)… » (Préférences › Journalisation, indépendant de l'édition), dont le zip **caviarde les secrets** — un diagnostic réel avait transmis clé Mistral et token BlueMind en clair. Révélé au passage **4 bugs pré-existants** : `tzdata` absent sous Windows (récurrences BlueMind en régression DST silencieuse), 2 hypothèses macOS non gardées dans les tests, et une **tempête de reconnexions micro** (3082 en 65 min sur puce Realtek SST → micro non enregistré), corrigée **sur Windows uniquement**. Reste : chaîne de bout en bout avec du vrai contenu audio, + 4 points mineurs (docs/44 §8.7). **⚠️ Remplacée par le mode de transcription unifié (docs/45, 2026-08-04) — plus de build lite.** cf. docs/44 §6-8 |
| **Mode de transcription unifié — un seul build, réglage Préférences (docs/45)** | 🔄 code + tests ✅ (2026-08-04, **1228 passed** clone partiel) — remplace les éditions complete/lite : clé `mode_transcription` (défaut **distant** pour tous), figée au démarrage par `core/mode_transcription.initialiser()`, prédicats `avec_*` inchangés sur les 17 sites. Préférences réorganisées (9 sections inconditionnelles, section « Transcription » = choix du mode + réglages locaux, « IA en ligne » = ex-Remote IA), écran de bienvenue au 1ᵉʳ lancement (`accueil_fait`, joue aussi sur les installations existantes), redémarrage proposé au changement de mode (`core/redemarrage.py`, relance détachée après `app.exec()`). Chaîne de build lite supprimée (spec, `.iss`, `--lite`, extra `windows-lite`) ; `[InstallDelete]` conservé pour la transition depuis un poste lite. Reste : build VM + fumée du setup unifié, validation manuelle de la relance (3 environnements), transition réelle chez Alix. cf. docs/45 §5 |
| **Réorganisation 1 dossier/réunion (docs/43)** | ✅ **TERMINÉ** — fusionné dans `main` et **validé manuellement** par Sylvain (2026-07-27, 1099 passed). La migration des réunions à plat a tourné une fois sur le poste de Sylvain (23 réunions → dossiers), puis son **code a été retiré** (app non déployée ailleurs) — les dossiers en précision minute qu'elle avait laissés ont ensuite été **normalisés en `HH-MM-00`** pour permettre le retrait du code de compatibilité (docs/43 §7 ; secondes désormais obligatoires, cf. § « Stockage des réunions »). ⚠️ Un rollback avant `1ed3b17` rendrait les réunions invisibles (ancien listing à plat) et il n'y a plus de migration à rejouer. Correctif embarqué : réunion active exclue du listing (ligne en double). Bilan & écarts : docs/43 §15. |
| **Lexique de corrections — tableau « entendu → à écrire » injecté dans les prompts (docs/46)** | ✅ **fusionné dans `main`** (41cfe8a, 2026-08-05, **1285 passed** 0 échec env complet), section Préférences **validée manuellement** (en-têtes de colonnes raccourcis suite au test : Qt centre et tronque des deux côtés un en-tête plus large que la colonne) — module pur `core/lexique.py` (bloc d'instructions + `completer_prompt`, seul point d'entrée des 2 sites d'injection : pipeline CR Mistral après résolution du prompt, copie avec prompt de l'Historique), clés `lexique_corrections`/`lexique_actif` (défauts pré-remplis vocabulaire BlueMind, **actif d'office** — les installations existantes en bénéficient sans config), section Préférences dédiée « Lexique » (10ᵉ, tableau 2 colonnes + case, grisé si inactif), termes « à écrire » ajoutés au `context_bias` Voxtral **derrière** les invités BlueMind (même interrupteur). Reste : un CR Mistral réel avec le lexique (clé API). cf. docs/46 |

## Packaging macOS (Phase 4) — pièges

- **Certificat local stable** `« debriefMeet Local »` (créé par `packaging/creer_certificat.sh`) — doit signer identiquement l'app ET le helper Swift à chaque build, sinon les permissions TCC (Micro + Enregistrement de l'écran) sont perdues.
- Vérifier : `codesign -dv dist/debriefMeet.app` — même Authority entre deux builds.
- Bundle id : `com.sylvaingarcia.debriefmeet` (aligné partout, y compris `demarrage_auto.py`, depuis 2026-07-02).
- **Pas d'auto-update en v1** — MAJ = re-téléchargement manuel du `.dmg`.
- La config (`platformdirs`) et les transcriptions (`~/Documents/debriefMeet`) vivent hors du bundle → survivent au remplacement.
- **ffmpeg embarqué (LGPL, `packaging/build_ffmpeg.sh`)** : à compiler une fois avant `build_app.sh` (binaire non versionné, `packaging/vendor/`). Pièges configure : les demuxers/muxers PCM bruts s'activent sous leur nom **interne** (`pcm_f32le`, `pcm_s16le`), pas le nom court de `ffmpeg -demuxers` (`f32le`/`s16le`) ; `--disable-postproc` n'existe plus en ffmpeg 8.1.x ; et **la liste des filtres se périme** — `aselect,asetpts` manquaient (ajoutés le 2026-08-18), donc la compaction des silences Mistral échouait **dans l'app livrée uniquement**, jamais en dev où répond le ffmpeg Homebrew complet. Toute nouvelle invocation de ffmpeg dans le code oblige à revisiter `--enable-*` ; `valider_binaire` exige désormais ces filtres (binaire trop ancien → reconstruit) et le build rejoue les 2 passes de `compacter_piste`.
- **`sys.executable` en app figée n'est pas un interpréteur Python générique** : `multiprocessing` (déclenché en interne par mlx/torch, ex. `resource_tracker`) le relance parfois en `-c "<code>"` pur → `__main__._relais_interprete_figee()` émule `python -c` avant tout autre routage (sinon bruit `unrecognized arguments`, sans casser la transcription).
- Premier `codesign` réel après création du certificat : peut afficher une popup trousseau **invisible aux API de scripting/accessibilité** (fenêtre sécurisée) — nécessite un clic humain une fois (« Toujours autoriser »), aucun moyen de la détecter ou franchir en automatique.

## Build Windows (benchmark + Phase 5)

**Le build se fait en natif sur la VM Proxmox, jamais en cross-compile depuis le Mac.**

- VM : `192.168.1.29`, SSH `sylvaing` (mot de passe hors dépôt)
- Script benchmark : `scripts/build_windows_vm.sh`
- Script spike backends : `scripts/build_spike_backends_vm.sh` ← Phase 5
- **Script app (setup installeur) : `scripts/build_app_windows_vm.sh`** ← Phase 5
  (docs/32) — rsync sources + `BUILD_INFO` (date+hash git), pytest bloquant sur la VM,
  PyInstaller onedir (`packaging/windows/debriefMeet.spec`), Inno Setup
  (`packaging/windows/debriefMeet.iss`), rapatrie
  `dist/debriefMeet-setup-<version>.exe`. **Un seul setup depuis docs/45** (plus de
  `--lite` ni d'extra `windows-lite` — le mode distant/local est un réglage
  utilisateur). Prérequis VM à installer une fois : Python 3.13 x64, Inno Setup 6
  (`ISCC.exe`, souvent installé per-user par winget sous
  `%LOCALAPPDATA%\Programs\Inno Setup 6\`, pas forcément `Program Files (x86)`).
- **Script fumée (installer/MAJ/désinstaller) : `scripts/fumee_setup_vm.sh`** ← Phase 5
  (docs/37) — via SSH, sans interface graphique : install `/VERYSILENT`, `--version`,
  réinstall par-dessus, désinstallation (docs/32 §4). Rejouable (nettoie avant/après).
  ⚠️ Limite connue : `usPostUninstall` du `.iss` ne se déclenche jamais via SSH
  (désinstalleur non auto-supprimé, Registre non nettoyé) — signalé en `[INFO]`, pas
  bloquant ; à revalider une fois en session interactive (cf. docs/37 §7).
- Garder la session SSH **ouverte** pendant le build — un process détaché est tué à la fermeture de session.
- Build ~20-40 min (première fois). Rebuild plus rapide : modèles HF déjà en cache sur la VM.
- HF_TOKEN optionnel : `HF_TOKEN=hf_xxx bash scripts/build_spike_backends_vm.sh`
- Doc benchmark : `docs/08-benchmark.md` § « Build & distribution »
- Doc spike : `docs/18-spike-backends-windows.md` §11 (journal de build, pièges résolus)
- Doc packaging app : `docs/32-phase5-packaging-cycle-de-vie.md`

## Piège `platformdirs` sur Windows — `appauthor=False` obligatoire

`platformdirs.user_config_dir/user_data_dir/user_log_dir(APP_NAME)` **sans**
`appauthor` explicite double le dossier sur Windows uniquement :
`%LOCALAPPDATA%\debriefMeet\debriefMeet` au lieu de `%LOCALAPPDATA%\debriefMeet`
(la lib traite `appname` comme « author » par défaut — `Windows._append_parts` :
`author = self.appauthor or self.appname`). Absent sur macOS/Linux. Tous les appels
de l'app passent donc `appauthor=False` (`core/config.py`, `core/logs.py`,
`platform/windows/moteur_faster_whisper.py`) — conséquence pratique : config,
logs et modèles téléchargés vivent tous sous la **même racine**
`%LOCALAPPDATA%\debriefMeet`, ce qui simplifie `[UninstallDelete]` dans le `.iss`
à une seule entrée (docs/32 §4).

## Capture loopback Windows

Utiliser **`soundcard`**, pas `sounddevice` (PortAudio ne sait pas faire le loopback WASAPI).

```python
# Capturer en stéréo puis downmixer — soundcard rend du bruit si 1 canal explicite sur WASAPI
sc.get_microphone(sc.default_speaker().name, include_loopback=True).record(...)
```

Pour le benchmark c'est validé. Pour le produit Phase 5, le spike dédié est remplacé par la stratégie « logs = spike » : surveillance du haut-parleur par défaut + réouverture à chaud + repli silence, spécifiée dans `docs/34` §2.3 (cas BT, changement de sortie à chaud).

## Moteur de transcription par OS

| OS | Moteur | Accélération |
|----|--------|-------------|
| macOS | `mlx-whisper` | Apple Silicon (MLX) |
| Windows | **v1 : faster-whisper CPU int8** (worker subprocess, docs/34) ; iGPU (OpenVINO / DirectML / Vulkan) ajouté après le rapport spike doc 18 | CPU (v1), iGPU AMD/Intel (ensuite) |
| Linux | `faster-whisper` | CPU / CUDA |

Machines cibles Windows : Bastien (AMD Ryzen 5 PRO 5675U + iGPU Radeon), Alix (Intel i5-1235U + iGPU Intel UHD) — **pas de NVIDIA**.

## Docs de référence

| Sujet | Doc |
|-------|-----|
| Specs fonctionnelles | `docs/01` |
| Architecture technique | `docs/02` |
| Phases & Definition of Done | `docs/03` |
| AEC (WebRTC/livekit) — ⚠️ inefficace sur le terrain, cf. docs/48 | `docs/06` |
| Diarization (pyannote) | `docs/07` |
| Benchmark RTF/WER | `docs/08` |
| Packaging macOS | `docs/16` |
| Spike backends Windows | `docs/18` |
| Ajout large-v3-turbo (macOS) | `docs/19` |
| Correctifs fuites CoreAudio | `docs/23` |
| Crash QThread à l'arrêt (diagnostic) | `docs/24` |
| Fix crash QThread à l'arrêt (implémenté) | `docs/26` |
| Fix dictée/journal muets (normalisation centrale) | `docs/27` |
| Raccourcis globaux paramétrables (macOS, Carbon) | `docs/28` |
| Fix diarization (pyannote 4.x, `local_files_only`) | `docs/29` |
| Robustesse micro hot-plug | `docs/25` |
| **Phase 5 Windows — architecture (chapeau, ordre d'exécution)** | `docs/30` |
| Phase 5 — observabilité / logs debug / export diagnostic | `docs/31` |
| Phase 5 — packaging Inno Setup, install/MAJ/désinstallation | `docs/32` |
| Phase 5 — transposition des correctifs macOS (exigences E-1→E-8) | `docs/33` |
| Phase 5 — adaptateurs Windows (moteur, WASAPI, raccourcis…) | `docs/34` |
| Phase 5 — livraison, notice utilisateur, analyse des diagnostics | `docs/35` |
| Phase 5 — fumée automatisée du setup via SSH (VM) | `docs/37` ✅ (`scripts/fumee_setup_vm.sh`) |
| Vibrancy native menu tray (macOS, NSVisualEffectView) — non implémenté | `docs/38` |
| **Interco BlueMind (calendrier, invités, notifications) — 🔄 code+tests faits ; fix récurrences 2026-07-27 (§5.2)** | `docs/40` |
| ffmpeg embarqué Windows (rétention Opus garantie) | `docs/41` |
| **Interco Mistral (CR cloud adaptatif, transcription Voxtral) — ✅ terminé, validé manuellement, fusionné dans `main` ; §4.1 = association BlueMind proposée avant le CR** | `docs/42` |
| **Réorganisation 1 dossier/réunion — ✅ terminé, validé manuellement, fusionné dans `main` (bilan §15)** | `docs/43` |
| Édition lite Windows — **obsolète**, remplacée par docs/45 (historique : décisions, pièges, terrain) | `docs/44` |
| **Mode de transcription unifié (un seul build, réglage distant/local) — 🔄 code+tests faits, build VM à lancer** | `docs/45` |
| **Lexique de corrections (tableau « entendu → à écrire » injecté dans les prompts + biais Voxtral) — ✅ fusionné dans `main`, UI validée manuellement** | `docs/46` |
| Diarization Voxtral V2 en mode distant — **piste non instruite** (annonce Transcribe 2 de 2026-02 : diarization batch, 3 h/requête ; questions §4 à instruire avant chantier) | `docs/47` |
| **Phase 6 — Portage Linux (Ubuntu 26.04 LTS)** | 🔄 EN COURS (docs/49, 2026-08-10) — v1 = mode **distant seul**, **sans raccourcis globaux** (Wayland), packaging **`.deb` amd64** avec `Depends: ffmpeg` (pas de ffmpeg embarqué). Cible : collègue BlueMind sur portable x86_64, en prod. **Faits** : LXC `192.168.1.32` provisionné (**Python système 3.14.4, sans PPA** — décision L7, la contrainte « PyInstaller ≠ 3.14 » a expiré ; Mac/Windows restent en 3.13, alignement séparé), **gate pytest VERTE : 1141 passed, 21 skipped, 0 échec** ; spike `spike/capture_monitor_linux/` (protocole guidé) ; adaptateurs `platform/linux/` (presse-papiers, démarrage auto `.desktop`), `_linux()` remplie ; retouches §5.5 (ffmpeg système en figé, logs DEBUG par défaut, infos système distro/session/PipeWire). Mac inchangé à **1351 passed**. **Spike TERMINÉ** (3 passages chez le collègue, 2026-08-12/13) : `.monitor` visibles **uniquement sous le hostapi PulseAudio**, `pactl get-default-sink` **nécessaire** pour choisir le bon, 48 kHz stéréo comme WASAPI. **Deux modes de panne opposés** — son parti ailleurs = zéros parfaits (indiscernables d'une réunion calme, détection `pactl`) ; **sink disparu = flux GELÉ**, `stream.active` toujours `True`, aucune exception (détection uniquement par absence de trames). D'où : surveillance `pactl` **+** chien de garde sur les trames + repli silence à hauteur du temps écoulé (sinon décalage inter-pistes = durée de la panne, docs/48). `platform/linux/capture_systeme_monitor.py` **écrit** (25 tests) : résolution par `pactl` sans repli aveugle, surveillance de la sortie par défaut, chien de garde sur les trames, repli silence à hauteur du temps écoulé (logs limités pour ne pas noyer le fichier rotatif). ⚠️ Il **ne rafraîchit jamais** la table PortAudio — `sd._terminate()` fermerait le flux micro en pleine réunion ; `micro_sounddevice.demarrer()` le fait juste avant, donc la table est fraîche à chaque début de réunion (une sortie apparue *pendant* reste invisible, limitation assumée identique au micro). **Packaging ✅ PREMIER BUILD RÉUSSI** (2026-08-13) : `debriefmeet_0.3.0+20260813.e5d38bd_amd64.deb`, **120 Mo**, via `scripts/build_app_linux_lxc.sh` (gate pytest bloquante incluse) — PyInstaller 6.22 sur Python 3.14 confirmé en réel. **Fumée verte** (`scripts/fumee_deb_lxc.sh`) : Depends (dont libportaudio2), install apt, `--version`, réinstall, purge. Extra `linux` = `livekit` seul (pas de faster-whisper dans le bundle v1). Gates après fusion avec `main` : **1403 passed** Mac (2 échecs d'env. habituels), **1186 passed, 0 échec** LXC. **Première panne terrain corrigée** (2026-08-13, §6.4) : fuite de descripteurs sqlite — `StoreCalendrier._connexion()` ne fermait jamais ses connexions (le `with` de sqlite3 = transaction seule) et les délégués de l'Historique l'interrogent à chaque frame de l'animation d'enregistrement → EMFILE en 35 s sur la limite Ubuntu de 1024 (invisible sur Mac, limite ~1 M). Contextmanager + close() en finally, test de régression sous `gc.disable()`. Nouveau build fumé : `debriefmeet_0.3.0+20260813.cd5620c_amd64.deb`. ✅ **VALIDÉ SUR LE TERRAIN le 2026-08-13** : le `.deb` corrigé fonctionne chez le collègue → branche `claude/linux-ubuntu-porting-plan-2cfbf9` **fusionnée dans `main`** et supprimée. **3 défauts d'intégration GNOME corrigés** (2026-08-14, §6.5) : icône de tray illisible (le « template » `setIsMask` est un mécanisme **macOS**, ignoré sous Linux → blanc plein sur bandeau sombre — surtout **ne pas** dériver ça de `colorScheme()`, le bandeau Ubuntu est noir même en thème clair) ; **aucune action au clic** (StatusNotifierItem n'appelle jamais `Activate` : `setContextMenu()` est obligatoire sous Linux, alors qu'il est proscrit sur macOS) ; fenêtre sans contour (le décorateur Wayland ne dessine pas d'ombre → liseré 1 px maison). `Depends` complétés : `libgtk-3-0t64`, `adwaita-icon-theme`. Gates : **1417 passed** Mac, **1193 passed** LXC. **Reste** (hors v1) : notice utilisateur, raccourcis globaux (portail XDG, L2), mode local (docs/49 §4.3). Ordre docs/49 §8. |
| **AEC inefficace sur le terrain + transcriptions en double — 🔄 étapes A/B/C-mesure implémentées** (diagnostic mesuré du 2026-08-06 : décalage inter-pistes 300-700 ms variable par réunion + dérive ~125 ppm, calibration one-shot inadaptée, att −0,2/−1 dB partout ; livré : dédoublonnage à la fusion `_entrelaces`, `DELAI_MAX_MS` 600→1500 ms, ré-estimation périodique du délai + WARNING d'écho résiduel, log de l'offset d'ingestion ; reste : validation terrain §5 + compensation d'offset). **Rechute du 2026-08-18 (§8)** : le délai calé à la 1ʳᵉ tranche (383 ms, correct — l'AEC annulait −25/−40 dB les 11 premières minutes) a été périmé par un **saut de ~68 ms de l'offset inter-pistes** (la chaîne micro **perd des paquets d'échantillons** — pas une dérive d'horloge : 12 ppm mesurés sur les fichiers, §8.4 ; mécanisme candidat : callback PortAudio affamé par le GIL, buffer HAL débordé — la chaîne SCK, process séparé, est immune). Un saut qui met la référence en retard sur l'écho casse la causalité → 0 dB instantané (marge de lead 40 ms), et le suivi de dérive a mis 20 min à rattraper → 22 min de voix distante dans la piste micro, attribution inutilisable. Corrigé (3 volets complémentaires) : **comblement des trous à la source** dans le callback micro (discontinuité d'horodatage ADC → silence de même durée, seuil 20 ms/plafond 10 s, WARNING 1 ligne/tranche max, les 3 OS — l'offset ne peut plus sauter, moi.opus/systeme.opus restent alignés) ; `QUALITE_CORR_CALAGE = 25` pour bouger l'alignement (sous ~25 l'estimation de délai est du bruit, la détection d'écho résiduel garde 10) ; le WARNING d'inefficacité déclenche un **recalage complet** du délai (borné à `RECALIBRAGES_AUTO_MAX = 3`, budget neuf à chaque `demarrer()`/`recalibrer()`), et le dédoublonnage gagne un critère d'**inclusion en mots**, `autojunk=False`, **directionnel** (couverture du segment MICRO par le système — l'inverse jetterait la parole de l'utilisateur), seuil 0,75 calibré sur les 73 réunions du poste. ⚠️ Le seuil ne peut pas descendre : un doublon manqué fait 0,70 et un tour légitime 0,71. Trouvé au passage : `aselect`/`asetpts` absents du ffmpeg embarqué macOS → compaction des silences Mistral **cassée depuis toujours dans l'app livrée** (exit 234, envoi intégral), invisible en dev ; filtres ajoutés + exigés par la validation du binaire + les 2 passes rejouées dans le build) | `docs/48` |
| **Phase 6 — Portage Linux Ubuntu 26.04 (distant seul, `.deb` amd64, build LXC Proxmox) — ✅ implémenté, validé chez l'utilisateur, fusionné dans `main`** | `docs/49` |
| **Dialogues : défilement, suivi de fenêtre, listes de participants — ✅ IMPLÉMENTÉ (2026-08-20, 1456 passed, 0 échec ; reste les vérifications manuelles §4)** (déclencheur : un événement BlueMind à ~34 invités poussait le pied de page hors de l'écran — plus aucun bouton, parcours CR Mistral bloqué). Livré : corps **défilant** dans `DialogueGabarit` (en-tête et pied fixes) + hauteur de carte plafonnée — `AlignCenter` sert le `sizeHint` sans borner, seule la taille **maximale** plafonne ; overlay devenu **widget enfant** de la fenêtre hôte (suit déplacement et redimensionnement sans code de suivi, `exec()` émulé par boucle imbriquée) — la modalité passe d'applicative à fenêtre, sans effet réel : l'app n'a qu'une fenêtre, les Préférences en sont une page ; carte d'association 440→580 px + infobulle ; « Tout cocher/décocher » avec compteur `PARTICIPANTS (n/N)` ; **pré-cochage à seuil** — tout coché jusqu'à `SEUIL_PRECOCHAGE = 8` personnes, au-delà organisateur + `STATUT_ACCEPTE` seulement (un événement à 34 invités externes nourrissait le CR de noms absents → participants inventés). ⚠️ Piège Fusion/Linux trouvé au passage : le fond du viewport doit être neutralisé par une feuille de style posée sur **le viewport seul** (sur le `QScrollArea` elle bascule aussi la barre de défilement ; une palette blanche, elle, est écrasée par le `QWidget {…}` global) — invisible sur macOS. `bluemind_details` réparé sans le toucher | `docs/50` |
