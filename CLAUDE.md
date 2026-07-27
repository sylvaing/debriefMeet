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
du dossier — plus aucun artefact ne peut rester orphelin. Migration one-shot
idempotente au démarrage (`core/migration_dossiers.py`) pour les réunions à plat
d'avant docs/43. Le **journal** (`AAAA-MM-JJ.md`) reste inchangé (à plat, 1 fichier/jour).

**Réunion active exclue du listing** : son `transcription.md` est créé dès le démarrage
de l'enregistrement, et elle est déjà représentée par la ligne « en cours » → sans
exclusion elle s'affiche **deux fois** (bug pré-existant, constaté en test manuel le
2026-07-27). `reunion_view.definir_reunion_active` (câblée sur
`OrchestrateurReunion.reunion_demarree`) pose le chemin actif à la fois sur le watcher
(§9) et sur `CaptureModel.definir_chemin_actif` ; le retour à `Mode.IDLE` le remet à None.

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
Après la réorganisation 1 dossier/réunion (docs/43, 2026-07-27) : **1106 passed** dans
le même environnement (mêmes 2 échecs attendus, inchangés) — nouveau module
`core/migration_dossiers.py` (`test_migration_dossiers.py`, 14 tests) + tests étendus
de `test_fichiers.py` (slug, nom de dossier, renommage) + adaptation du layout dans
tous les tests touchant des réunions (fixtures désormais en sous-dossier) + 6 tests
d'exclusion de la réunion active (ligne en double, cf. § ci-dessous).

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
| **Interco Mistral — CR cloud adaptatif, transcription Voxtral (docs/42)** | ✅ TERMINÉ + **fusionné dans `main`** (2026-07-21) — code + tests (1046 passed sur `main`) + validation manuelle clé API réelle OK |
| **Réorganisation 1 dossier/réunion (docs/43)** | ✅ code + tests TERMINÉS et **fusionnés dans `main`** (2026-07-27, 1113 passed sur `main`). La migration a **déjà tourné sur les données réelles** de Sylvain (23 réunions → dossiers, collision `09-56`/`09-56-2` correctement séparée). Reste : validation fonctionnelle complète de l'UI avec le nouveau code (le 1ᵉʳ test manuel a été fait par erreur avec l'ancien code `main` d'avant fusion — cf. docs/43 §12). Correctif inclus : réunion active exclue du listing (ligne en double, § « Stockage des réunions »). |

## Packaging macOS (Phase 4) — pièges

- **Certificat local stable** `« debriefMeet Local »` (créé par `packaging/creer_certificat.sh`) — doit signer identiquement l'app ET le helper Swift à chaque build, sinon les permissions TCC (Micro + Enregistrement de l'écran) sont perdues.
- Vérifier : `codesign -dv dist/debriefMeet.app` — même Authority entre deux builds.
- Bundle id : `com.sylvaingarcia.debriefmeet` (aligné partout, y compris `demarrage_auto.py`, depuis 2026-07-02).
- **Pas d'auto-update en v1** — MAJ = re-téléchargement manuel du `.dmg`.
- La config (`platformdirs`) et les transcriptions (`~/Documents/debriefMeet`) vivent hors du bundle → survivent au remplacement.
- **ffmpeg embarqué (LGPL, `packaging/build_ffmpeg.sh`)** : à compiler une fois avant `build_app.sh` (binaire non versionné, `packaging/vendor/`). Piège configure : les demuxers/muxers PCM bruts s'activent sous leur nom **interne** (`pcm_f32le`, `pcm_s16le`), pas le nom court de `ffmpeg -demuxers` (`f32le`/`s16le`) ; `--disable-postproc` n'existe plus en ffmpeg 8.1.x.
- **`sys.executable` en app figée n'est pas un interpréteur Python générique** : `multiprocessing` (déclenché en interne par mlx/torch, ex. `resource_tracker`) le relance parfois en `-c "<code>"` pur → `__main__._relais_interprete_figee()` émule `python -c` avant tout autre routage (sinon bruit `unrecognized arguments`, sans casser la transcription).
- Premier `codesign` réel après création du certificat : peut afficher une popup trousseau **invisible aux API de scripting/accessibilité** (fenêtre sécurisée) — nécessite un clic humain une fois (« Toujours autoriser »), aucun moyen de la détecter ou franchir en automatique.

## Build Windows (benchmark + Phase 5)

**Le build se fait en natif sur la VM Proxmox, jamais en cross-compile depuis le Mac.**

- VM : `192.168.1.29`, SSH `sylvaing` (mot de passe hors dépôt)
- Script benchmark : `scripts/build_windows_vm.sh`
- Script spike backends : `scripts/build_spike_backends_vm.sh` ← Phase 5
- **Script app (setup installeur) : `scripts/build_app_windows_vm.sh`** ← Phase 5 (docs/32) — rsync
  sources + `BUILD_INFO` (date+hash git), pytest bloquant sur la VM, PyInstaller onedir
  (`packaging/windows/debriefMeet.spec`), Inno Setup (`packaging/windows/debriefMeet.iss`),
  rapatrie `dist/debriefMeet-setup-<version>.exe`.
  Prérequis VM à installer une fois : Python 3.13 x64, Inno Setup 6 (`ISCC.exe`,
  souvent installé per-user par winget sous `%LOCALAPPDATA%\Programs\Inno Setup 6\`,
  pas forcément `Program Files (x86)`).
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
| AEC (WebRTC/livekit) | `docs/06` |
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
| **Interco Mistral (CR cloud adaptatif, transcription Voxtral) — ✅ terminé, validé manuellement, fusionné dans `main`** | `docs/42` |
| **Réorganisation 1 dossier/réunion — ✅ terminé, fusionné dans `main`, migration réelle passée** | `docs/43` |
