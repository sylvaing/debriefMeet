# Édition « lite » Windows — enregistrement Opus + IA distante Mistral

**Statut : ✅ code, tests, builds réels et fumée terminés (2026-07-30) — livré et utilisé
en réel (§8). Setup lite 116 Mo contre 159 Mo pour la complète (−27 %). Reste : chaîne
de bout en bout avec du vrai contenu audio, et 4 points mineurs listés en §8.7.**

## 1. Contexte et problème

Les postes Windows cibles (Bastien, Alix) n'ont pas de GPU et la transcription locale
CPU int8 y est lente. Or l'interco Mistral (docs/42) sait déjà **tout** faire à
distance : Voxtral transcrit les pistes `.opus`, `mistral-small` génère le CR. Le
bundle Windows embarque pourtant toute la pile Whisper locale pour un moteur qui ne
servira jamais sur ces machines, et l'app télécharge ~1,5 Go de `large-v3-turbo` au
premier lancement.

**Aucune fonctionnalité nouvelle n'est nécessaire** : tout existe déjà
(`transcription_live=False`, `MARQUEUR_EN_ATTENTE`,
`mistral.pipeline.generer_cr_reunion` qui transcrit un placeholder puis réécrit le
`.md`). Le chantier consiste à **désactiver proprement à la compilation** le moteur
local, la diarization, les modes Dictée/Journal et leurs UI, et à sortir les paquets
correspondants du bundle.

### Ce qui sort / ce qui reste

| Sort de l'édition lite | Reste (indispensable à l'enregistrement + Mistral) |
|---|---|
| `faster-whisper`, `ctranslate2`, `tokenizers`, `huggingface_hub`, `hf_xet` | `soundcard` — loopback WASAPI : sans lui l'**autre partie** n'est pas enregistrée |
| `onnxruntime`, `av` (tirés par faster-whisper, hooks PyInstaller dédiés) | `livekit` — AEC3, cf. §2 D2 |
| Sélecteur de modèle Whisper (Préférences › Modèle) | `ffmpeg.exe` embarqué — encodage Opus + décodage 16 kHz (docs/41) |
| Diarization : badge + assistant, action « Générer les locuteurs » | `sounddevice`, `numpy`/`scipy`, `httpx`, `python-dateutil` (deps cœur) |
| Action « Transcrire la réunion » (transcription différée locale) | Interco BlueMind, interco Mistral, historique, rétention audio |
| Modes **Dictée** et **Journal** (tray, pages, raccourcis) | Mode **Réunion** |
| `pyannote`, `torch`, `mlx*` — déjà exclus du bundle Windows avant ce chantier | |

## 2. Décisions figées (ne pas re-discuter)

**D1 — Dictée et Journal masqués à la compilation.** Ils dépendent à 100 % du moteur
local et n'ont pas d'équivalent distant utile (leur intérêt est le retour immédiat :
presse-papiers / entrée du jour ; un aller-retour réseau le détruirait). Lite =
« réunion » uniquement.

**D2 — AEC (livekit) conservée.** Sans elle la piste `moi.opus` capte aussi les voix
distantes : Voxtral les transcrirait deux fois et la fusion des deux pistes
deviendrait illisible. livekit pèse bien moins que la pile Whisper — le gros du gain
vient de `faster-whisper` et de ses dépendances natives.

**D3 — `AppId` inchangé → éditions mutuellement exclusives.** Installer lite remplace
la complète et inversement ; une seule entrée dans « Applications installées », mêmes
`%LOCALAPPDATA%\debriefMeet` et `Documents\debriefMeet`. Seuls changent le nom affiché
(`debriefMeet Lite`) et le nom du setup (`debriefMeet-lite-setup-<version>.exe`).
**Conséquence structurante :** une nouvelle install lite hérite du `config.json` d'une
install complète → aucune valeur par défaut ne peut servir de garantie (cf. D5).

**D4 — Source unique de vérité : `EDITION_COMPILEE` dans le `_version.py` généré.** Le
spec PyInstaller le lit par regex, le runtime par import. Pas de variable
d'environnement lue indépendamment par plusieurs consommateurs : ce serait autant
d'occasions de divergence, et la pire est silencieuse — un bundle privé de
`ctranslate2` dont l'app se croit complète proposerait une transcription locale qui
meurt au premier usage. Effet de bord précieux : `generer_version.py` tourne à l'étape
`[3/6]`, **avant** la gate pytest `[4/6]` → la gate d'un build lite teste l'édition
lite, avec une ligne de commande pytest inchangée.

