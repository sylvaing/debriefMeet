# debriefMeet — contexte pour Claude Code

Application de transcription vocale locale (dictée, réunion, journal).
Stack : Python + PySide6 (Qt 6), moteur Whisper accéléré par OS.

## Confidentialité du dépôt (publication GitHub, 2026-10-20)

Le dépôt est destiné à être publié. **Aucune donnée client, aucun enregistrement, aucune
transcription réelle** n'y entre (cf. `.gitignore`), et le lexique par défaut est
**vierge** (docs/46 §7). Les prénoms des utilisateurs terrain cités dans les docs et les
tests (Alix, Bastien, Cyril, Dario…) sont des **pseudonymes** — ne jamais réintroduire
les identités réelles, ni des noms de clients, dans le code, les docs ou les fixtures.

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

**Un renommage peut survenir pendant un job de fond.** Renommer est interdit pendant un
*enregistrement* (handles audio ouverts → WinError 32), mais reste possible — et
encouragé, c'est le geste du flux pré-CR — pendant un **job a posteriori** qui dure des
minutes en tenant le chemin capturé à son lancement. Tout code qui écrit dans le dossier
d'une réunion après une opération longue doit donc passer par
`core/fichiers.resoudre_chemin_reunion(md)`, qui retrouve le dossier par son **préfixe
horodaté** (seule identité stable : le renommage ne touche que le slug). Il rend le chemin
**inchangé** si le dossier existe encore (un seul `stat`), si la réunion a été supprimée
(l'appelant échoue comme avant) ou si **plusieurs** dossiers partagent le préfixe (le
compteur de collision est posé *après* le slug — écrire dans la mauvaise réunion serait
pire que l'échec réparé). Câblé sur les 5 points d'écriture des 3 pipelines et dans les
handlers de fin des 2 gestionnaires. Cf. docs/43 §6.4 et §16.

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

Après le correctif « Quitter » du tray sous Linux (2026-08-24) : **+4 tests**, soit
**1482 passed** sur la branche `fix/diarization-pyannote-4-0-6` (1478 avant). Les
4 tests portent sur l'**effet** de l'activation, pas sur le libellé : action simple
(non-`QWidgetAction`) et sortie effective sous Linux, widget rouge conservé et clic
souris effectif ailleurs, sortie aussi par `trigger()` (clavier/hôte externe), et
pas de double sortie sur le chemin souris. ⚠️ `make test` se termine par un
`Segmentation fault: 11` **au teardown de pytest, après le rapport** — préexistant
sur `main`, non lié à ce correctif (vérifié en stash).

Après le correctif de la colonne actions + l'icône de job de l'Historique
(2026-08-24, **validé manuellement** par Sylvain) : **1498 passed**, 0 échec en
environnement complet (1482 avant), en 2 commits verts indépendamment. Deux défauts
distincts, tous deux sur les icônes des lignes de réunion :

1. **Colonne actions sous-dimensionnée** — la largeur était restée calée sur 2 boutons
   dédiés alors que `_boutons_reunion` en produit **3** depuis la retouche du
   2026-08-21 (« Copier le fichier »). 130 px au lieu de 162 ; `ActionsDelegate._zones`
   construisant depuis le bord **droit** sans clipper, le bouton « Générer le CR »
   était peint de −32 à −2 px, soit pile sur l'icône de la colonne « lien calendrier »
   (3..31 d'une colonne de 34) : **superposition** sur macOS, apparence « collée » sur
   Windows, et Linux touché de la même façon — la géométrie est 100 % Python. La
   largeur passe désormais par `NB_BOUTONS_REUNION`/`NB_FLECHES_REUNION`, qui
   documentent le pire cas réel. ⚠️ `test_largeur_colonne_journal_et_reunion` ne
   pouvait pas voir la régression : il vérifie la **formule**, jamais le nombre de
   boutons qu'on lui passe. L'accord est maintenant testé côté vue
   (`test_colonne_actions_dimensionnee_pour_les_boutons_reellement_produits`), plus le
   symptôme lui-même sur les `visualRect` réels des deux colonnes.
2. **L'icône de la ligne montre l'opération en cours** — la colonne 0 cédait toujours
   « users-three » : rien ne disait qu'un traitement **a posteriori** tournait sur
   telle réunion. Elle affiche maintenant l'icône du job (transcription →
   `file-text`, locuteurs → `users`, CR Mistral → `notebook`, type inconnu →
   `arrows-clockwise` — une icône « réunion » mentirait sur l'inactivité), teintée
   `C.JOB` : le même orange que l'icône de tray dans cet état, sorti du bloc tray sous
   un nom sémantique dont `TRAY_TRANSCRIBE` dérive (le tray dit qu'une opération
   tourne, la ligne dit laquelle et sur quelle réunion) + infobulle sur la colonne.
   `CaptureModel.definir_job_en_cours(chemin, type)` suit le modèle de
   `definir_chemin_actif` — le modèle ne connaît toujours aucun gestionnaire — et
   **`ReunionView.recharger()` devient le point de rechargement UNIQUE** : les 11
   `self._modele.recharger()` directs passent par lui, sinon l'icône se périme au
   premier rechargement venu d'ailleurs (watcher de dossier, fin de mapping des
   locuteurs, association BlueMind). Deux pièges figés par des tests : les
   gestionnaires remettent `_job_en_cours` à None **avant** d'émettre
   `termine`/`echoue` (le handler voit donc bien « plus de job » — inverser cet ordre
   casse un test) ; et la ligne « en cours » a `Path()` pour chemin sentinelle, qu'un
   `_job_chemin` lui aussi vide égalerait, collant une icône de job à
   l'enregistrement live. Les tests comparent les **images rendues**, pas les `QIcon` :
   ça fige la forme (donc *quelle* opération) autant que la teinte.

Après la copie du CR mise en forme (docs/51, 2026-08-26, **validé manuellement** par
Sylvain — collage réel dans une note Pipedrive) : **1581 passed**, 0 échec en
environnement complet (1498 avant), +45 tests, en 4 commits verts indépendamment.
Déclencheur : le prompt « CR Pipedrive » produisait des `<b>`/`<i>`/`<br>` littéraux
pour contourner l'absence d'interprétation markdown de Pipedrive, mais collés en
texte brut ces balises restaient visibles — un éditeur riche ne met en forme que ce
qu'il reçoit **déjà en HTML** sur le presse-papiers, jamais un texte collé. Mesuré
**à la balise près** sur une note de test relue via l'API Pipedrive (`getNotes`) :
seuls les niveaux de titre `h1`-`h3` sont aplatis en `<div>`, tout le reste (gras,
italique, listes imbriquées, liens, citation, code, tableau) survit — et le CR
BlueMind ne s'appuie jamais sur des titres (structure 100 % en gras), donc rien
n'était perdu. `core/markdown_html.py` (nouveau, pur) convertit à la volée au moment
du copier, calibré sur les **56 CR réels du poste** plutôt que sur CommonMark strict
— le modèle écrit majoritairement `**TEXTE **` (délimiteur fermant précédé d'une
espace, non *right-flanking* en CommonMark : un convertisseur conforme afficherait
les marqueurs en clair sur la construction centrale du CR), enveloppe 54 % de ses CR
dans ` ```markdown ` malgré la consigne contraire, et mélange 2/3/4 espaces
d'indentation dans un même fichier (niveaux comparés **relativement**, pas en
profondeur absolue). `PressePapiers.copier_riche(html, texte)` — implémentation
commune aux 3 OS, macOS quittant `pbcopy` pour `QMimeData` (`pbcopy` ne porte pas de
flavor HTML). Bouton de copie de l'Historique devenu split button (clic = mis en
forme, flèche = choix du format) ; prompt Pipedrive retiré des défauts, migration
config **v4** (ne retire que s'il est resté identique au défaut, recale
`prompt_actif` — un index, pas un nom). ⚠️ `NB_FLECHES_REUNION` passé à 2, même
famille de piège que la régression du 2026-08-24 ci-dessus : le garde-fou existant a
été étendu pour continuer à couvrir le pire cas réel (CR effectivement présent dans
la fixture, sinon le test ne verrait plus rien si la flèche de copie devenait un jour
conditionnelle). Build Windows + fumée automatisée **verts** le soir même sur ce
commit (`debriefMeet-setup-0.3.0+20260826.1cbbd5d.exe`).

Après le correctif « renommage pendant un job de fond » (docs/43 §16, 2026-08-28) :
**1599 passed**, 0 échec en environnement complet, +15 tests, en 2 commits verts
indépendamment (1597 sur le premier). Un job a posteriori (CR Mistral, transcription
différée, diarization) dure des minutes et tenait le chemin **absolu** capturé à son
lancement, pendant que l'association BlueMind ou l'édition du titre **renommait le
dossier** : 5 `FileNotFoundError` réelles entre le 2026-07-29 et le 2026-08-26, dont
2 datées à la seconde qui documentent 2 étapes distinctes du pipeline CR (réécriture de
`transcription.md` 347 ms après l'upload Voxtral, puis écriture de `CR.md` après la
rédaction). ⚠️ Le flux pré-CR n'était **pas** en cause (`_proposer_association_avant_cr`
retourne bien `dlg.chemin_md`) : le trou est structurel, rien ne verrouille l'association
ni `CaptureModel.setData` pendant un job — `setData` ne se protège que de `ligne.en_cours`,
c'est-à-dire de l'**enregistrement**. Corrigé côté job (`resoudre_chemin_reunion`, cf.
§ « Stockage des réunions ») plutôt que par un verrou d'UI, qui bloquerait l'utilisateur
plusieurs minutes précisément au moment où on lui propose d'associer. Effet de bord
trouvé en chemin : les gestionnaires émettaient `termine`/`echoue` au chemin périmé, donc
`_inserer_bloc_invites_si_associe` lisait un sidecar disparu et le cartouche invités
manquait **silencieusement**. ⚠️ Piège de test figé dans docs/43 §16.6 : le renommage doit
être déclenché **depuis le mock lui-même** (`side_effect` respx, `_transcrire_pret`,
`diariser`) — posé avant l'appel, il teste un cas plus facile que le code d'entrée gérait
déjà, et resterait vert en cas de régression.

Après le garde-fou AEC recalé sur une preuve (docs/48 §8.6, fusionné le 2026-08-28) :
**+3 tests** (1577 passed en clone partiel sur le correctif seul, 1574 avant), et
**1592 passed** au sommet de `main` une fois rebasé sur les 2 commits `fix(jobs)` du
même jour — dans les deux cas les 2 échecs d'environnement habituels (helper Swift non
compilé, audio canonique du benchmark). Déclencheur : le
diagnostic de Alix du 2026-08-27 (build `1cbbd5d`), dont les **deux** réunions se
terminaient par « AEC DÉSACTIVÉE — l'offset entre les pistes a sauté de 771 / 1200 ms »,
verdict **faux dans les deux cas**. Ce qui sautait était l'**estimation** du délai, pas
l'offset : en casque fermé il n'y a pas de trajet acoustique, donc pas de vrai pic de
corrélation, et chaque calage tire un lag au hasard dans ±`DELAI_MAX_MS`. Un saut RÉEL,
lui, se voit dans les longueurs livrées (la tranche amputée arrive courte) —
`ProcesseurAEC` tient donc son propre `_cumul_ecart_ech` (même mesure que
`core/reunion.py`, comptée dans `pousser()` **avant** toute sortie anticipée) et
mémorise sa valeur à chaque calage ; `_saut_offset_max()` rend `(écart entre calages
consécutifs, déplacement réel sur l'intervalle)` et le verdict terminal a **deux
sorties** : WARNING inchangé au-delà de `SAUT_OFFSET_ECH` de déplacement réel, **INFO**
« AEC sans objet — aucun écho à annuler » sinon (on cesse de traiter dans les deux cas :
le micro brut *est* le bon résultat sans écho, et renoncer rend le GIL). Rejoué sur les
données réelles : 0 et 50 ms de déplacement contre 771 et 1200 ms d'écart entre calages.
⚠️ L'ancien test de bout en bout poussait des tranches de **longueurs égales** tout en
attendant « flux non synchronisables » : il validait la confusion qu'on corrige — même
famille de piège que les tests d'ordre de menu du 2026-08-24, verts sur un item mort.
Réécrit en 2 tests qui figent les 2 terrains (longueurs égales → INFO ; tranches micro
amputées → WARNING), + 1 test que l'offset continue d'être mesuré après l'abandon (sans
quoi un `recalibrer()` en cours de session repartirait sur un cumul figé). ⚠️ La branche
« flux non synchronisables » n'a **aucun cas terrain confirmé** : ses 2 seules
occurrences sont celles du 27/08, et le cas du 25/08 qui l'avait motivée est sorti par
l'ancienne branche « casque recommandé » — l'instrumentation des durées livrées
n'existait pas encore ce jour-là, et l'utilisatrice portait déjà un casque. **Non
livré à Alix** : son poste tourne `1cbbd5d`, le correctif attend le prochain build
Windows (cosmétique — ses CR sortent correctement).

Après les assistants de configuration rendus lisibles (2026-09-02, **validé
manuellement** par Sylvain) : **1636 passed, 0 échec** sur `main` en environnement
complet (1625 avant, +11 tests) — 1629 passed en clone partiel, avec les 2 échecs
d'environnement habituels (helper Swift non compilé, audio canonique du benchmark). Deux défauts d'affordance sur les assistants guidés (diarization docs/13,
clé API Mistral docs/42 §9.4), plus un troisième trouvé en regardant le rendu :

1. **Le bouton « Créer un compte » ne se voyait pas comme cliquable** — il était
   construit en `QPushButton` **sans `objectName`**, or `theme.qss` ne donne fond et
   bordure qu'aux boutons nommés (`#primary`/`#secondary`/…) : la règle nue ne pose que
   police et rayon, donc il se peignait en gras noir sur blanc, indiscernable d'un
   paragraphe. C'étaient les 2 seuls `QPushButton` anonymes de tout `ui/`. Ils passent en
   `secondary` + icône Phosphor `arrow-square-out` (dire *qu'on quitte l'app pour le
   navigateur*, ce qu'aucune couleur ne porte ; le bleu reste à « Suivant », seule sortie
   de l'étape). Garde-fou : `test_assistant_etape.py` parcourt les pages **réelles** des
   deux assistants et refuse tout bouton de page sans nom de style ni icône.
2. **L'assistant Mistral n'avait aucune illustration** — et c'était structurel : tout le
   mécanisme (`_pixmap_svg`, `_illustration`) vivait *dans* `assistant_diarization.py`.
   Extrait dans `ui/assistant_etape.py` (maquette, titre, bouton de lien, fabrique
   `page_etape`), qui dédoublonne au passage les deux `_page()` identiques. 4 maquettes
   `mistral_etape_1..4.svg` dans le style des 5 existantes — schématiques et portant les
   **libellés exacts à chercher sur la vraie page** (« Create new key ») plutôt que
   fidèles au pixel : ce sont des UI tierces qui bougent, une maquette approximative
   reste utile après un redesign, une capture fidèle devient trompeuse. Carte passée de
   460 à 520 px comme la diarization — une maquette rendue à 460 ne tient pas dans les
   416 px utiles d'une carte de 460 (`CarteFlottante` retire 22 px de chaque côté).
3. **La maquette de la dernière page mentait** (préexistant côté diarization) : elle
   affirmait « Diarization activée » / « Connexion réussie » **pendant** le
   téléchargement ou le test, et restait affichée après un **échec**, au-dessus du
   libellé qui disait le contraire. Une maquette d'arrivée n'est plus révélée qu'au
   succès ; sa place restant prise par la page la plus haute de la pile, un ressort de
   centrage évite que l'attente ne montre une barre de progression seule en haut du
   vide. ⚠️ `test_chaque_etape_a_son_illustration` ne pouvait pas voir ce défaut : il
   vérifie qu'un `QLabel` porte un pixmap, jamais qu'il est **visible** — les 3 tests
   ajoutés portent sur `isVisibleTo` dans les 3 états (attente, succès, échec).

⚠️ Méthode qui a sorti les points 3 et le dégradé de la marque Mistral (15 tuiles
fusionnées en un aplat faute de jours) : **rendre les écrans offscreen et les regarder**
(`QT_QPA_PLATFORM=offscreen`, `carte.grab().save(...)`), pas relire le code. Les deux
sont invisibles à la lecture.

Après le muxer `segment` du ffmpeg embarqué (docs/42 §10.4, docs/16 §5.5, 2026-09-02) :
**1639 passed, 0 échec** en environnement complet — helper Swift compilé et `packaging/vendor/ffmpeg` construit, donc sans les 2 échecs d'environnement habituels (1636 avant, +3 tests). Déclencheur terrain : une réunion
de **1 h 52** dont le CR a été perdu — envoi entier → **503** → repli découpage (câblé la
semaine précédente, §10.1) → `exit 8`. Le build minimal `--disable-everything` n'activait
pas le muxer **`segment`**, donc ffmpeg ne reconnaissait pas `-segment_time` : le repli
était **cassé depuis toujours dans l'app livrée** et n'avait jamais tiré sur macOS.
**macOS seul touché** — Windows embarque un build BtbN complet, Linux dépend du ffmpeg
système. Corrigé dans `build_ffmpeg.sh` (muxer ajouté, exigé par `valider_binaire` avec
`return 1` → reconstruction, commande exacte du repli rejouée par le build) ; vérifié sur
le fichier réel (9 segments, le 1ᵉʳ à 840,0 s décodées). ⚠️ Nouveauté côté tests :
`tests/test_build.py` interroge désormais le **binaire réellement livré** sur les muxers et
filtres qu'utilise le code, et exécute `decouper_piste` dessus — les **deux** régressions de
cette famille (`aselect`/`asetpts` le 2026-08-18, `segment` ici) étaient invisibles à
`make test`. ⚠️ Le DMG produit ce soir-là s'appelle `…+20260902.ba0e150` alors qu'il porte
déjà le correctif, non committé à ce moment-là.

Après la transcription distante seule au raccourci ⌘T / Ctrl+T (docs/42 §4.2, 2026-09-03) :
**1677 passed, 0 échec** en environnement complet (1639 avant, +38 tests), en 2 commits verts
**indépendamment** (1657 sur le premier, vérifié en mettant la couche vue de côté).
Nouveau point d'entrée `pipeline.transcrire_reunion()` — même étape Voxtral que le repli du
CR, la chaîne s'arrête après l'écriture du transcript (récupérer le texte sans dépenser un
appel de rédaction). Trois décisions structurantes :

1. **Un seul gestionnaire pour les deux tâches.** `GestionnaireCRMistral` gagne
   `lancer_transcription()` et un discriminant `tache` : les deux tâches réécrivant
   `transcription.md`, un second gestionnaire les aurait laissées tourner en parallèle sur
   la même réunion (deux uploads, deux écritures). Partager `_job_en_cours` rend l'exclusion
   **structurelle** au lieu d'une vérification à ne pas oublier au point d'appel. Paire de
   signaux dédiée (`transcription_terminee`/`transcription_echouee`) plutôt qu'un 3ᵉ
   argument sur `termine` — résultats et fichiers à ouvrir différents, connexions existantes
   intactes.
2. **`locuteurs.md` est supprimé** quand la transcription est remplacée : `_lire_transcript_local`
   lui donne la **priorité**, donc le garder ferait rédiger le prochain CR sur le texte
   remplacé, silencieusement. La confirmation de remplacement l'annonce.
3. **Un seul `QKeySequence("Ctrl+T")` couvre les deux OS** (Qt traduit `Ctrl` → ⌘ sur macOS),
   en contexte **`WidgetShortcut`** comme le Suppr voisin : l'app n'a qu'une fenêtre dont
   Préférences et Journal sont des *pages*, un contexte applicatif capterait tout. Sélection
   multiple **refusée explicitement** (un seul job Mistral, pas de file) ; la ligne « en
   cours » compte pour 0 (sentinelle `Path()`, docs/43). L'association BlueMind n'est **pas**
   proposée ici, contrairement au flux CR — arbitrage assumé pour garder un geste court.

⚠️ **Défaut évité de justesse** : `ArbitreEtatVisuel.suivre_gestionnaire` ne câblait que
`termine`/`echoue` — la nouvelle paire aurait allumé l'icône de tray en orange **sans jamais
l'éteindre**, jusqu'à la fin de la session et sans aucune erreur. Les paires sont désormais
déclarées dans `PAIRES_FIN` et toutes câblées, et un test parcourt les **vraies** classes de
gestionnaires pour refuser tout signal de fin non déclaré. ⚠️ Les deux garde-fous ont été
vérifiés par **régression simulée** : amputer `PAIRES_FIN` fait échouer les 3 tests
d'arbitre, et retirer `activated.connect` fait échouer les 3 tests d'**effet** du raccourci
tandis que les 2 tests de simple présence restent verts — c'est pourquoi les tests d'effet
existent (cf. les items de menu morts du 2026-08-24). Menu ⋯ rendu offscreen et regardé.
**Premier usage réel le 2026-09-07, chez Alix : échec** — cf. § suivant. Le raccourci et
le pipeline ont bien fonctionné ; c'est le repli découpage qui a cédé, sur du code
antérieur et commun au CR.

Après le correctif du cumul de `usage` (docs/42 §10.5, 2026-09-07) : **1681 passed,
0 échec** en environnement complet (1677 avant, +4 tests). Diagnostic terrain (build
`4d967e7`, poste Windows) : une réunion de **2 h**, transcription distante seule,
429 sur l'envoi entier → repli découpage → tous les segments transcrits **et facturés**
→ `TypeError: unsupported operand type(s) for +: 'int' and 'dict'`, transcription
perdue. Cause **mesurée sur l'API réelle** le jour même : `usage` n'est pas un plat de
nombres — Voxtral y renvoie `prompt_tokens_details` (sous-dictionnaire) et
`service_tier` (chaîne), or `_transcrire_decoupe` faisait `usage_total.get(cle, 0) +
valeur`. ⚠️ **La forme de `usage` dépend de la DURÉE envoyée, bascule franche à 30 s** (mesuré en
faisant varier un sinus synthétique, même clé/modèle/requête) : **< 30 s** → `usage` porte
`prompt_tokens_details` (dict) + `service_tier` (str) — **plante** ; **≥ 30 s** → forme
aplatie avec `request_count`, Mistral découpant lui-même en interne et renvoyant un usage
agrégé — passe. Donc le déclencheur est le **dernier segment** du découpage : `L mod 840 <
30`, soit une fenêtre de **~3,6 % des pistes**. Alix : `moi.opus` = 5061,98 s = 6×840 +
**21,98 s** → ❌. Sylvain, même commit `4d967e7` le même jour : ~5563 s = 6×840 + 523 s →
✅ à 11:37, 16:11 **et 17:14**. Le chronométrage colle (7 segments à ~6 s + une attente de
20 s = les 74 s entre 16:24:14 et 16:25:28). ⚠️ **Hypothèse fausse écartée en cours de
route** : « déploiement serveur entre 16:11 et 16:25 », cohérente avec les 3 points connus
alors et réfutée par le découpage réussi de 17:14 — c'est le passage à une mesure
**paramétrique** (varier la durée) et non ponctuelle qui a sorti la règle. Ce n'est donc
pas « le problème de Alix » : tout poste non corrigé perd sa transcription en tombant
dans la fenêtre, et rien dans les logs ne le voit venir (`usage` n'est journalisé nulle
part). ⚠️ `TranscriptionMistral.usage` **n'a aucun
consommateur** dans l'app (§11 de docs/42 interdit toute notion de coût) : 2 h de réunion
perdues pour agréger une valeur que rien n'affiche — d'où un `_cumuler_usage` qui
privilégie la robustesse (somme les nombres, descend dans les sous-dictionnaires, recopie
tout autre type tel quel). ⚠️ Invisible à la suite : les 6 tests du repli découpage
mockent leurs payloads **sans clé `usage`**, donc la boucle de cumul ne tournait jamais —
le test de régression rejoue le relevé réel et échoue, sans le correctif, avec le message
**exact** du terrain (régression simulée vérifiée). Deuxième volet : `_WorkerCRMistral`
n'émettait que `str(exc)`, le diagnostic ne livrait donc qu'une ligne sans provenance ;
il journalise maintenant la **trace** pour tout ce qui n'est pas une `ErreurMistral`.
**Non livré à Alix** — son poste tourne `4d967e7`, le correctif attend le prochain build
Windows ; en attendant, relancer plus tard suffit (sans 429, l'envoi entier ne touche
jamais ce code).

Après la compaction des silences réparée au-delà de 100 plages (docs/42 §10.6,
2026-09-08) : **1697 passed**, +20 tests, en 2 commits verts indépendamment (1686 sur le
premier), avec les 2 échecs d'environnement habituels (helper Swift non compilé, audio
canonique du benchmark). Déclencheur : la compaction sortait en **244** sur les deux
tentatives de CR du 2026-09-07, donc la piste système partait entière (5 563 s au lieu de
2 508 s), remplissait la fenêtre de quota Mistral et exposait le poste au 429 → repli
découpage → au défaut de cumul de `usage` ci-dessus. Cause **mesurée sur le binaire
livré** : `av_expr_parse` (`libavutil/eval.c`) analyse `a+b+c` **par récursion, un niveau
par terme**, et s'arrête à `STACK_SIZE` — **100 termes passent, 101 échoue**, exactement
(dichotomie). Or `MAX_PLAGES` en autorise **120** : le défaut était **permanent**, et sur
les **3 OS** (la limite vit dans `libavutil`, pas dans les options de compilation — ce
n'est donc PAS la famille « composant absent du build minimal » de docs/16 §5.5, dont
`aselect`/`asetpts` sont exigés depuis le 2026-08-18). `244` = `AVERROR(ENOMEM)` replié
sur un octet non signé. ⚠️ **Deux hypothèses plausibles écartées par la mesure** : la
longueur de la ligne de commande (3 380 caractères, loin d'`ARG_MAX` — c'est pourtant ce
risque qu'invoquait le commentaire de `MAX_PLAGES`) et un filtre manquant ; ni
`-filter_script` ni un plafonnement des plages n'auraient traité la vraie cause.
Correctif : `expression_selection` groupe les termes par parenthèses de 25 (profondeur
`n/25 + 25`, soit 31 niveaux au pire cas ; groupement neutre — chaque `between` vaut 0 ou
1, l'addition est associative). Rejoué sur le fichier réel : 5 563 s → 2 508 s, durée
exacte. ⚠️ **Invisible à `make test`**, 3ᵉ fois dans cette famille : les tests de
`compacter_piste` mockent `subprocess.run`, l'expression n'était donc jamais analysée par
ffmpeg — `tests/test_build.py` l'exerce désormais à 120 plages sur le **binaire livré**,
avec un **témoin** exigeant que la chaîne plate sorte bien en 244 (s'il devient vert, la
limite a bougé et le premier test passerait pour de mauvaises raisons), et
`profondeur_expression` est **dérivée de l'expression réellement produite**, jamais d'une
formule parallèle qui resterait verte si le groupement disparaissait (piège de la colonne
d'actions du 2026-08-24). Second volet, `core/ffmpeg.py` (nouveau) : **le stderr de ffmpeg
n'arrivait jamais dans le log** — `CalledProcessError` ne porte que la commande et le code,
et les codes de ffmpeg sont des `AVERROR` illisibles tels quels (8 en §10.4, 234 au piège
des filtres, 244 ici), si bien que **les trois pannes ont été instruites en rejouant la
commande à la main**. `executer()` lève `ErreurFfmpeg` avec le code, les **dernières**
lignes de stderr et la commande, tout tronqué à 200 caractères par ligne et par argument
(ffmpeg réémet les 3 ko d'expression fautive, et le log est rotatif) ; aucun argument
implicite, la commande du message reste rejouable telle quelle. Câblé sur les **3** sites
(`silences.py`, `decoupage.py`, `core/audio.py`) — personne ne rattrapait
`CalledProcessError`, le changement de type est sans effet de bord. ⚠️ `tests/test_ffmpeg.py`
couvre le lanceur **et les 3 appelants réels** : le lanceur seul ne prouverait rien, c'est
chaque site d'appel qui était muet. **Non livré** : attend le prochain build macOS.

Après le retrait des modèles de CR non servis (docs/42 §10.7, 2026-09-08) : **1720 passed**,
+23 tests, en 2 commits verts indépendamment (1711 sur le premier), 2 échecs
d'environnement habituels. Déclencheur : « Quota dépassé (429) sur v1/chat/completions »
chez Alix (build `e170d50`, correctif du cumul de `usage` déjà embarqué), **4 fois en
1 h 35** sur une réunion de 25 min dont toute la chaîne amont marchait (compaction 23 et
27 plages, deux pistes transcrites par Voxtral) ; dernier CR réussi chez elle le
2026-08-27. **Mesuré sur l'API réelle et reproduit avec la clé de Sylvain** — ce n'est
donc ni son poste ni sa clé : `mistral-medium-latest` et `mistral-small-latest`, **les
deux seuls choix du sélecteur**, répondent 429 avec
`x-ratelimit-limit-req-minute: **0**` ; `mistral-large` reste en 403 `tier_not_allowed`
(migration v5) ; `magistral-medium-latest` est un **alias** de medium ; seuls les
`ministral-*` répondent (30/188/750 req/min). **L'allocation n'est pas épuisée, elle est
nulle** — aucune attente ne peut aboutir, et Alix n'avait aucun réglage qui marche.
⚠️ **Trois pistes plausibles écartées par la mesure** : fenêtre tokens/minute saturée par
les appels Voxtral qui précèdent (réfutée par les tentatives 1 h 30 plus tard, sans
transcription), taille du transcript (contexte **256 k des deux côtés** d'après
`/v1/models` — la longueur des réunions n'entre pas en compte), et repli sur
`magistral-medium` (alias). Livré en 2 volets : **migration config v6** — `MODELES_CR` /
`MODELE_CR_DEFAUT` dans `core/config.py`, **importés** par le sélecteur et jamais
recopiés (une liste divergente proposerait un modèle que la migration annulerait en
silence, un test compare les deux), défaut `ministral-14b-latest`, et comme la valeur
fautive ne peut pas être énumérée on migre **tout ce qui n'est pas dans la liste**, choix
explicite compris ; et **le client Mistral** — la branche 429 **jetait le corps de la
réponse** alors que les branches 401/403 et 400/422 le joignent (⚠️ **même angle mort que
le stderr de ffmpeg ci-dessus**, corrigé le même jour : le diagnostic a de nouveau
demandé de rejouer l'appel à la main), et un plafond à 0 déclenche désormais un refus
**immédiat** au lieu de 20 + 40 + 60 s d'attente suivies d'un « Quota dépassé » qui envoie
l'utilisateur attendre un déblocage qui ne viendra jamais.
⚠️ `ErreurModeleIndisponibleMistral` est **sœur** de `ErreurQuotaMistral`, surtout pas une
sous-classe : `transcription.py` rattrape le quota pour découper, or découper une piste
dont le modèle est refusé multiplierait le refus par le nombre de segments — figé par un
test d'**effet** côté transcription, pas par une vérification de hiérarchie de classes
(régression simulée vérifiée). ⚠️ Les tests de la migration v5 passaient par `Config`,
donc la v6 écrasait leur résultat : ils appellent désormais la v5 **seule**, sans quoi ils
seraient restés verts en ne prouvant plus rien. ⚠️ **Ce que le choix coûte** :
`ministral-14b` est un modèle *small / edge* (14 B, **sans** capacité `reasoning`) là où
`mistral-medium` est un milieu de gamme « frontier » — à surveiller sur les 3 points qui
comptent pour un CR (tenir un prompt long, ne pas inventer de participant — l'écueil de
docs/46 —, synthétiser plutôt que paraphraser). Le vrai remède reste un abonnement
supérieur. **Contournement sans build** : `"mistral_modele_cr": "ministral-14b-latest"`
dans `config.json`, app fermée.

Après la journalisation du **succès** des intercos (2026-09-11) : **1734 passed, 0 échec**
en environnement complet (1724 avant, +10 tests), en 2 commits verts indépendamment.
Déclencheur : le diagnostic de Cyril (build `f77f407`), « la connexion BlueMind ne
marche pas ». Verdict réel : elle marchait — 2 lignes d'URL saisie **sans `/api`** à
10:37 et 10:38, corrigée avant son redémarrage de 10:43:58, puis 2 flux CR qui forcent
chacun une resync (`attendre_sync`) **sans la moindre erreur**. Mais ce verdict n'a pu
être rendu que par un raisonnement **en creux** : une sync réussie ne journalisait
**rien** (`_sur_terminee` n'émettait qu'un signal), donc le log ne permettait que de
constater l'absence d'échec — jamais d'affirmer que l'interco fonctionne. ⚠️ **Même
angle mort que le stderr de ffmpeg (§10.6) et que le corps du 429 Mistral (§10.7)**, tous
deux corrigés 3 jours plus tôt : la famille, ce sont les chemins où l'information existe
au moment des faits et n'est simplement jamais écrite. 3 trous bouchés :

1. **Sync BlueMind réussie** → `INFO Sync BlueMind réussie — N événement(s) dans la
   fenêtre`, dans `_sur_terminee`, symétrique du WARNING de `_sur_erreur`. ⚠️ `N` est le
   contenu de la **fenêtre entière** (−90 j/+30 j), pas un delta : la resync est toujours
   complète depuis docs/40 §5.2, le nom du signal (`ajoutes_ou_maj`) est un reliquat du
   chemin incrémental retiré. Volume ~100 lignes/jour au timer de 15 min, contre 5 Mo × 6
   de rotation — négligeable (le log de Cyril fait 100 ko pour 68 h).
2. **« Tester la connexion » BlueMind** — son verdict ne vivait que dans le label des
   Préférences, effacé à la fermeture de la fenêtre : rien ne disait si le bouton avait
   seulement été cliqué. INFO/WARNING dans le **worker** (les 2 branches au même endroit,
   impossible de diverger de ce qui est affiché). L'URL est journalisée **telle que
   saisie**, dans les 2 branches — c'est le champ qui était faux, et l'export de
   diagnostic la transmet déjà en clair. Ce worker n'avait **aucun test** : nouveau
   `test_testeur_connexion_bluemind.py` (4).
3. **« Tester la connexion » Mistral** — idem, plus le **nombre de modèles servis**, tiré
   du corps de `v1/models` déjà reçu puis jeté : c'est exactement la mesure qui a démêlé
   §10.7 (clé valide, plafonds nuls). ⚠️ D'où un `_nombre_de_modeles` **défensif** —
   sans la garde, un 200 au corps illisible remonte dans le `except Exception` et
   s'affiche à l'utilisateur comme une **connexion en échec** (régression simulée
   vérifiée, c'est l'objet d'un test dédié).

⚠️ Chaque ligne de succès est doublée d'une **contre-épreuve** (« un échec ne journalise
aucun succès ») : c'est elle qui rend la ligne exploitable en diagnostic — la lire doit
suffire à conclure, sans avoir à vérifier qu'aucun WARNING ne suit. Et 2 tests figent
qu'aucun secret ne fuit par ces logs (token BlueMind, clé Mistral) — ils ne voyagent
qu'en en-tête et les messages d'erreur des 2 clients ne reprennent que des corps de
réponse serveur. Les 10 tests ont été validés par **régression simulée**.

Après PortAudio recompilé avec le correctif amont #1175 (docs/16 §5.7, 2026-10-23,
**validé manuellement** par Sylvain le jour même sur le DMG CI `632e5f9` — pastille
orange éteinte après la réunion) : **1871 passed, 0 échec** en environnement complet,
+11 tests ; CI verte sur les 3 OS. Terrain : sur le Mac de
Sylvain (build `445b0b4`), la **pastille orange du micro est restée allumée** après la fin
d'une réunion, puis l'app s'est figée en quittant. Cause : un **interblocage AB-BA dans
PortAudio 19.7.0** (la dylib de sounddevice). Le listener `IsRunning` appelle
`AudioUnitGetProperty` sur le thread d'E/S du HAL pendant que `Pa_StopStream` tient le
mutex de l'AudioUnit ([PortAudio#1174](https://github.com/PortAudio/portaudio/issues/1174),
aussi sur macOS 26 : non lié à macOS 27). Correctif fusionné en amont le jour même
(#1175), **dans aucune release** : `packaging/build_portaudio.sh` compile v19.7.0 + ce
seul patch (`packaging/patches/`) et le spec **substitue** la dylib du hook sounddevice
(exactement une substitution exigée, résultat revérifié par `build_app.sh`). ⚠️ **Mesuré
avant/après** avec le repro de l'issue, plus une variante entrée seule fidèle à notre
micro : dylib livrée bloquée en **265** (duplex) et **327** (entrée) cycles, témoin compilé
par nous sans patch bloqué en **299**, version patchée **3 000 et 2 000 cycles sans
blocage**. Les piles bloquées portaient les **mêmes décalages** que le process figé du
terrain. ⚠️ Le défaut pouvait figer l'**UI** à la réunion suivante :
`_attendre_fermeture_differee` rendait la main au bout de 2 s, puis le refresh
`sd._terminate()` (un `Pa_Terminate`) aurait buté sur le même verrou. Filet ajouté :
refresh **sauté** si l'ancien flux reste bloqué, et WARNING « Flux micro toujours pas
fermé » 5 s après l'arrêt (le thread bloqué ne peut rien journaliser lui-même). Tests
d'effet vérifiés par régression simulée. **macOS seul** (code `pa_mac_core.c`) ; en dev
(`make run`), la dylib non corrigée de sounddevice tourne toujours. Master amont écarté
(265 commits, rien d'utile pour nous hors #1175, cf. §5.7).

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

## État des phases (au 2026-10-23)

| Phase | Statut |
|-------|--------|
| 0 — Socle + archi | ✅ |
| 0.5 — Spike audio système (SCK retenu) | ✅ |
| 1→3 — Dictée, Réunion, Journal macOS | ✅ |
| **4 — Packaging macOS** | ✅ **TERMINÉ** — `.app` + `.dmg` signés par le certificat local stable « debriefMeet Local » (docs/16), utilisés en réel depuis juillet 2026 (permissions TCC conservées d'un build à l'autre). Depuis le 2026-10-21 le DMG sort aussi de la **CI** avec la **même identité** (secrets du dépôt, empreinte vérifiée — docs/52 §6, §9 run 9). Notarisation Apple hors périmètre : un `.dmg` téléchargé passe par « Ouvrir quand même » (README). |
| **4b — Modèle large-v3-turbo** | ✅ TERMINÉ (2026-06-30, turbo = modèle par défaut) |
| **5 — Spike backends Windows** | ✅ **CLOS** — matrice Intel mesurée (docs/18 §14), décision v1 = faster-whisper CPU ; le run AMD n'a jamais eu lieu et l'accélération iGPU (OpenVINO/DirectML/Vulkan) reste hors v1 |
| **5 — Portage Windows** | ✅ **TERMINÉ** — docs/30→35 + 37 : setup Inno Setup, fumée SSH automatisée, ffmpeg embarqué (docs/41), export de diagnostic (docs/31). **Livré et utilisé en réel** sur 2 postes Windows (builds `1cbbd5d` 2026-08-26, `e170d50`, `f77f407`) ; diagnostics terrain analysés (docs/42 §10.5-10.7, docs/44 §8, docs/48 §8.6). Build natif sur la VM (`scripts/build_app_windows_vm.sh`) **ou** sur GitHub Actions (docs/52). Reste : validation interactive de `usPostUninstall` (docs/37 §7). |
| **Correctifs fuites CoreAudio (docs/23)** | ✅ TERMINÉ (2026-07-02, 530 passed) |
| **Robustesse micro hot-plug (docs/25)** | ✅ TERMINÉ (2026-07-02, 542 passed) |
| **Fix dictée/journal muets (docs/27)** | ✅ TERMINÉ (2026-07-02, 556 passed) |
| **Raccourcis globaux paramétrables (docs/28)** | ✅ TERMINÉ + validé manuellement (2026-07-02, 573 passed) |
| **Fix diarization pyannote 4.x (docs/29)** | ✅ TERMINÉ + validé manuellement (2026-07-02, 576 passed) — offline via `HF_HUB_OFFLINE`, `local_files_only` supprimé |
| **Fix crash QThread à l'arrêt (docs/26)** | ✅ TERMINÉ (2026-07-03, 589 passed) — registre workers MLX + kill forcé, helper `arreter_thread`/`proteger_thread` |
| **Interco BlueMind — calendrier, invités, notifications (docs/40)** | ✅ **TERMINÉ, validé en réel** — association, invités et notifications en usage quotidien ; **fix 2026-07-27** : réunions **récurrentes** invisibles à l'association (`_search` renvoie la série maître) → `core/bluemind/recurrence.py` (expansion `rrule`/`exdate`, DST-safe, `python-dateutil`), resync complète ; sync réussie et « Tester la connexion » journalisés depuis le 2026-09-11 (diagnostic Cyril : l'interco marchait, l'URL saisie manquait `/api`). cf. docs/40 §5.2 |
| **ffmpeg embarqué Windows — rétention Opus garantie (docs/41)** | ✅ TERMINÉ (2026-07-12, 938 passed Mac + 780 passed VM) — build+fumée réels validés, setup 159 Mo |
| **Interco Mistral — CR cloud adaptatif, transcription Voxtral (docs/42)** | ✅ **TERMINÉ**, fusionné dans `main` (2026-07-21), validé en réel. **2026-08-04** : association BlueMind proposée **avant** le CR (§4.1 — « Associer » renomme le dossier, le job part sur `dlg.chemin_md`). **2026-08-05** : bouton dédié « Générer le CR ▾ » + « Copier le CR », menu ⋯ exhaustif, confirmation avant remplacement. **2026-09-03** : transcription distante seule au raccourci ⌘T/Ctrl+T (§4.2). **Pannes terrain corrigées** : muxer `segment` absent du ffmpeg macOS (§10.4), cumul de `usage` non typé (§10.5), compaction cassée > 100 plages + stderr ffmpeg journalisé (§10.6), modèles `mistral-*` à plafond nul → `ministral-*` par défaut, migration config v6 (§10.7). |
| **Édition lite Windows (docs/44)** | ✅ **REMPLACÉE** par le mode de transcription unifié (docs/45) — plus de build lite depuis le 2026-08-04. Acquis conservés : export de diagnostic avec secrets caviardés, `tzdata` sous Windows, tempête de reconnexions micro corrigée. |
| **Mode de transcription unifié — un seul build, réglage Préférences (docs/45)** | ✅ **TERMINÉ** — clé `mode_transcription` (`distant` par défaut, `local` = Whisper embarqué + diarization + Dictée/Journal), figée au démarrage, écran de bienvenue au 1ᵉʳ lancement, redémarrage proposé au changement. Builds unifiés livrés sur les 3 OS depuis août 2026, transition réelle faite sur les postes lite. |
| **Réorganisation 1 dossier/réunion (docs/43)** | ✅ **TERMINÉ** — fusionné dans `main` et **validé manuellement** (2026-07-27, 1099 passed). Migration à plat jouée une fois puis code retiré ; secondes obligatoires dans le nom de dossier (§7). ⚠️ Un rollback avant `1ed3b17` rendrait les réunions invisibles. **Correctif du 2026-08-28** : renommage pendant un **job de fond** → `resoudre_chemin_reunion` (re-résolution par préfixe horodaté avant chaque écriture), docs/43 §6.4 et §16. |
| **Lexique de corrections (docs/46)** | ✅ **TERMINÉ** — fusionné le 2026-08-05, validé en réel (1ᵉʳ CR : participant inventé → chapeau reformulé et bloc inséré avant « Voici la transcription », correctif du 2026-08-06). **Tableau par défaut vierge depuis le 2026-10-20** (publication GitHub). |
| **AEC continue + dédoublonnage des pistes (docs/48)** | 🔄 **livré, validation terrain en cours** — recalage sur inefficacité, dédoublonnage par inclusion directionnelle (seuil 0,75), comblement des trous micro à la source ; garde-fou « flux non synchronisables » recalé sur une preuve (§8.6, 2026-08-28). Reste : compensation d'offset (§5). |
| **Dialogues défilants, listes de participants (docs/50)** | ✅ TERMINÉ (2026-08-20, 1456 passed) — reste les vérifications manuelles §4 |
| **Copie du CR mise en forme (docs/51)** | ✅ TERMINÉ, validé manuellement (2026-08-26, 1581 passed) — collage riche Pipedrive/webmail, prompt Pipedrive retiré (migration v4) |
| **6 — Portage Linux Ubuntu 26.04 (docs/49)** | ✅ **TERMINÉ** — mode distant seul, `.deb` amd64 (`Depends: ffmpeg…`), validé chez l'utilisateur le 2026-08-13, 4 défauts d'intégration GNOME corrigés (icône de tray, clic, contour, « Quitter »). Build sur le LXC (`scripts/build_app_linux_lxc.sh`) **ou** sur GitHub Actions. Reste (hors v1) : raccourcis globaux (portail XDG), mode local. |
| **Publication GitHub + anonymisation (2026-10-20)** | ✅ **TERMINÉ** — dépôt `sylvaing/debriefMeet` (privé), historique réécrit par `git filter-repo` (noms réels → pseudonymes, clients, lexique, mot de passe VM, maquettes), vérifié à zéro résidu sur blobs **et** messages ; historique privé d'origine archivé hors GitHub. Cf. § « Confidentialité du dépôt ». |
| **Mise à jour automatique (docs/53)** | ✅ **TERMINÉ** (2026-10-23) — manifeste de Release signé ed25519 (secret CI `MAJ_CLE_PRIVEE_PEM`, clé publique embarquée, vérifiée par la CI avec la fonction de l'app), vérification 30 s après le lancement puis toutes les 24 h (opt-out Préférences › Général), badge toolbar + notification tray, clic ⇒ téléchargement SHA256 puis handoff **après `app.exec()`** (Windows : `.cmd` qui attend la mort du PID puis setup `/SILENT /AUTOUPDATE=1` ; macOS : `/bin/sh` qui remplace le bundle par deux `mv` avec retour arrière ; Linux : page de release). Bump **0.4.0**, assets de Release renommés sans `+date.hash`, zip macOS publié. **Release officielle `v0.4.0` publiée le 2026-10-23** (`f4269d4`, manifeste `latest` signé et vérifié — dernière réinstallation manuelle). ⚠️ **Une rc porte son propre numéro** : tag `vX.Y.Z-rcN` ⇔ `__version__ = "X.Y.ZrcN"`, imposé par `packaging/verifier_tag_version.py` — la `v0.4.0-rc1`, construite en `"0.4.0"`, se croyait finale et ne se voyait jamais proposer la `v0.4.0` ; traduction par OS : Inno/Info.plist en entiers, Debian en `~rcN` (docs/53 §4). |
| **CI GitHub Actions (docs/52)** | ✅ **TERMINÉ** (2026-10-21) — `build.yml` : Windows `.exe`, Linux `.deb` (conteneur `ubuntu:26.04`) et macOS `.dmg` (identité stable via secrets) au tag `v*` ou à la demande (`gh workflow run build.yml -f macos=true`), Release GitHub sur tag, gates pytest bloquantes. Pièges mesurés : `$GITHUB_ENV` ne vaut que pour les steps suivants, RC=139 toléré au teardown, BtbN purge ses zips (miroir `outils-build`), PySide6 borné `<6.12`. Segfault Linux intermittent vu une fois (`test_assistant_mistral.py`), à surveiller. |

## Packaging macOS (Phase 4) — pièges

- **Certificat local stable** `« debriefMeet Local »` (créé par `packaging/creer_certificat.sh`) — doit signer identiquement l'app ET le helper Swift à chaque build, sinon les permissions TCC (Micro + Enregistrement de l'écran) sont perdues.
- Vérifier : `codesign -dv dist/debriefMeet.app` — même Authority entre deux builds.
- Bundle id : `com.sylvaingarcia.debriefmeet` (aligné partout, y compris `demarrage_auto.py`, depuis 2026-07-02).
- **Pas d'auto-update en v1** — MAJ = re-téléchargement manuel du `.dmg`.
- La config (`platformdirs`) et les transcriptions (`~/Documents/debriefMeet`) vivent hors du bundle → survivent au remplacement.
- **ffmpeg embarqué (LGPL, `packaging/build_ffmpeg.sh`)** : à compiler une fois avant `build_app.sh` (binaire non versionné, `packaging/vendor/`). Pièges configure : les demuxers/muxers PCM bruts s'activent sous leur nom **interne** (`pcm_f32le`, `pcm_s16le`), pas le nom court de `ffmpeg -demuxers` (`f32le`/`s16le`) ; `--disable-postproc` n'existe plus en ffmpeg 8.1.x ; et **la liste des filtres se périme** — `aselect,asetpts` manquaient (ajoutés le 2026-08-18), donc la compaction des silences Mistral échouait **dans l'app livrée uniquement**, jamais en dev où répond le ffmpeg Homebrew complet. Toute nouvelle invocation de ffmpeg dans le code oblige à revisiter `--enable-*` ; `valider_binaire` exige désormais ces filtres (binaire trop ancien → reconstruit) et le build rejoue les 2 passes de `compacter_piste`. **Même piège une 2ᵉ fois le 2026-09-02** : le **muxer `segment`** manquait → le repli découpage Mistral était cassé dans l'app livrée depuis toujours (jamais déclenché sur macOS avant le repli 5xx de docs/42 §10.1) ; sans lui ffmpeg ne reconnaît même pas `-segment_time` et sort en **8** (« Unrecognized option »), ce qui ne ressemble pas à « composant absent ». macOS seul touché (Windows = build BtbN complet, Linux = ffmpeg système). Muxer ajouté + exigé par `valider_binaire` + commande exacte du repli rejouée dans le build ; et `tests/test_build.py` interroge maintenant le **binaire livré** sur les muxers/filtres utilisés par le code — les 2 régressions étaient invisibles à `make test`. ⚠️ **À ne pas confondre avec la famille voisine** : l'échec de compaction du 2026-09-07 (exit **244**) n'était PAS un composant absent mais la limite d'imbrication de l'évaluateur d'expressions de `libavutil` — il échouait donc aussi en dev, et sur les 3 OS. Le réflexe « ajouter un `--enable-*` » n'aurait rien réparé : docs/42 §10.6.
- **PortAudio recompilé (`packaging/build_portaudio.sh`, docs/16 §5.7)** : la dylib de
  sounddevice (v19.7.0) s'interbloque parfois à l'arrêt du micro (PortAudio#1174) ; le
  bundle embarque v19.7.0 + #1175, substituée par le spec. À retirer quand une release
  amont **et** sounddevice l'embarqueront. Vérifier dans le bundle : `strings
  …/_sounddevice_data/portaudio-binaries/libportaudio.dylib | grep PortAudio.CoreAudio.startStop`.
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
| Packaging macOS (§5.5 ffmpeg embarqué ; §5.7 PortAudio recompilé avec #1175) | `docs/16` |
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
| **Interco BlueMind (calendrier, invités, notifications) — ✅ terminé, validé en réel (usage quotidien) ; §5.2 = fix récurrences 2026-07-27 ; sync réussie et « Tester la connexion » journalisés depuis le 2026-09-11** | `docs/40` |
| ffmpeg embarqué Windows (rétention Opus garantie) | `docs/41` |
| **Interco Mistral (CR cloud adaptatif, transcription Voxtral) — ✅ terminé, validé manuellement, fusionné dans `main` ; §4.1 = association BlueMind proposée avant le CR ; §4.2 = transcription distante SEULE au raccourci ⌘T/Ctrl+T (2026-09-03) ; §10.4 = muxer `segment` absent du ffmpeg embarqué macOS ; §10.5 = cumul de `usage` non typé, repli découpage cassé sur les 3 OS (terrain 2026-09-07, corrigé) ; §10.6 = compaction cassée au-delà de 100 plages (expression `aselect` trop imbriquée, 3 OS) + stderr de ffmpeg enfin journalisé (`core/ffmpeg.py`) ; §10.7 = plus aucun modèle `mistral-*` servi en chat (429 à plafond NUL), sélecteur et défaut passés aux `ministral-*` (migration v6) + corps de la réponse 429 journalisé** | `docs/42` |
| **Réorganisation 1 dossier/réunion — ✅ terminé, validé manuellement, fusionné dans `main` (bilan §15 ; §6.4 et §16 = renommage pendant un job de fond, correctif du 2026-08-28)** | `docs/43` |
| Édition lite Windows — **obsolète**, remplacée par docs/45 (historique : décisions, pièges, terrain) | `docs/44` |
| **Mode de transcription unifié (un seul build, réglage distant/local) — ✅ terminé, builds unifiés livrés sur les 3 OS depuis août 2026** | `docs/45` |
| **Lexique de corrections (tableau « entendu → à écrire » injecté dans les prompts + biais Voxtral) — ✅ fusionné dans `main`, UI validée manuellement** | `docs/46` |
| Diarization Voxtral V2 en mode distant — **piste mesurée** (spike du 2026-10-23, §6 : `diarize=true` ⇒ `speaker_id` par segment, compatible `context_bias` ; `voxtral-mini-latest` = déjà la V2 ; net en réunion physique, à confirmer en visio ; étiquettes propres à chaque requête ⇒ incompatible en l'état avec le repli découpage) | `docs/47` |
| **CI GitHub Actions — builds Windows (.exe), Linux (.deb) et macOS (.dmg, sur tag ou `-f macos=true`, identité de signature via secrets) au tag `v*` ou à la demande (`gh workflow run build.yml`), Release GitHub automatique ; `make dmg` local inchangé** | `docs/52` |
| **Mise à jour automatique — ✅ release officielle `v0.4.0` publiée le 2026-10-23 ; une rc porte son propre numéro (`vX.Y.Z-rcN` ⇔ `X.Y.ZrcN`, §4) — manifeste signé ed25519 sur la Release, vérification quotidienne, badge + tray, handoff installeur Windows/macOS après `app.exec()`, Linux manuel ; pièges : `follow_redirects` httpx, clé par défaut liée à la définition, zombie vs `kill -0`** | `docs/53` |
| **Phase 6 — Portage Linux (Ubuntu 26.04 LTS) — ✅ terminé, validé chez l'utilisateur le 2026-08-13, fusionné dans `main` (journal du chantier ci-contre)** | docs/49, démarré le 2026-08-10 — v1 = mode **distant seul**, **sans raccourcis globaux** (Wayland), packaging **`.deb` amd64** avec `Depends: ffmpeg` (pas de ffmpeg embarqué). Cible : collègue BlueMind sur portable x86_64, en prod. **Faits** : LXC `192.168.1.32` provisionné (**Python système 3.14.4, sans PPA** — décision L7, la contrainte « PyInstaller ≠ 3.14 » a expiré ; Mac/Windows restent en 3.13, alignement séparé), **gate pytest VERTE : 1141 passed, 21 skipped, 0 échec** ; spike `spike/capture_monitor_linux/` (protocole guidé) ; adaptateurs `platform/linux/` (presse-papiers, démarrage auto `.desktop`), `_linux()` remplie ; retouches §5.5 (ffmpeg système en figé, logs DEBUG par défaut, infos système distro/session/PipeWire). Mac inchangé à **1351 passed**. **Spike TERMINÉ** (3 passages chez le collègue, 2026-08-12/13) : `.monitor` visibles **uniquement sous le hostapi PulseAudio**, `pactl get-default-sink` **nécessaire** pour choisir le bon, 48 kHz stéréo comme WASAPI. **Deux modes de panne opposés** — son parti ailleurs = zéros parfaits (indiscernables d'une réunion calme, détection `pactl`) ; **sink disparu = flux GELÉ**, `stream.active` toujours `True`, aucune exception (détection uniquement par absence de trames). D'où : surveillance `pactl` **+** chien de garde sur les trames + repli silence à hauteur du temps écoulé (sinon décalage inter-pistes = durée de la panne, docs/48). `platform/linux/capture_systeme_monitor.py` **écrit** (25 tests) : résolution par `pactl` sans repli aveugle, surveillance de la sortie par défaut, chien de garde sur les trames, repli silence à hauteur du temps écoulé (logs limités pour ne pas noyer le fichier rotatif). ⚠️ Il **ne rafraîchit jamais** la table PortAudio — `sd._terminate()` fermerait le flux micro en pleine réunion ; `micro_sounddevice.demarrer()` le fait juste avant, donc la table est fraîche à chaque début de réunion (une sortie apparue *pendant* reste invisible, limitation assumée identique au micro). **Packaging ✅ PREMIER BUILD RÉUSSI** (2026-08-13) : `debriefmeet_0.3.0+20260813.e5d38bd_amd64.deb`, **120 Mo**, via `scripts/build_app_linux_lxc.sh` (gate pytest bloquante incluse) — PyInstaller 6.22 sur Python 3.14 confirmé en réel. **Fumée verte** (`scripts/fumee_deb_lxc.sh`) : Depends (dont libportaudio2), install apt, `--version`, réinstall, purge. Extra `linux` = `livekit` seul (pas de faster-whisper dans le bundle v1). Gates après fusion avec `main` : **1403 passed** Mac (2 échecs d'env. habituels), **1186 passed, 0 échec** LXC. **Première panne terrain corrigée** (2026-08-13, §6.4) : fuite de descripteurs sqlite — `StoreCalendrier._connexion()` ne fermait jamais ses connexions (le `with` de sqlite3 = transaction seule) et les délégués de l'Historique l'interrogent à chaque frame de l'animation d'enregistrement → EMFILE en 35 s sur la limite Ubuntu de 1024 (invisible sur Mac, limite ~1 M). Contextmanager + close() en finally, test de régression sous `gc.disable()`. Nouveau build fumé : `debriefmeet_0.3.0+20260813.cd5620c_amd64.deb`. ✅ **VALIDÉ SUR LE TERRAIN le 2026-08-13** : le `.deb` corrigé fonctionne chez le collègue → branche `claude/linux-ubuntu-porting-plan-2cfbf9` **fusionnée dans `main`** et supprimée. **3 défauts d'intégration GNOME corrigés** (2026-08-14, §6.5) : icône de tray illisible (le « template » `setIsMask` est un mécanisme **macOS**, ignoré sous Linux → blanc plein sur bandeau sombre — surtout **ne pas** dériver ça de `colorScheme()`, le bandeau Ubuntu est noir même en thème clair) ; **aucune action au clic** (StatusNotifierItem n'appelle jamais `Activate` : `setContextMenu()` est obligatoire sous Linux, alors qu'il est proscrit sur macOS) ; fenêtre sans contour (le décorateur Wayland ne dessine pas d'ombre → liseré 1 px maison). **4ᵉ défaut de la même famille, corrigé le 2026-08-24** : « Quitter » inerte au tray, seul item construit en `QWidgetAction` (widget rouge maison) — DBusMenu ne transporte que libellé/icône/état, donc l'item s'affichait par son seul `setText()` et l'hôte l'activait via `triggered`, signal auquel rien n'était branché ; aucune autre porte de sortie (`setQuitOnLastWindowClosed(False)`), l'utilisateur devait tuer le process. Corrigé en `QAction` simple sous Linux + `triggered` branché dans les deux cas. ⚠️ Les 2 tests d'ordre du menu n'assertaient que le **libellé** : verts pendant tout le temps où l'item était mort — les nouveaux tests portent sur l'**effet** de l'activation (`QApplication.quit` espionné AVANT construction, `connect()` capturant le callable au câblage). `Depends` complétés : `libgtk-3-0t64`, `adwaita-icon-theme`. Gates : **1417 passed** Mac, **1193 passed** LXC. **Reste** (hors v1) : notice utilisateur, raccourcis globaux (portail XDG, L2), mode local (docs/49 §4.3). Ordre docs/49 §8. |
| **AEC inefficace sur le terrain + transcriptions en double — 🔄 livré, validation terrain en cours (reste : compensation d'offset §5)** (diagnostic mesuré du 2026-08-06 : décalage inter-pistes 300-700 ms variable par réunion + dérive ~125 ppm, calibration one-shot inadaptée, att −0,2/−1 dB partout ; livré : dédoublonnage à la fusion `_entrelaces`, `DELAI_MAX_MS` 600→1500 ms, ré-estimation périodique du délai + WARNING d'écho résiduel, log de l'offset d'ingestion ; reste : validation terrain §5 + compensation d'offset). **Rechute du 2026-08-18 (§8)** : le délai calé à la 1ʳᵉ tranche (383 ms, correct — l'AEC annulait −25/−40 dB les 11 premières minutes) a été périmé par un **saut de ~68 ms de l'offset inter-pistes** (la chaîne micro **perd des paquets d'échantillons** — pas une dérive d'horloge : 12 ppm mesurés sur les fichiers, §8.4 ; mécanisme candidat : callback PortAudio affamé par le GIL, buffer HAL débordé — la chaîne SCK, process séparé, est immune). Un saut qui met la référence en retard sur l'écho casse la causalité → 0 dB instantané (marge de lead 40 ms), et le suivi de dérive a mis 20 min à rattraper → 22 min de voix distante dans la piste micro, attribution inutilisable. Corrigé (3 volets complémentaires) : **comblement des trous à la source** dans le callback micro (discontinuité d'horodatage ADC → silence de même durée, seuil 20 ms/plafond 10 s, WARNING 1 ligne/tranche max, les 3 OS — l'offset ne peut plus sauter, moi.opus/systeme.opus restent alignés) ; `QUALITE_CORR_CALAGE = 25` pour bouger l'alignement (sous ~25 l'estimation de délai est du bruit, la détection d'écho résiduel garde 10) ; le WARNING d'inefficacité déclenche un **recalage complet** du délai (borné à `RECALIBRAGES_AUTO_MAX = 3`, budget neuf à chaque `demarrer()`/`recalibrer()`), et le dédoublonnage gagne un critère d'**inclusion en mots**, `autojunk=False`, **directionnel** (couverture du segment MICRO par le système — l'inverse jetterait la parole de l'utilisateur), seuil 0,75 calibré sur les 73 réunions du poste. ⚠️ Le seuil ne peut pas descendre : un doublon manqué fait 0,70 et un tour légitime 0,71. Trouvé au passage : `aselect`/`asetpts` absents du ffmpeg embarqué macOS → compaction des silences Mistral **cassée depuis toujours dans l'app livrée** (exit 234, envoi intégral), invisible en dev ; filtres ajoutés + exigés par la validation du binaire + les 2 passes rejouées dans le build ; **§8.6, 2026-08-28** : le garde-fou « flux non
synchronisables » accusait à tort une utilisatrice **en casque** — il exige désormais que
le déplacement RÉEL de l'offset (longueurs livrées) confirme le désaccord entre calages,
sinon c'est un INFO « AEC sans objet », et la branche WARNING reste sans cas terrain
confirmé) | `docs/48` |
| **Dialogues : défilement, suivi de fenêtre, listes de participants — ✅ IMPLÉMENTÉ (2026-08-20, 1456 passed, 0 échec ; reste les vérifications manuelles §4)** (déclencheur : un événement BlueMind à ~34 invités poussait le pied de page hors de l'écran — plus aucun bouton, parcours CR Mistral bloqué). Livré : corps **défilant** dans `DialogueGabarit` (en-tête et pied fixes) + hauteur de carte plafonnée — `AlignCenter` sert le `sizeHint` sans borner, seule la taille **maximale** plafonne ; overlay devenu **widget enfant** de la fenêtre hôte (suit déplacement et redimensionnement sans code de suivi, `exec()` émulé par boucle imbriquée) — la modalité passe d'applicative à fenêtre, sans effet réel : l'app n'a qu'une fenêtre, les Préférences en sont une page ; carte d'association 440→580 px + infobulle ; « Tout cocher/décocher » avec compteur `PARTICIPANTS (n/N)` ; **pré-cochage à seuil** — tout coché jusqu'à `SEUIL_PRECOCHAGE = 8` personnes, au-delà organisateur + `STATUT_ACCEPTE` seulement (un événement à 34 invités externes nourrissait le CR de noms absents → participants inventés). ⚠️ Piège Fusion/Linux trouvé au passage : le fond du viewport doit être neutralisé par une feuille de style posée sur **le viewport seul** (sur le `QScrollArea` elle bascule aussi la barre de défilement ; une palette blanche, elle, est écrasée par le `QWidget {…}` global) — invisible sur macOS. `bluemind_details` réparé sans le toucher | `docs/50` |
| **Copie du CR mise en forme (collage riche Pipedrive/webmail) — ✅ TERMINÉ, validé manuellement, fusionné dans `main`** (2026-08-26, 1581 passed, 0 échec, +45 tests). Déclencheur : le prompt « CR Pipedrive » produisait des `<b>`/`<i>`/`<br>` littéraux pour contourner l'absence d'interprétation markdown de Pipedrive — mais collés en texte brut, ces balises restaient visibles : un éditeur riche ne met en forme que ce qu'il reçoit **déjà en HTML** sur le presse-papiers, jamais un texte collé, markdown ou pseudo-HTML. Mesure empirique décisive : une note de test à 20 constructions HTML, collée puis relue **à la balise près** via l'API Pipedrive (`getNotes`) — les niveaux de titre `<h1>`-`<h3>` sont aplatis en `<div>`, tout le reste est conservé ; comme le CR BlueMind ne s'appuie jamais sur des titres (structure 100 % portée par le gras), rien n'était perdu. Livré : `core/markdown_html.py` (convertisseur pur, calibré sur les **56 CR réels du poste** plutôt que sur CommonMark strict — cf. docs/51 §3 pour les 3 écarts mesurés) ; `PressePapiers.copier_riche(html, texte)` commun aux 3 OS ; bouton de copie de l'Historique devenu split button (clic = mis en forme, flèche = choix du format) ; retrait du prompt Pipedrive (migration config **v4**). Build Windows + fumée automatisée verts le même soir sur ce commit (`debriefMeet-setup-0.3.0+20260826.1cbbd5d.exe`). Détails, mesures et pièges : `docs/51` | `docs/51` |
