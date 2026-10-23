# Phase 4 — Packaging macOS (`.app` + `.dmg`)

> **Statut au 2026-07-12 :** 🟢 **§5 terminé et validé en conditions réelles** sur
> cette machine (arm64, macOS 26.5.1) — reste **uniquement §6** (validation TCC
> manuelle : permissions Micro/Enregistrement de l'écran, ne peut pas être
> scriptée par conception).
>
> Réalisé le 2026-07-12 : `packaging/build_ffmpeg.sh` compile pour de vrai un
> ffmpeg LGPL minimal (§5.5, corrigé au passage : `--disable-postproc` obsolète,
> noms internes des demuxers/muxers `pcm_f32le`/`pcm_s16le` différents de la
> sortie `ffmpeg -demuxers`) ; `packaging/build_app.sh`/`build_dmg.sh` écrits et
> **exécutés réellement** — `dist/debriefMeet.app` build + signé (Authority
> `debriefMeet Local` stable, même leaf hash qu'à la création du certificat) +
> `dist/debriefMeet-0.2.0.dmg` (343 Mo) produits. App **lancée réellement** (pas
> seulement compilée) : tray, worker MLX (self-relaunch), helper SCK et ffmpeg
> embarqués tous trouvés en bundle. Un bug réel trouvé au lancement (bruit
> `unrecognized arguments` du bootstrap `multiprocessing.resource_tracker` sur
> `sys.executable` figé) corrigé dans `__main__._relais_interprete_figee` — cf.
> §5.1. `demarrage_auto.py` corrigé pour utiliser `sys.executable` en app figée
> (§5.4, item resté ouvert malgré le ✅ bundle id).
>
> Ce document est autoporteur : une autre session doit pouvoir reprendre à
> partir d'ici sans contexte supplémentaire.
>
> Références : [`03-phases-implementation.md`](03-phases-implementation.md) §Phase 4.

---

## 1. Objectif & décisions de cadrage

Livrer une **app installable** (`.dmg`) sur Mac Apple Silicon, avec des
**permissions stables** (Micro + Enregistrement de l'écran ne se redemandent pas
entre rebuilds ni après réinstallation).

Décisions actées (utilisateur) :

- **Cible** : macOS **14.4+**, **arm64** uniquement.
- **Bundle identifier** (définitif, ne doit **jamais** changer) : `com.sylvaingarcia.debriefmeet`.
- ~~Pas de mise à jour distante / auto-update en v1. Pas de check de version.~~
  **Révisé le 2026-10-23 (docs/53)** : vérification quotidienne du manifeste signé de
  la Release, et remplacement de la `.app` dans `/Applications` depuis un zip publié
  par la CI (même identité de signature ⇒ permissions TCC conservées). La MAJ
  manuelle (retélécharger le `.dmg`) reste possible.
- **Poids des modèles non embarqués** : mlx-whisper et pyannote les téléchargent à
  la volée (onboarding HF déjà en place — cf. [`13`](13-diarization-onboarding.md)).
- **Pas de notarisation** (post-v1) : signature **auto-signée locale stable**.

### Pourquoi la stabilité de la signature est l'enjeu #1

macOS (TCC) attribue les permissions à la **signature de code** d'une app, pas à
son chemin. Si tous les builds sont signés avec **le même certificat local**, la
nouvelle `.app` est vue comme « la même app » → **permissions conservées**. Si la
signature change (cas d'une signature ad-hoc régénérée), macOS redemande tout.

Les données (config via `platformdirs`, transcriptions dans `~/Documents/debriefMeet`)
vivent **hors du bundle** → elles survivent au remplacement de la `.app`.

---

## 2. Environnement de build

- **Venv dédié** : `.venv-build` à la racine, en **Python 3.13**.
  - Raison : le venv de dev `.venv` est en **Python 3.14**, non supporté de façon
    fiable par PyInstaller. Ne pas builder depuis `.venv`.
  - Création (déjà faite) :
    ```bash
    python3.13 -m venv .venv-build
    .venv-build/bin/pip install -e ".[macos]" pyinstaller
    ```
  - Contenu vérifié : pyinstaller **6.21**, torch 2.12, mlx 0.31, pyannote 4, livekit, PySide6 6.11 — tous importables.
- **`create-dmg`** : installé via Homebrew (`brew install create-dmg`).

---

## 3. Adaptations du code (faites, testées)

Trois points cassaient en app figée ; tous corrigés :

| Problème | Correctif | Fichier |
|---|---|---|
| Helper Swift localisé par chemin relatif au dépôt → introuvable en bundle | Module de résolution `chemin_ressource()` / `est_figee()` (dev vs `sys._MEIPASS`), **même chemin relatif** dans les deux modes | `core/ressources.py` (nouveau), `platform/macos/capture_systeme.py` |
| Worker MLX lancé via `python -m …_mlx_worker` → `-m` inexistant en bundle | App figée se **relance elle-même** : `[sys.executable, "--mlx-worker"]`, routé tôt dans `main()` avant Qt | `__main__.py`, `platform/macos/moteur_mlx.py` (`_commande_worker`) |
| Assets (police Tabler, SVG, icns) | Embarqués via la spec (cible `debrief_meet/ui/assets`) ; le code les lit déjà via `Path(__file__).parent/"assets"` (OK en onedir) | `packaging/debriefMeet.spec` |

Helper Swift **version production** (ex-POC restructuré comme prévu en Phase 0.5) :

- `helpers/macos/sck-audio/SCKAudioCapture.swift` (+ `build.sh`, `entitlements.plist`).
- `build.sh` signe avec `CODESIGN_IDENTITY` (défaut `-` ad-hoc ; le packaging passe l'identité stable).
- L'ancien `helpers/macos/poc-audio-tap/` est **conservé** (historique go/no-go).
- `Makefile` (`build-helpers`) et `tests/test_build.py` (`TestHelperSwift`) mis à jour.

Tests : `core/ressources.py` couvert par `tests/test_ressources.py`. Suite complète
**481 passed** (`.venv/bin/pytest -m "not integration"`).

---

## 4. Outillage de packaging (écrit)

Dans `packaging/` :

- **`launcher.py`** — point d'entrée du bundle (délègue à `debrief_meet.__main__.main`).
- **`debriefMeet.spec`** — spec PyInstaller :
  - `Analysis` sur `launcher.py`, `pathex=src`.
  - `datas` : dossier `ui/assets` + binaire `SCKAudioCapture`.
  - `collect_all` enveloppé par paquet pour les deps ML (mlx, mlx_whisper, pyannote(.audio), lightning, pytorch_lightning, asteroid_filterbanks, julius, torch_pitch_shift, torch_audiomentations, pytorch_metric_learning, speechbrain, livekit, huggingface_hub, tiktoken, transformers). torch/torchaudio/sounddevice/sklearn/numba via hooks contrib.
  - `excludes` : tkinter, pytest, matplotlib.
  - `BUNDLE` : `LSUIElement=True` (app barre de menus, pas de Dock), `bundle_identifier=com.sylvaingarcia.debriefmeet`, `LSMinimumSystemVersion=14.4`, `CFBundleShortVersionString`/`Version` lus depuis `__init__.py`, icône `ui/assets/icons/debriefMeet.icns` (refonte design, handoff — remplace l'ancien `AppIcon.icns` généré par `scripts/generer_icone.py`), `NSMicrophoneUsageDescription` + `NSAudioCaptureUsageDescription`.
- **`creer_certificat.sh`** — crée **une fois** l'identité de signature locale stable
  « debriefMeet Local » (clé RSA + cert auto-signé EKU codeSigning, importé au
  trousseau de session). **Idempotent** : ne régénère pas si présente (sinon les
  permissions seraient perdues).

  **✅ Exécuté et validé le 2026-07-12** — identité en trousseau, leaf hash
  `95fa8aa3da22a3ff5900164ae7f254fa3dbb31b2`, **identique entre deux signatures**
  (vérifié via `codesign -d -r-` : le requirement désigné épingle
  `certificate leaf = H"…"` — c'est ce que TCC compare). **Aucune popup
  trousseau** : l'ACL posée par `security import -T /usr/bin/codesign` suffit,
  codesign signe sans interaction. Trois pièges corrigés au passage dans le script :
  1. `security import` **refuse un p12 à mot de passe vide** (« MAC verification
     failed ») → mot de passe jetable (`uuidgen`), utilisé le temps de l'import ;
  2. utiliser `/usr/bin/openssl` (LibreSSL), pas l'openssl Homebrew ;
  3. le check d'idempotence ne doit **pas** utiliser `find-identity -v` : un cert
     auto-signé est `CSSMERR_TP_NOT_TRUSTED` donc exclu des identités « valides »
     → le script régénérait un cert à chaque run (= perte TCC). Sans `-v`, OK.
     (codesign signe très bien avec une identité non « trusted ».)

---

## 5. Point de reprise — ✅ terminé (2026-07-12)

> Tout se lance depuis la racine du dépôt, avec `.venv-build`.

### 5.1 Build PyInstaller — ✅ validé en conditions réelles

```bash
.venv-build/bin/pyinstaller packaging/debriefMeet.spec --noconfirm \
    --distpath dist --workpath build/work
```

**Build réussi du premier coup** (aucun hiddenimport manquant à ajouter — la spec
existante suffisait). `dist/debriefMeet.app/Contents/MacOS/debriefMeet` **lancé
réellement** en terminal :
- tray apparaît (LSUIElement, pas d'icône Dock) ;
- worker MLX démarre (self-relaunch `[sys.executable, "--mlx-worker"]`), pool=1 et
  pool=2 atteignent `READY` ;
- helper SCK trouvé (`Contents/Resources/helpers/macos/sck-audio/SCKAudioCapture`,
  signé, `Authority=debriefMeet Local`) ;
- ffmpeg embarqué trouvé (`Contents/Resources/vendor/ffmpeg`, symlink PyInstaller
  vers `Contents/Frameworks/vendor/ffmpeg`, signé).

**Bug réel trouvé et corrigé** (uniquement visible en app figée, invisible en
dev) : au démarrage du worker MLX, `multiprocessing.resource_tracker` (déclenché
en interne par mlx/torch) relance `sys.executable` en mode `-c` pur
(`-B -S -I -c "from multiprocessing.resource_tracker import main;main(11)"`).
Notre binaire figé n'est pas un interpréteur générique : ces flags atterrissaient
dans l'argparse de `__main__._parser`, qui échouait avec `unrecognized arguments`
(bruit dans les logs, sans casser la transcription — le worker atteignait quand
même `READY`). Corrigé en émulant `python -c` : `__main__._relais_interprete_figee()`
détecte `-c` dans `sys.argv` et `exec()` le code reçu avant tout le reste (routage
placé avant même le check `--mlx-worker`). Confirmé par un relancement réel :
0 occurrence de `unrecognized arguments`/`resource_tracker` dans les logs après
correctif, workers toujours `READY`. Tests : `tests/test_main_relais_interprete.py`.

### 5.2 `packaging/build_app.sh` — ✅ écrit et exécuté réellement

Orchestration signature **stable**, implémentée telle que prévue (identité →
helper → PyInstaller → signature app `--deep` sans `--options runtime` →
re-signature helper avec entitlements → **signature du binaire ffmpeg embarqué**
→ re-scellage sans `--deep` → vérification). Exécutée deux fois de suite sur
cette machine : `Authority=debriefMeet Local` les deux fois, et le leaf hash
(`codesign -d -r-`) est **identique** à celui relevé à la création du certificat
(§4) — preuve concrète que TCC conservera les permissions entre rebuilds.

⚠️ Piège rencontré (à anticiper pour une prochaine machine) : le **premier**
`codesign` réel avec l'identité (celui du helper, dans `build_app.sh`) peut
déclencher une popup système "codesign veut accéder à une clé…" **invisible aux
API d'accessibilité/scripting** (fenêtre sécurisée du trousseau) — un script ou
un agent ne peut ni la détecter ni la fermer. Un humain doit cliquer **Toujours
autoriser** une fois ; ensuite tous les codesign suivants passent sans popup.

### 5.3 `packaging/build_dmg.sh` — ✅ écrit et exécuté réellement

```bash
VERSION=$(.venv-build/bin/python -c "import debrief_meet; print(debrief_meet.__version__)")
create-dmg --volname "debriefMeet" --app-drop-link 450 180 \
    "dist/debriefMeet-$VERSION.dmg" "dist/debriefMeet.app"
```
(lien `/Applications` pour l'install par glisser-déposer). Produit réellement :
`dist/debriefMeet-0.2.0.dmg` (343 Mo, compression 75,5 %).

### 5.4 Makefile + autostart en contexte bundle — ✅ fait

- Cibles `build-app` et `dmg` ajoutées (utilisant `.venv-build`).
- `platform/macos/demarrage_auto.py` :
  - **Aligner le bundle id** : ✅ fait (2026-07-02) — `_BUNDLE_ID = "com.sylvaingarcia.debriefmeet"` (cohérence avec la spec ; sinon label LaunchAgent incohérent). Confirmé par l'audit externe ([`audits-externes/21`](audits-externes/21-audit-recommandations.md) R1) : c'était à faire **avant** le premier build, sinon l'autostart pointe dans le vide et risque de dédoublement TCC.
  - **En mode figé, LaunchAgent → `sys.executable`** : ✅ fait (2026-07-12) — `activer()` utilise `sys.executable` si `est_figee()`, sinon `sys.argv[0]` (dev, inchangé). Tests : `tests/test_demarrage_auto_macos.py`.

### 5.5 Décision ffmpeg dans l'app packagée (audit R7) — ✅ implémenté et compilé réellement

> Issue de la contre-analyse de l'audit externe ([`audits-externes/21`](audits-externes/21-audit-recommandations.md) R7).

**Constat :** la rétention audio choisit Opus si ffmpeg est trouvé, sinon repli WAV
(`core/fichiers.py`, `_ffmpeg_present()` via `shutil.which`). Or une app lancée
depuis le **Finder** hérite d'un `PATH` minimal (`/usr/bin:/bin:…`) **sans**
`/opt/homebrew/bin` → dans le bundle, `shutil.which("ffmpeg")` échoue *même si
ffmpeg est installé via brew*. Conséquences :

1. **Rétention en WAV** depuis l'app installée (fichiers ~10× plus gros, pas bloquant) ;
2. **`.opus` historiques illisibles** depuis l'app (enregistrés du temps du venv de
   dev, où ffmpeg était dans le PATH) → transcription différée / diarization en
   échec avec un `FileNotFoundError` cryptique (`core/audio.py`, `_decoder_ffmpeg`).

**✅ Tranché (utilisateur, 2026-07-12) : option (b) — bundler ffmpeg dans la `.app`.**

L'app packagée est ainsi **autonome** (Opus garanti, `.opus` historiques toujours
relisibles), sans dépendance à un brew de la machine cible (Bastien/Alix n'auront
pas brew).

1. **Binaire à embarquer : ffmpeg minimal LGPL, compilé par nous** (arm64,
   liaison statique de libopus, libs système en dynamique — normal sur macOS).
   Pas de prébuild communautaire : ils sont quasi tous « full GPL »
   (`--enable-gpl`), et le binaire brew est inutilisable (dylibs `/opt/homebrew`
   non portables). Ce que le code utilise réellement (cf. `core/fichiers.py`
   encodage `-f s16le … -c:a libopus` → `.opus`, et `core/audio.py` décodage
   `.opus`/autres → PCM 16k mono) tient entièrement dans le périmètre LGPL :
   configure de départ —
   `--disable-gpl --disable-nonfree --disable-everything --disable-doc
   --disable-ffplay --disable-ffprobe --enable-libopus` + activation sélective
   (protocols `file,pipe` ; demuxers `pcm_f32le,pcm_s16le,ogg,wav` — noms internes
   du build system, différents des noms courts affichés par `ffmpeg -demuxers`
   (`f32le`/`s16le`) : utiliser `./configure --list-demuxers`/`--list-muxers`
   comme référence, pas la sortie runtime ; muxers `opus,ogg,wav,pcm_s16le,segment` ;
   decoders `pcm_f32le,pcm_s16le,opus,libopus` ; encoders `pcm_s16le,libopus` ;
   filters `aresample,aformat,anull,aselect,asetpts`) — **itérer avec les tests réels
   ci-dessous comme oracle** plutôt que de sur-raffiner la liste a priori.
   ⚠️ `aselect,asetpts` ont été **ajoutés le 2026-08-18** : la compaction des silences
   avant envoi à Voxtral (docs/42 §10.2, mise en service en août) en dépend, et personne
   n'avait revisité cette liste — elle échouait donc à tous les coups dans l'app livrée,
   et jamais en dev où répond le ffmpeg Homebrew complet. **Toute nouvelle invocation de
   ffmpeg dans le code oblige à revenir ici** : ce build ne connaît que les usages qui
   existaient le jour où il a été écrit, et un composant manquant ne se voit qu'en
   production.
   ⚠️ **Deuxième occurrence, exactement la même**, le 2026-09-02 : le muxer `segment`
   manquait, donc le **repli découpage** de Voxtral (docs/42 §10.4) échouait dans l'app
   livrée depuis toujours. Il n'avait jamais tiré sur macOS avant que le repli sur 5xx
   ne soit câblé (docs/42 §10.1, 2026-08-31) ; à son premier déclenchement réel, le CR
   d'une réunion de 1 h 52 a été perdu. Sans ce muxer, ffmpeg ne reconnaît même pas
   l'option `-segment_time` et sort en **8** (« Unrecognized option »), ce qui ne
   ressemble en rien à « composant absent ». Deux occurrences en trois semaines : la
   règle ci-dessus n'est pas théorique, et la liste `--enable-*` est le premier endroit
   à rouvrir dès qu'une invocation de ffmpeg est ajoutée au code.
   Validation obligatoire du binaire produit :
   - `otool -L ffmpeg` → uniquement `/usr/lib` + frameworks système (pas de
     `/opt/homebrew`) ;
   - `./ffmpeg -hide_banner -encoders | grep libopus` → présent ;
   - `./ffmpeg -hide_banner -filters` → `aselect` et `asetpts` présents. `return 1` et
     non `err` dans `valider_binaire` : sur le chemin idempotent, un binaire déjà là mais
     dépourvu de ces filtres doit être **reconstruit**, pas réutilisé — c'est ce qui
     rattrape automatiquement un `packaging/vendor/ffmpeg` d'avant le 2026-08-18 ;
   - `./ffmpeg -hide_banner -muxers` → `segment` présent, même mécanique de `return 1`
     (rattrape un binaire d'avant le 2026-09-02) ;
   - `./ffmpeg -version` → configuration **sans** `--enable-gpl` ;
   - test réel bout-en-bout : encode WAV→`.opus` avec la commande exacte de
     `core/fichiers.py`, puis décode avec celle de `core/audio.py`, et relire
     un `.opus` **historique** existant ;
   - test réel de compaction : les **deux passes** de `compacter_piste`
     (`aselect`+`asetpts` → WAV, puis WAV → Opus) avec la syntaxe exacte de l'app. La
     seule présence des filtres ne dit pas que la chaîne complète fonctionne.
   - test réel de découpage : la commande exacte de `decouper_piste`. Là encore la
     présence du muxer ne suffit pas — `-f segment` délègue à un **muxer enfant** déduit
     de l'extension de sortie (ici `opus`), qui doit être présent lui aussi.
2. **Script de build** : `packaging/build_ffmpeg.sh` — télécharge les sources
   (ffmpeg + libopus, **versions et checksums SHA-256 épinglés**), compile
   libopus statique puis ffmpeg, dépose le binaire en `packaging/vendor/ffmpeg`
   (**git-ignoré**, ~5-10 Mo). Idempotent (ne rebuilde pas si le binaire validé
   est présent). `build_app.sh` échoue avec un message clair si le binaire
   manque (→ « lancer packaging/build_ffmpeg.sh »).
3. **Spec PyInstaller** : ajouter aux `datas` → `Contents/Resources/vendor/ffmpeg`
   (même motif que le helper SCK).
4. **Signature** (`build_app.sh`) : signer le binaire avec l'identité stable,
   comme le helper (pas d'entitlements particuliers), **avant** le re-scellage
   final de l'app.
5. **Résolution côté code** : centraliser dans **une** fonction (ex.
   `core/fichiers.chemin_ffmpeg()`) : si `est_figee()` → binaire embarqué (via
   `core/ressources.chemin_ressource`), sinon `shutil.which("ffmpeg")` (dev).
   Remplacer les **deux** invocations `"ffmpeg"` nues (`core/fichiers.py`
   encodage, `core/audio.py` `_decoder_ffmpeg`). Le repli WAV existant reste
   pour le dev sans ffmpeg.
6. **Erreur typée** à la relecture d'un `.opus` sans ffmpeg résolu (« ffmpeg
   requis pour relire l'audio Opus ») au lieu du `FileNotFoundError` brut,
   remontée proprement à l'UI (dialogue gabarit §8.9) — cas devenu improbable
   en bundle mais garde-fou (binaire manquant/corrompu, dev).
7. **Licence** : le build maison est **LGPL** (aucun composant GPL activé,
   libopus = BSD). L'app l'invoque en **subprocess** (programme séparé, simple
   agrégation — aucune contamination du code de l'app). Obligations restantes,
   légères : embarquer le texte de licence (`Contents/Resources/vendor/
   LICENSE-ffmpeg.md` : LGPL 2.1 + mention libopus BSD + versions exactes des
   sources, dont l'URL est déjà épinglée dans `build_ffmpeg.sh`) et le
   mentionner dans la notice utilisateur.

Options écartées : (a) étendre la résolution aux chemins brew (garde la
dépendance implicite à brew sur chaque machine cible), (c) assumer le WAV
(fichiers ~10×, casse la relecture des `.opus` historiques).

**✅ Réalisé et validé le 2026-07-12** (versions épinglées : ffmpeg 8.1.2,
libopus 1.6.1 statique — checksums SHA-256 dans `build_ffmpeg.sh`) :
- binaire produit : 2,3 Mo, `otool -L` = uniquement `/usr/lib` + frameworks
  système, `-version` sans `--enable-gpl`, `-encoders` contient `libopus` ;
- cycle réel encode (PCM f32le → `.opus` via `libopus`) → décode (`.opus` → WAV
  16 kHz mono) exécuté avec les commandes exactes de `core/fichiers.py`/`core/audio.py` ;
- `chemin_ffmpeg()` testé en mode figé simulé et en dev (`tests/test_fichiers.py`),
  erreur typée `ErreurFfmpegIntrouvable` testée côté encodage et décodage
  (`tests/test_fichiers.py`, `tests/test_audio.py`) ;
- `tests/test_build.py::TestFfmpegVendor` vérifie (quand le binaire est présent :
  skip sinon, il n'est pas produit par `make setup`) l'absence de dylib Homebrew,
  l'absence de `--enable-gpl`, la présence de `libopus` ;
- signé dans l'app produite avec l'identité stable (`build_app.sh` §5.2),
  `Authority=debriefMeet Local` confirmé via `codesign -dv`.

Trois pièges de configure (documentés dans le point 1 ci-dessus après coup) :
`--disable-postproc` n'existe plus en ffmpeg 8.1.x ; les demuxers/muxers raw PCM
doivent être activés sous leur nom **interne** (`pcm_f32le`, `pcm_s16le`) et non le nom
court affiché par `ffmpeg -demuxers` ; et la liste des filtres **se périme** quand le
code gagne un usage de ffmpeg (`aselect,asetpts` ajoutés le 2026-08-18, cf. point 1).
Les deux premiers cassaient le build, bruyamment. Le troisième ne cassait que
l'exécution **chez l'utilisateur**, silencieusement : c'est le seul des trois qui a
vécu des semaines sans être vu.

### 5.6 Doc & clôture

- Statut de ce document mis à jour (→ §5 ✅, 2026-07-12).
- `03-phases-implementation.md` mis à jour : Phase 4 reste 🔄 tant que §6
  (validation manuelle TCC, ci-dessous) n'a pas été rejouée par Sylvain sur le
  `.dmg` réellement produit — mais tout le travail scriptable est fait.

---

## 6. Validation manuelle (utilisateur — TCC non scriptable)

Checklist à jouer une fois le `.dmg` produit :

1. Monter le `.dmg`, glisser **debriefMeet** dans Applications, lancer (1er lancement non notarisé : clic droit → Ouvrir).
2. Accorder **Micro** puis, au 1er mode Réunion, **Enregistrement de l'écran** — **une seule fois**.
3. Quitter, relancer → permissions **conservées** (pas de redemande).
4. **Rebuild + réinstaller par-dessus** (glisser, Remplacer) → permissions **et** données (`~/Documents/debriefMeet`, config) **conservées**.
5. Les **3 modes** fonctionnent depuis l'app installée (Dictée, Réunion, Journal).
6. **Autostart** : activer dans Préférences → vérifier le LaunchAgent (`~/Library/LaunchAgents/com.sylvaingarcia.debriefmeet.plist`) et le redémarrage de session.
7. **Raccourcis globaux** (`docs/28`) : depuis l'app packagée, ⌃⌥⌘D/R/J basculent bien les 3 modes même sans focus, et un changement dans Préférences → Raccourcis prend effet sans redémarrer.
8. **Notifications natives** : déclencher une notification (fin de diarization, ou
   « rien entendu » sur une dictée muette) → macOS affiche la **demande
   d'autorisation** au premier envoi (Qt la fait via `UNUserNotificationCenter`
   au premier `showMessage` — ne fonctionne **que** bundlé, jamais en dev
   `python -m debrief_meet`), **debriefMeet apparaît** dans Réglages Système →
   Notifications, et la bannière s'affiche. Vérifier aussi que le **clic** sur la
   notification ouvre l'Historique sur la bonne réunion. Si aucune demande
   d'autorisation n'apparaît : bug à traiter avant clôture (demander
   l'autorisation explicitement au premier lancement).

---

## 7. Procédure de mise à jour (à communiquer à l'utilisateur final)

Sans mécanique de MAJ : **retélécharger le `.dmg`**, le monter, glisser la nouvelle
`debriefMeet` sur `/Applications` et **Remplacer**. Tant que le build est signé avec
l'identité « debriefMeet Local » stable, les permissions ne sont pas redemandées et
l'historique/les réglages sont préservés.