**D5 — Aucune clé de `_DEFAUTS` ne change entre éditions.** `Config.charger()`
(`core/config.py:99-101`) jette les clés inconnues et `set()` lève sur clé inconnue :
une forme de `_DEFAUTS` propre au lite détruirait silencieusement les réglages de
l'édition complète au changement d'édition. Toute garantie est appliquée **au point
d'usage**, jamais par un défaut. Corollaire : `mistral_source_transcription` reste
`"auto"` — en lite `_lire_transcript_local` rend `None` sur le placeholder, donc
`"auto"` et `"voxtral"` sont behaviouralement identiques.

## 3. Mécanisme

```
scripts/build_app_windows_vm.sh --lite
        └→ build_app.cmd lite
              ├─ [1/6] pip install -e .[windows-lite,dev]      ← extra sans faster-whisper
              ├─ [3/6] generer_version.py --edition lite
              │           ├→ src/debrief_meet/_version.py   : EDITION_COMPILEE = "lite"
              │           └→ packaging/windows/version.iss  : #define MonAppEdition "lite"
              ├─ [4/6] pytest  ← lit _version.py, tourne donc DANS l'édition lite
              ├─ [5/6] pyinstaller  ← le spec regexe _version.py → excludes lite
              └─ [6/6] ISCC         ← le .iss lit #define → AppName + OutputBaseFilename
```

**Runtime** — `src/debrief_meet/core/edition.py` (stdlib seule, règle d'or respectée) :

- `edition()` → `"complete" | "lite"`. Résolution **monotone** : `EDITION_COMPILEE`
  puis `DEBRIEFMEET_EDITION`, qui peut *restreindre* (complète → lite) mais **jamais
  élargir**. Un bundle lite qui se croirait complet ferait tomber la fabrique sur
  `MoteurStub`, dont la sortie `[stub — pas de transcription réelle]` serait écrite
  dans un vrai débrief.
- L'environnement est relu **à chaque appel** (et non figé à l'import) : c'est ce qui
  rend l'édition lite testable par un simple `monkeypatch.setenv`, sans
  `importlib.reload` (dangereux avec Qt, docs/26), et exerçable en dev par
  `DEBRIEFMEET_EDITION=lite make run`. Coût : un `dict.get` à la construction d'un
  widget et au démarrage d'une réunion — jamais dans la boucle audio.
- Valeur inconnue → repli `complete` + WARNING, jamais d'exception.
- Prédicats de capacité, seuls interrogés par le code métier :
  `avec_transcription_locale()`, `avec_diarization()`, `avec_dictee_journal()`.
  Le préfixe `avec_` est obligatoire : `edition.diarization()` à côté de
  `diarization.configuree()` dans le même fichier serait un piège de lecture.

## 4. Fichiers touchés

### Runtime

| Fichier | Changement |
|---|---|
| `core/edition.py` | **nouveau** — le module ci-dessus |
| `__init__.py` | `_version` importé comme module + `getattr` : un `_version.py` sans `EDITION_COMPILEE` ne fait plus retomber `VERSION_COMPLETE` en `+dev` |
| `core/raccourcis.py` | `actions()` filtre `ACTIONS` — **point d'étranglement unique**, alimente l'enregistrement OS **et** les éditeurs de Préférences |
| `platform/factory.py` | `Adaptateurs.moteur: MoteurTranscription \| None`, gate sur l'**édition** (cf. §5) |
| `core/reunion.py` | `_transcription_live` forcé False en lite — **site unique** (§5) ; `moteur` optionnel ; `debloquer=None` |
| `ui/preferences_view.py` | `_sections()` remplace les 2 tuples parallèles ; Audio sans les cases menteuses ; raccourcis pilotés par `actions()` |
| `ui/reunion_view.py` | actions « Transcrire » / « Générer les locuteurs » **non ajoutées** (§5) |
| `ui/tray.py` | `_actions_modes` + table `_MODES_MENU` ; `_actualiser_libelles` réduit à 2 règles |
| `ui/fenetre_principale.py` | `_index_pages` : les `PAGE_*` redeviennent des identifiants, plus des positions |
| `ui/recording_controller.py` | vues Dictée/Journal optionnelles |
| `ui/remote_ia_view.py` | case « forcer Voxtral » masquée (inerte en lite) |
| `platform/infos_systeme.py`, `core/logs.py` | `edition` dans l'en-tête de session, le zip de diagnostic et la 1ʳᵉ ligne de log |
| `__main__.py` | orchestrateurs Dictée/Journal, garde IPC, préchargement de modèle, chaîne `aboutToQuit` |

### Packaging

