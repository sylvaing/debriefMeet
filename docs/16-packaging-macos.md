# Phase 4 — Packaging macOS (`.app` + `.dmg`)

> **Statut au 2026-06-30 :** 🟡 **en cours** — fondations code + outillage faits et
> testés (suite dev **481 passed**) ; **build PyInstaller non encore validé**
> (mis en pause). Ce document est autoporteur : une autre session doit pouvoir
> reprendre à partir d'ici sans contexte supplémentaire.
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
  permissions seraient perdues). Premier `codesign` ensuite → macOS demande
  d'autoriser l'accès au trousseau (**Toujours autoriser**, une seule fois).

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

**À trancher pendant la validation du build (§5.1), trois options :**

- **(a) Étendre la résolution** : chercher ffmpeg aussi dans les emplacements connus
  (`/opt/homebrew/bin`, `/usr/local/bin`) au lieu du seul PATH — le moins cher,
  garde la dépendance implicite à brew ;
- **(b) Bundler ffmpeg** dans le `.app` (+ ~25 Mo, licence LGPL à vérifier selon le build) ;
- **(c) Assumer le WAV** dans l'app packagée et documenter.

Dans tous les cas : remplacer le `FileNotFoundError` brut à la **relecture** d'un
`.opus` par une erreur typée avec message explicite (« ffmpeg requis pour relire
l'audio Opus »).

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

---

## 7. Procédure de mise à jour (à communiquer à l'utilisateur final)

Sans mécanique de MAJ : **retélécharger le `.dmg`**, le monter, glisser la nouvelle
`debriefMeet` sur `/Applications` et **Remplacer**. Tant que le build est signé avec
l'identité « debriefMeet Local » stable, les permissions ne sont pas redemandées et
l'historique/les réglages sont préservés.
