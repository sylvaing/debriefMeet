# Phase 4 — Packaging macOS (`.app` + `.dmg`)

> **Statut au 2026-07-12 :** 🟡 **en cours** — fondations code + outillage faits et
> testés ; **build PyInstaller non encore validé** (mis en pause le 2026-06-30).
> Préparation d'un run autonome faite le 2026-07-12 : **certificat créé et validé**
> (§4, aucune interaction requise), **décision ffmpeg tranchée** (§5.5, option b —
> build LGPL minimal compilé par nous, bundlé), **item notifications ajouté** à la
> checklist (§6.8). Ce document est autoporteur :
> une autre session doit pouvoir reprendre à partir d'ici sans contexte
> supplémentaire — seul §6 (validation TCC) reste manuel, par conception.
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
- **Pas de mise à jour distante / auto-update** en v1. **Pas de check de version**.
  La MAJ = l'utilisateur **retélécharge le `.dmg`** et glisse la nouvelle `.app`
  par-dessus l'ancienne dans `/Applications`.
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

## 5. Point de reprise — reste à faire

> Ordre conseillé. Tout se lance depuis la racine du dépôt, avec `.venv-build`.

### 5.1 Valider le build PyInstaller (partie tâtonnante)

```bash
.venv-build/bin/pyinstaller packaging/debriefMeet.spec --noconfirm \
    --distpath dist --workpath build/work
```

Puis lancer `dist/debriefMeet.app/Contents/MacOS/debriefMeet` en terminal pour voir
les erreurs d'import. **Itérer** : ajouter les modules manquants dans
`hiddenimports`/`collect_all` de la spec (suspects classiques : sous-modules
`pyannote`, `lightning`, `speechbrain`, plugins `torchaudio`). Vérifier que :
- le tray apparaît,
- le worker MLX démarre (transcription dictée),
- le helper SCK est trouvé (`Contents/Resources/helpers/macos/sck-audio/SCKAudioCapture`).

### 5.2 `packaging/build_app.sh` (à écrire)

Orchestration signature **stable** :
1. `bash packaging/creer_certificat.sh` (idempotent).
2. Recompiler le helper signé stable : `CODESIGN_IDENTITY="debriefMeet Local" bash helpers/macos/sck-audio/build.sh`.
3. `pyinstaller … debriefMeet.spec`.
4. Signer l'app : `codesign --force --deep --sign "debriefMeet Local" dist/debriefMeet.app`
   (⚠️ **pas** `--options runtime` : mlx/torch ont besoin de mémoire exécutable non signée ; le hardened runtime n'est requis que pour la notarisation, hors périmètre).
5. Re-signer le helper avec ses entitlements : `codesign --force --sign "debriefMeet Local" --entitlements helpers/macos/sck-audio/entitlements.plist dist/debriefMeet.app/Contents/Resources/helpers/macos/sck-audio/SCKAudioCapture`.
6. Re-sceller l'app (sans `--deep`) : `codesign --force --sign "debriefMeet Local" dist/debriefMeet.app`.
7. Vérifier : `codesign -dv --verbose=4 dist/debriefMeet.app` → noter l'**Authority**. Rebuild → l'Authority doit être **identique** (preuve que TCC tiendra).

### 5.3 `packaging/build_dmg.sh` (à écrire)

```bash
VERSION=$(.venv-build/bin/python -c "import debrief_meet; print(debrief_meet.__version__)")
create-dmg --volname "debriefMeet" --app-drop-link 450 180 \
    "dist/debriefMeet-$VERSION.dmg" "dist/debriefMeet.app"
```
(lien `/Applications` pour l'install par glisser-déposer).

### 5.4 Makefile + autostart en contexte bundle

- Ajouter cibles `build-app` et `dmg` (utilisant `.venv-build`).
- `platform/macos/demarrage_auto.py` :
  - **Aligner le bundle id** : ✅ fait (2026-07-02) — `_BUNDLE_ID = "com.sylvaingarcia.debriefmeet"` (cohérence avec la spec ; sinon label LaunchAgent incohérent). Confirmé par l'audit externe ([`audits-externes/21`](audits-externes/21-audit-recommandations.md) R1) : c'était à faire **avant** le premier build, sinon l'autostart pointe dans le vide et risque de dédoublement TCC.
  - En mode figé, faire pointer le LaunchAgent sur le binaire `.app` via `sys.executable` (et non `sys.argv[0]`, moins fiable une fois figé).

### 5.5 Décision ffmpeg dans l'app packagée (audit R7)

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
   (protocols `file,pipe` ; demuxers `s16le,ogg,wav` ; muxers `opus,ogg,wav,s16le` ;
   decoders `pcm_s16le,opus,libopus` ; encoders `pcm_s16le,libopus` ; filters
   `aresample,aformat,anull`) — **itérer avec les tests réels ci-dessous comme
   oracle** plutôt que de sur-raffiner la liste a priori.
   Validation obligatoire du binaire produit :
   - `otool -L ffmpeg` → uniquement `/usr/lib` + frameworks système (pas de
     `/opt/homebrew`) ;
   - `./ffmpeg -hide_banner -encoders | grep libopus` → présent ;
   - `./ffmpeg -version` → configuration **sans** `--enable-gpl` ;
   - test réel bout-en-bout : encode WAV→`.opus` avec la commande exacte de
     `core/fichiers.py`, puis décode avec celle de `core/audio.py`, et relire
     un `.opus` **historique** existant.
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

Tests attendus : `chemin_ffmpeg()` en mode figé simulé (monkeypatch
`est_figee`/`chemin_ressource`) et en dev ; erreur typée quand rien n'est
résolu ; `test_build.py` vérifie la présence de `vendor/ffmpeg` signé dans
l'app produite.

### 5.6 Doc & clôture

- Mettre ce statut à jour (→ ✅).
- Marquer **Phase 4 ✅** dans [`03-phases-implementation.md`](03-phases-implementation.md) (section + tableau Vue d'ensemble).

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