`pyproject.toml` (extra `windows-lite`), `packaging/windows/generer_version.py`
(`--edition`), `debriefMeet.spec` (`_edition_compilee()`, `EXCLUDES_LITE`),
`debriefMeet.iss` (bloc ISPP, `[InstallDelete]`), `build_app.cmd` (argument `%~1`),
`scripts/build_app_windows_vm.sh` (`--lite`), `scripts/fumee_setup_vm.sh` (§6).

### Bonus embarqué — bouton d'export des logs

`ui/export_diagnostic.py` (**nouveau**) factorise le corps de
`tray._exporter_diagnostic` ; Préférences › Journalisation gagne
« Exporter les logs (.zip)… », qui réutilise le zip de `core/diagnostic.py` (logs +
config + infos machine, **jamais de texte transcrit**, docs/31 §3.7.1). Indépendant de
l'édition, mais d'autant plus utile en lite : c'est le seul moyen de diagnostiquer un
échec de transcription distante à distance. Corrigé au passage : la note affichait en
dur `~/Library/Logs/debriefMeet/`, **faux sur Windows**.

## 5. Pièges (lire avant de toucher au code)

**La fabrique doit gater sur l'ÉDITION, pas sur `ImportError`.**
`platform/windows/moteur_faster_whisper.py` n'importe `faster_whisper` **nulle part au
niveau module** (c'est le sous-processus worker qui le fait) : dans un bundle lite le
moteur se construirait sans erreur et ne mourrait qu'à la première transcription, chez
l'utilisateur. Un `except ImportError` ne protège de rien.
Gardé par `tests/test_factory_windows.py::test_lite_aucun_moteur_local`.

**`moteur = None`, jamais `MoteurStub`.**
`GestionnaireDiarization.disponible()` est littéralement `self._moteur is not None` :
un stub rendrait « Transcrire la réunion » **actif**, et `MoteurStub._transcrire_pret`
écrirait `[stub — pas de transcription réelle]` par-dessus une vraie réunion.

**`reunion_view` : gater est obligatoire, pas cosmétique.** Dans `_actions_reunion`,
`actions.append(...)` était **inconditionnel** ; `dispo`/`prete` ne pilotent que
`actif` et l'infobulle. En lite toute réunion est « en attente » jusqu'à ce que Mistral
écrive le transcript → **chaque ligne** afficherait une icône grisée « Moteur de
transcription indisponible », et l'autre branche renverrait vers une ligne de
Préférences › Audio qui n'existe plus.

**Le garde IPC est une correction de justesse.** `--toggle` peut encore arriver d'un
raccourci bureau survivant à une MAJ complète → lite (AppId identique). Sans garde,
`MachineEtats` bascule en `Mode.DICTEE` **sans orchestrateur à l'écoute** : rien
n'enregistre, le tray ne rougit pas, et `Mode.REUNION` reste ensuite refusé —
verrouillage silencieux de la seule fonctionnalité de l'app. `--toggle` et
`--toggle-journal` restent **acceptés et ignorés** dans `_parser()` : les retirer
ferait `argparse` sortir en 2, invisible avec `console=False`.

**`_transcription_live` : un seul site correct** (`core/reunion.py`, dans
`_demarrer()`). C'est la variable que lisent toutes les branches aval — rétention
forcée, placeholder du `.md`, routage du tick, arrêt court-circuité. Gater plus tard
(dans `_sur_tick`) laisserait `_demarrer` appeler `EcrivainReunion.creer()` **et**
sauter la rétention → une réunion avec ni audio ni transcript.

**`av` et `onnxruntime` doivent être exclus NOMMÉMENT.** Notre code ne les importe
jamais (zéro occurrence dans `src/`), ils n'entrent que via `faster_whisper` — mais
`_pyinstaller_hooks_contrib` fournit un hook dédié pour chacun, donc sans exclusion
explicite ils restent dans le bundle. À eux deux ~41 Mo de wheel : le plus gros du gain.

**`[InstallDelete]` du `.iss` n'est pas optionnel.** `[Files]` **copie par-dessus** et
ne fait jamais de miroir : les fichiers présents dans l'ancienne install et absents de
la nouvelle survivent (Inno ne les retire qu'au désinstall, depuis son log — or une MAJ
ne rejoue pas l'ancien désinstalleur). Sans vider `{app}\_internal`, installer lite
par-dessus la complète laisserait ~150-200 Mo de DLL Whisper mortes et **annulerait tout
le gain sur le chemin de mise à jour**. Prouvé par la phase B′ de la fumée.

**Les cases à cocher qui mentent.** `transcription_live` et `retention_audio` sont
forcés par l'orchestrateur en lite : les afficher serait un contrôle sans effet. La
rétention est remplacée par une note ; le contrôle par réunion reste dans l'Historique
(« Supprimer l'audio (garde le débrief) »).

## 6. Definition of Done

| # | Gate | Statut |
|---|---|---|
| 1 | `make test` en édition complète (défaut) — aucune régression | ✅ **1153 passed** (2 échecs d'env. attendus : helper Swift non compilé, audio canonique du benchmark) |
| 2 | `DEBRIEFMEET_EDITION=lite pytest -m "not integration"` | ✅ **1153 passed**, mêmes 2 échecs |
| 3 | Gate VM lite simulée (lite **+ sans `huggingface_hub`**), commande exacte de `build_app.cmd [4/6]` | ✅ **951 passed, 11 skipped, 0 échec** |
| 4 | `bash scripts/build_app_windows_vm.sh --lite` — build réel | ✅ **2026-07-30**, gate VM **971 passed, 16 skipped, 0 échec** (§7) |
| 5 | Taille du setup **mesurée** et consignée §7 | ✅ **116 Mo** (159 → −27 %) ; exclusions vérifiées sur le bundle |
| 6 | Build de l'édition **complète** depuis le même commit — non-régression de taille | ✅ **159 Mo**, gate VM **982 passed, 5 skipped** (§7) |
| 7 | `bash scripts/fumee_setup_vm.sh` sur les **deux** setups, 2 fois chacun | ✅ **4 runs, 0 échec**, dont `ctranslate2 RETIRE par le passage a lite` (§7) |
| 8 | Suite complète relancée **dans les 2 éditions** après tous les correctifs | ✅ **1156 passed** chacune (24 s), 2 échecs d'env. attendus |
| 9 | `DEBRIEFMEET_EDITION=lite` + lancement de l'app — vérification visuelle macOS | ⬜ demande une vraie session graphique (cf. note ci-dessous) |
| 10 | Réunion réelle enregistrée sur la VM → « Générer le CR (Mistral) » avec clé réelle | ⬜ nécessite une clé API |

**Lancer l'app ou les tests depuis un worktree — deux pièges.** (a) Le worktree n'a pas
de `.venv` et l'install éditable du venv principal pointe vers le **dépôt principal** :
sans `PYTHONPATH=$PWD/src`, `make run` exécute le code de `main` et on conclut à tort que
rien n'a changé. (b) Les tests Qt exigent une session graphique attachée ; dans un
contexte sans TTY ni `SECURITYSESSIONID`, `QApplication` se construit mais
`processEvents()` ne rend jamais la main. Contournement pour la suite :
`QT_QPA_PLATFORM=offscreen` (24 s au lieu d'un blocage). La vérification **visuelle**,
elle, demande forcément une vraie session — et l'app installée doit être quittée d'abord
(micro et raccourcis globaux partagés).

Les 11 tests sautés en gate lite sont ceux qui importent `huggingface_hub` dans leur
corps (`test_diarization.py` ×8, `test_moteur_faster_whisper.py` ×3) — garde
`pytest.importorskip("huggingface_hub")`, **par test et non par module** : les ~40
autres tests de `test_diarization.py` sont du Python pur (étiquetage, attribution,
fusion) et doivent continuer à tourner en lite.

### Stratégie de test : épingler plutôt que sauter

Les modules dont le **sujet** est une fonctionnalité absente en lite portent une
fixture `autouse` `edition_complete_sauf_si_lite` (`tests/conftest.py`) qui épingle
l'édition complète, sauf pour les tests demandant explicitement `edition_lite`.

Épingler plutôt que `skipif(est_lite())` : un test sauté ne garde **rien**, alors qu'un
test épinglé continue de garder du code réellement livré (l'édition complète l'est
aussi), y compris pendant la gate d'un build lite. Les 8 modules concernés :
`test_raccourcis`, `test_factory_windows`, `test_remote_ia_view`, `test_reunion`,
`test_preferences_view`, `test_reunion_view`, `test_fenetre_principale`, `test_tray`.

Nouveaux tests : `tests/test_edition.py` (11), `tests/test_export_diagnostic.py` (5),
`TestSpecWindowsEditions` dans `tests/test_build.py` (12 — **les premiers tests du
dépôt portant sur le spec et le `.iss`**, lecture structurelle par `ast` pour qu'un
commentaire citant `ctranslate2` ne puisse pas tromper le test ; ils épinglent au
passage deux invariants jusqu'ici tenus par un simple commentaire : le GUID « NE JAMAIS
CHANGER » et `AppMutex` == `instance_unique.NOM_MUTEX`), + 6 tests de
`generer_version` dont l'anti-obsolescence, + ~18 tests lite explicites.

## 7. Journal — premier build lite réel (2026-07-30)

`bash scripts/build_app_windows_vm.sh --lite` →
`dist/debriefMeet-lite-setup-0.2.0+20260730.59fa002.exe`

| Mesure | Lite | Complète (réf. docs/41) | Écart |
|---|---|---|---|
| Setup `.exe` | **116 Mo** | 159 Mo | **−43 Mo (−27 %)** |
| `dist\debriefMeet` décompressé | 395 Mo (1186 fichiers) | — | dont 108 Mo d'`ffmpeg.exe` |
| Gate pytest VM | 971 passed, 16 skipped, 0 échec | 962 passed (Mac, réf.) | — |
| Modèle téléchargé au 1ᵉʳ lancement | **aucun** | ~1,5 Go (`large-v3-turbo`) | −1,5 Go |

**Exclusions vérifiées sur le bundle** (et non déduites de la taille) : `ctranslate2`,
`av`, `onnxruntime`, `faster_whisper`, `tokenizers`, `huggingface_hub`, `hf_xet` →
**tous absents** de `_internal\`. `soundcard`, `livekit`, `tzdata` et `ffmpeg` →
**tous présents**, comme voulu.

**116 Mo contre 95-115 Mo estimés** : la borne haute est dépassée de 1 Mo, l'estimation
était donc légèrement optimiste (−27 % au lieu de −30 à −40 %). L'écart s'explique par
le poids incompressible commun aux deux éditions — Qt/PySide6 et surtout les 108 Mo
d'`ffmpeg.exe`, qui à eux seuls dominent le bundle décompressé. Le levier suivant est
donc bien ffmpeg (cf. ci-dessous), pas la pile Whisper : elle est déjà entièrement
sortie.

### Fumée — `scripts/fumee_setup_vm.sh`, les deux setups (2026-07-30)

Les deux éditions produites depuis **le même commit** (`59fa002`), donc directement
comparables. `debriefMeet-setup` : **159 Mo**, exactement la référence docs/41 — l'édition
complète n'a pas grossi (`tzdata` est négligeable). Gates VM :

| | passed | skipped |
|---|---|---|
| complète | **982** | 5 |
| lite | **971** | 16 |

L'écart est de **11 dans les deux sens** : les 11 tests gardés par
`importorskip("huggingface_hub")`, qui s'exécutent quand `faster-whisper` est installé et
se sautent sinon. Cela valide d'un coup que le drapeau agit dans les deux sens, que les
tests épinglés tournent (ils ne sont pas sautés), et qu'il n'y a **aucune contamination**
entre deux builds enchaînés sur la même VM (propriété anti-obsolescence de `_version.py`).

**Zéro `[ECHEC]`, sur les deux setups et sur 2 exécutions chacun** (standard de
rejouabilité docs/37 §5-6 : 4 runs verts au total, code de sortie 0). Vérifications
marquantes :

- `ctranslate2 RETIRE par le passage a lite` — **l'assertion décisive** : elle prouve que
  `[InstallDelete] {app}\_internal` fonctionne. Sans elle, ~150-200 Mo de DLL Whisper
  mortes survivraient à la MAJ complète → lite et annuleraient tout le gain.
- `ctranslate2 present apres passage au complet` — le sens inverse fonctionne aussi.
- `raccourci menu Demarrer (debriefMeet Lite.lnk)` + `pas de raccourci de l'autre
  edition` dans les deux sens — nettoyage des raccourcis par `[InstallDelete]`.
- `entree de desinstallation unique (AppId partage)` — les 2 éditions sont bien un seul
  produit pour Windows.
- Les 4 sondes d'absence (`ctranslate2`, `av`, `onnxruntime`, `faster_whisper`) passent
  sur le bundle **installé**, pas seulement sur `dist/`.
- `config.json` et `Documents\debriefMeet` préservés à la MAJ **et** au changement
  d'édition ; `%LOCALAPPDATA%\debriefMeet` bien supprimé au désinstall (D4).

Les 2 `[INFO]` restants sont la limite SSH connue et inchangée (docs/37 §7 :
`usPostUninstall` ne se déclenche jamais via SSH — désinstalleur non auto-supprimé,
valeur de Registre non nettoyée). Non concernés par `[InstallDelete]`, qui tourne à
l'installation.

### Incidents du premier build (4 tentatives)

Trois blocages, dont **deux pré-existants révélés** par cette première gate VM depuis
2026-07-12 :

1. **`build_app.cmd` — guillemet parasite ssh** (de ce chantier). Windows OpenSSH
   enveloppe la commande reçue dans un **second** `cmd /c` : son guillemet fermant fuit
   dans le dernier argument, donc `%1` valait `lite"`. Or `%~1` ne retire que des
   guillemets **appariés** → `if "lite"""==""` → « La syntaxe de la commande n'est pas
   correcte ». Corrigé par un retrait explicite de tout guillemet + `if defined` (la
   substitution `%VAR:"=%` n'est pas expansée sur une variable non définie : cmd laisse
   le texte littéral et casse la ligne suivante). Validé sur la VM pour les 4 cas.
2. **`tzdata` non déclaré** (pré-existant, `a7869c8` du 2026-07-27). Windows n'a aucune
   base de fuseaux système ; `zoneinfo` y exige le paquet PyPI. `sync.py` et
   `recurrence.py` enveloppant `ZoneInfo(...)` dans un `try/except`, l'absence ne
   plantait pas — elle faisait **retomber silencieusement sur un offset figé**, soit
   exactement le bug DST que docs/40 §5.2 corrigeait. L'édition complète était cassée à
   l'identique. Déclaré en dépendance cœur avec marqueur `sys_platform == 'win32'` et
   ajouté aux paquets collectés par le spec.
3. **Deux hypothèses macOS non gardées** (pré-existant) :
   `test_demarrage_auto_macos.py` comparait des chemins POSIX au contenu d'un plist, et
   le test ffmpeg assertait `vendor/ffmpeg` alors que Windows utilise
   `ffmpeg\ffmpeg.exe`. Le premier est sauté hors macOS, le second suit désormais la
   branche de la plateforme — il **couvre** donc la disposition Windows.
4. **Course dans `assistant_mistral`** : `_succes` était positionné avant l'écriture de
   la clé et la mise à jour des libellés, exposant un état intermédiaire. Drapeau
   déplacé en dernier ; le test se synchronise sur le libellé qu'il asserte.

### Levier suivant, hors périmètre

Les 108 Mo d'`ffmpeg.exe` (BtbN complet, ~34 Mo compressés) contre un build LGPL minimal
à la `packaging/build_ffmpeg.sh` (~5-10 Mo sur macOS) rendraient ~25-30 Mo compressés aux
**deux** éditions — soit, en proportion, un gain plus important pour le lite que tout ce
qui reste à gratter côté Python. Mérite son propre docs/NN.

Estimation d'origine, à partir des wheels win_amd64 (déjà compressés en deflate, donc
majorant de la contribution marginale LZMA2) : `av` 27,6 Mo + `ctranslate2` 19,2 Mo +
`onnxruntime` 13,8 Mo + `hf_xet` 4,0 Mo + `tokenizers` 2,8 Mo + `faster_whisper`/
`huggingface_hub` ~3 Mo ≈ **70 Mo**. Recoupé avec la composition connue (setup 125 Mo
avant ffmpeg → 159 Mo après, soit 108 Mo d'`ffmpeg.exe` compressés à ~34 Mo, ratio
31 %) : **159 Mo → ~95-115 Mo**, et ~150-200 Mo de moins décompressés dans `{app}`.

Le gain le plus visible pour l'utilisateur est ailleurs : lite ne télécharge
**jamais** `large-v3-turbo` (~1,5 Go) — l'app est utilisable dès la fin de l'install.

### Levier suivant, hors périmètre

Le binaire BtbN complet (108 Mo, ~34 Mo compressés) contre un build LGPL minimal à la
`packaging/build_ffmpeg.sh` (~5-10 Mo sur macOS) rendrait encore ~25-30 Mo compressés
aux **deux** éditions. Indépendant de ce chantier, mérite son propre docs/NN.

Verrue connue et assumée : le bouton « Configurer… » de la diarization dans
Préférences › Audio est **déjà mort sur Windows** dans les deux éditions (`pyannote` et
`torch` sont exclus du bundle Windows depuis toujours). Lite le fait disparaître ;
l'édition complète Windows le conserve.

---

## 8. Retour de terrain — micro non enregistré chez Alix (2026-07-31 → 08-03)

Premier usage réel du lite, et première utilisation du bouton « Exporter les logs ».
Symptôme rapporté : « le son du micro n'est pas enregistré ».

### 8.1 Ce que le premier diagnostic a montré

Aucun WARNING, aucune exception — mais le micro **redémarré toutes les ~1,1 s** :
92 événements `audioInputsChanged`, 144 reconnexions. Chaque `redemarrer()` coûte
0,3 s d'attente de fermeture + 0,2 s de warm-up **jeté**, donc le flux est affamé.
Conséquence en cascade, lisible dans les logs AEC :

| Tranche | RMS brut | RMS nettoyé | Atténuation | Calage |
|---|---|---|---|---|
| 1 | 0,00947 | 0,00874 | −0,7 dB | −583 ms |
| 2 | 0,00660 | 0,00407 | −4,2 dB | +594 ms |
| 3 | 0,00311 | 0,00120 | −8,3 dB | −439 ms |
| 4 | 0,00543 | **0,00097** | **−15,0 dB** | +87 ms |

Le calage oscille de −583 à +594 ms et les logs disent `saut micro=0` pendant que la
référence avance : l'AEC ne peut pas se caler et soustrait n'importe quoi. Seuil de
silence à 0,008 ⇒ la piste finit **sous le seuil**.

**Fuite de secrets découverte au passage** : le zip embarquait `config.json` en clair,
donc la clé API Mistral et le token BlueMind de Alix. Corrigé en premier (commit
`a6b2052`, `core/diagnostic.caviarder`) — cf. docs/31 §3.6.

### 8.2 Deux causes possibles appelant des correctifs OPPOSÉS

`docs/25` a **délibérément supprimé** la comparaison « est-ce vraiment notre
périphérique ? » : `resoudre_peripherique` lisait une table PortAudio périmée et jugeait
« inchangé » un vrai retrait d'AirPods. La reconnexion inconditionnelle est donc un
**correctif macOS**, couvert par 12 tests de `test_reunion.py`. Impossible d'y toucher à
l'aveugle. Deux hypothèses restaient :

1. la liste des entrées **change réellement** (matériel qui énumère en boucle) ;
2. Qt émet un **signal parasite** à liste constante.

D'où une étape purement observationnelle (même commit) : journaliser l'écart entre deux
relevés de la liste **Qt** — et non de la table PortAudio, dont la péremption est
justement ce que docs/25 reprochait à l'ancienne comparaison.

### 8.3 Verdict du second diagnostic

| | occurrences |
|---|---|
| Liste **INCHANGÉE** → signal Qt parasite | **3086** |
| Liste réellement modifiée | **3** |

Les 3 réels sont le même casque Bluetooth (`Headset (casque Bluetooth)`) qui se
connecte/déconnecte — exactement le scénario que docs/25 protège. Ampleur : **3082
reconnexions en 65 min**. Machine : Windows 11, puce Realtek SST.

### 8.4 Correctif — gardé sur Windows, et pourquoi

`SurveillantPeripheriques` ignore l'événement à liste inchangée **si et seulement si
`sys.platform == "win32"`**.

Le réflexe serait de corriger pour tout le monde. C'est **refusé** : la comparaison porte
sur `description()`, donc elle ne verrait PAS deux cas qui concernent macOS —
un changement de taux d'échantillonnage à périphérique constant (AirPods 24↔48 kHz,
docs/20) et un changement de périphérique **par défaut** à liste constante (`micro_index`
vaut `None`, l'app doit suivre le défaut). Sur macOS ces cas sont aujourd'hui couverts par
la reconnexion inconditionnelle. **Aucune donnée macOS ne permet de les supprimer sans
risque** — et macOS fonctionne, Windows est cassé : on ne met pas en risque celui qui
marche pour réparer l'autre.

Trois précautions :

- **Paramètre de constructeur** `supprimer_parasites`, défaut dérivé de `sys.platform`.
  Les tests le passent explicitement, sinon les 3 tests d'anti-rebond existants
  s'inverseraient sur la gate VM Windows (verts sur Mac, rouges au build).
- **Repli fail-open** : un relevé vide (Qt indisponible, ou plus aucune entrée) ne doit
  jamais passer pour « inchangé ». Une panne de l'instrumentation désactiverait sinon en
  silence la reconnexion à chaud.
- **Filet conservé** : le watchdog « tranche muette » (`core/reunion.py`) reconnecte si
  le buffer micro reste vide sur une tranche entière — un événement ignoré à tort est
  donc rattrapé.

`test_hors_windows_liste_inchangee_emet_quand_meme` verrouille explicitement le
comportement macOS.

### 8.5 Validation terrain (2026-08-03, build `69e1283`)

⚠️ **Le log est rotatif** : un diagnostic contient plusieurs sessions, parfois de
plusieurs versions. Segmenter sur la ligne `Logs activés … — <version>` **avant** de
compter, sinon les chiffres des anciens builds faussent tout (constaté : 3154
reconnexions au total, dont 0 pour le build corrigé).

**Le correctif fonctionne**, sur deux sessions successives :

| | avant | après |
|---|---|---|
| Événements à liste inchangée | 3086 | 12 puis 2 |
| **dont ignorés** | 0 | **12 puis 2** (tous) |
| **Reconnexions micro** | **3082** (65 min) | **0 puis 1** |
| Calage AEC | oscillant −583 → +594 ms | **`AEC calée`** |

Le changement réel (casque Bluetooth branché) est bien passé à travers le filtre.

**L'AEC s'est réparée d'elle-même**, comme espéré : elle affiche
`AEC non calé → passthrough (voix préservée)` puis `AEC calée`. Le garde-fou qu'on
envisageait d'ajouter **existait déjà** — il ne se déclenchait pas parce que la tempête
faisait croire à l'AEC qu'elle était calée. Chantier AEC **abandonné**, sans regret :
c'était le plus risqué pour macOS.

### 8.6 Le silence était un problème de sélection de périphérique

Cause finale, **indépendante** de la tempête et invisible tant que celle-ci masquait
tout : Windows dirigeait l'entrée vers le micro interne Realtek pendant que
l'utilisatrice portait des écouteurs Bluetooth. L'app ouvrait donc
`Microphone Array (2- Realtek(R)` (RMS **0,0000**) tandis que la capture système sortait
sur `écouteurs One Plus`. Après changement de la source d'entrée dans Windows :

| | Realtek (défaut Windows) | Casque, explicitement |
|---|---|---|
| RMS brut | 0,0000 | **0,12770** / **0,12056** |
| vs seuil 0,008 | sous le seuil | **×16 au-dessus** |
| Atténuation AEC | −15 dB | −0,49 / −0,20 dB |
| Tranches « Audio silencieux » | toutes | **aucune** |

**Hypothèse infirmée — à ne pas ressortir** : on avait cru à un « micro faible à la
source » (0,003–0,009 brut) justifiant de normaliser la piste Opus avant envoi à Voxtral.
Faux : ces valeurs étaient le Realtek captant du bruit de pièce à vide. Avec le bon
périphérique on est à 0,127. La piste Opus n'est effectivement pas normalisée
(`normaliser_asr` vit dans `MoteurTranscription.transcrire()`, que lite n'appelle jamais),
mais **ce n'était pas le problème** et rien n'est à corriger là.

### 8.7 Ce qui reste ouvert

- ✅ **Sélecteur de micro ambigu** — corrigé le 2026-08-04 : le libellé porte l'API audio
  (`Headset (casque Bluetooth) — Windows WASAPI`), et « Périphérique par défaut »
  indique ce qu'il résout réellement (`(actuellement : Microphone Array…)`). Avant, le
  même casque apparaissait **trois fois à l'identique**, ce qui rendait le contournement
  impraticable et poussait à modifier Windows à la place.
- ✅ **Avertissement « aucun son capté »** — ajouté le 2026-08-04. À la FIN d'une réunion
  dont la piste micro était **intégralement** muette, notification + WARNING. Déclencheur
  volontairement conservateur : jamais sur une tranche isolée (une tranche muette est
  banale), donc pas de faux positif possible — c'est ce qui le rend sans risque sur macOS.
- ❌ **« Suivre le périphérique par défaut » — HYPOTHÈSE INFIRMÉE, ne pas la ressortir.**
  J'avais écrit ici que l'app ne suivait pas la bascule vers le casque. **C'est faux** :
  `_ouvrir_flux(None)` laisse PortAudio résoudre le défaut à chaque ouverture, donc l'app
  suit fidèlement le défaut Windows à chaque démarrage de réunion et à chaque
  reconnexion. Preuve dans les logs : le casque était **déjà dans la liste** à 16:53:37
  et l'app a ouvert le Realtek à 16:54:22 ; après changement du réglage **Windows**, elle
  a ouvert le casque à 17:10:24. Le défaut Windows n'était simplement pas le casque —
  ce n'est pas un défaut de l'app. Seul cas non couvert : un changement de défaut
  *pendant* une réunion à liste constante, déjà rattrapé en 30 s par le watchdog
  « tranche muette ». Le coder signifierait toucher le code partagé le plus risqué pour
  macOS pour un gain marginal : **abandonné au profit de l'avertissement ci-dessus**, qui
  traite le dommage réel (plusieurs réunions muettes sans que personne ne le sache).
- **Sync BlueMind cassée** — `'NoneType' object has no attribute 'get'` avalé par le
  `except` silencieux de docs/40 §1.1, alors que l'interco **est** configurée. Rien à voir
  avec le micro ; à traiter séparément.
- Chaîne de bout en bout **non validée avec du vrai contenu** : le CR Voxtral a été
  produit, mais à partir de silence. Reste à enregistrer en parlant puis à déclencher
  « Générer le CR (Mistral) » depuis l'Historique.
- Trou de journalisation mineur : `att None` au lieu d'une valeur d'atténuation quand le
  micro est quasi muet.
