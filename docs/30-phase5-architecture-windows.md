# Phase 5 — Architecture du portage Windows (doc chapeau)

> **Statut : 📝 SPEC à implémenter** (rédigée le 2026-07-03, décisions arbitrées avec
> Sylvain le 2026-07-03). Ce document est le **chapeau** de la Phase 5 : il fixe le
> périmètre, l'architecture cible et l'ordre d'exécution. Les specs détaillées sont
> dans les docs 31 à 35. À exécuter par une session LLM (Sonnet) **dans l'ordre du §6**.

---

## 1. Contexte et contrainte structurante

Le développeur (Sylvain) travaille sur macOS et **ne dispose d'aucune machine Windows
de développement**. Le seul environnement Windows est la VM Proxmox de build
(`192.168.1.29`, cf. CLAUDE.md) et les machines des utilisateurs finaux (Bastien : AMD
Ryzen 5 PRO 5675U + iGPU Radeon ; Alix : Intel i5-1235U + iGPU Intel UHD — pas de
NVIDIA).

Conséquences architecturales (décisions actées) :

1. **Les logs sont le seul canal de debug.** Sur Windows, les logs sont **activés en
   DEBUG par défaut**, avec numéro de version+build dans chaque session et un export
   diagnostic en un clic → **docs/31**.
2. **Chaque livraison est un exécutable installable** (Inno Setup) : mise à jour par
   réinstallation par-dessus, désinstallation complète → **docs/32**. ⚠️ Ceci **révise
   docs/03** qui prévoyait « v1 = ZIP portable, installeur reporté ».
3. **Les utilisateurs sont le banc de test** : chaque livraison s'accompagne d'une
   checklist et d'une procédure de remontée d'incident → **docs/35**.

## 2. Décisions arbitrées (2026-07-03)

| # | Décision | Détail |
|---|----------|--------|
| D1 | **Installeur Inno Setup en v1** | Per-user, sans droits admin, sans certificat Authenticode (avertissement SmartScreen assumé et documenté). Révise docs/03. |
| D2 | **CPU d'abord, iGPU en plugin ensuite** | v1 = `faster-whisper` CPU (socle universel, fiable). L'accélération iGPU (OpenVINO/DirectML/Vulkan) sera un second moteur derrière la même interface, activé par la table d'auto-sélection quand le rapport spike (docs/18, Bastien/Alix) sera disponible. La première livraison peut être CPU-only ; le RTF loggé dira si c'est tenable. |
| D3 | **Raccourcis globaux inclus en v1** | `RegisterHotKey` (user32). Défauts Windows : `Ctrl+Alt+D/R/J`. |
| D4 | **Désinstallation complète sauf données utilisateur** | Supprime : app, config, logs, modèles téléchargés, entrée autostart. **Préserve : `Documents\debriefMeet`** (transcriptions + fichiers audio). |
| D5 | **Logs DEBUG par défaut sur Windows uniquement** | macOS conserve son comportement actuel (logs off par défaut). |
| D6 | **Diagnostic zip sur le Bureau** | Contient logs + infos système + config. Jamais de texte transcrit dans les logs. |

## 3. Périmètre fonctionnel v1 Windows

- **Dictée** ✅ (pipeline identique à macOS : micro commun + moteur + presse-papiers)
- **Réunion avec AEC** ✅ (capture système = loopback WASAPI via `soundcard`)
- **Journal** ✅ — coût marginal quasi nul : il réutilise le pipeline dictée
  (micro + moteur + fichiers). S'il apparaît un blocage spécifique, le reporter
  sans bloquer la livraison Dictée+Réunion.
- **Diarization** ❌ hors v1 (conforme docs/03, docs/29 sans objet sur Windows v1)
- **Raccourcis globaux** ✅ (D3)
- **Démarrage automatique** ✅ (Registre `HKCU\...\Run`)

## 4. Architecture cible

### 4.1 Rappel de la règle d'or (inchangée)

`core/` n'importe **jamais** de module OS-spécifique (`winreg`, `ctypes` Win32,
`soundcard`, `faster_whisper`…). Toute dépendance plateforme passe par
`platform/interfaces.py`. Les collectes d'informations système OS-spécifiques
(GPU, RAM, build Windows — cf. docs/31) vivent dans `platform/`, pas dans `core/`.

### 4.2 Arborescence à créer

```
src/debrief_meet/platform/windows/
├── __init__.py
├── moteur_faster_whisper.py    # MoteurTranscription — worker subprocess (cf. docs/34 §1)
├── _fw_worker.py               # worker enfant faster-whisper (miroir de macos/_mlx_worker.py)
├── selection_backend.py        # détection matériel + table d'auto-sélection (v1 : CPU)
├── capture_systeme_wasapi.py   # CaptureAudioSysteme — loopback via soundcard
├── presse_papiers.py           # PressePapiers — QClipboard
├── demarrage_auto.py           # DemarrageAuto — winreg HKCU Run
├── raccourcis_win32.py         # RaccourcisGlobaux — RegisterHotKey + nativeEventFilter
├── instance_unique.py          # mutex Win32 nommé (single-instance + AppMutex Inno)
└── infos_systeme.py            # collecte OS/CPU/GPU/RAM pour l'en-tête de logs (docs/31)
```

Modules **réutilisés tels quels** (aucune modification attendue) :

- `platform/commun/micro_sounddevice.py` — PortAudio est cross-platform ; porte déjà
  les fixes docs/20 (16 kHz constant) et docs/25 (hot-plug).
- `platform/commun/surveillant_peripheriques.py` — Qt Multimedia, cross-platform.
- Tout `core/` — y compris `arret_threads.py` (docs/26), `audio.preparer_asr` (docs/27).

### 4.3 Fabrique — `platform/factory.py`

Remplacer le corps de `_windows()` (actuellement 100 % stubs, `factory.py:100-109`)
par le même motif que `_macos()` : import paresseux de chaque adaptateur dans un
`try/except ImportError` → repli stub + log WARNING (sur Windows, un repli stub est
un événement grave à voir dans les logs, pas un silence).

Le moteur est choisi via `selection_backend.py` :

```
selectionner_backend(config) -> ("faster-whisper", options)   # v1 : toujours ça
```

- Nouvelle clé de config : `"backend": "auto"` (valeurs futures : `"auto"`,
  `"faster-whisper"`, `"openvino"`, `"directml"`, `"vulkan"`). En v1, toute valeur
  autre que `"auto"`/`"faster-whisper"` retombe sur faster-whisper avec un WARNING.
- Même en v1 CPU-only, `selection_backend.py` **détecte et logge** le matériel
  (CPU vendor/modèle, iGPU présents, RAM) : ces logs des machines utilisateurs
  alimenteront la table d'auto-sélection définitive une fois le rapport spike rendu.

### 4.4 Moteur : pattern « worker subprocess » (décision d'architecture)

`faster-whisper` s'exécute normalement in-process. **On choisit de le faire tourner
dans un sous-processus worker**, en miroir exact de `macos/moteur_mlx.py` +
`_mlx_worker.py`, pour trois raisons :

1. **Sémantique d'arrêt uniforme (docs/26)** : le registre de workers + `kill()`
   forcé fonctionne à l'identique. In-process, une transcription bloquée serait
   intuable (GIL) → retour du crash QThread.
2. **Isolation des crashs natifs** : un crash de DLL (ctranslate2, drivers) tue le
   worker, pas l'app — c'est vital quand on ne peut pas déboguer sur place.
3. **Un seul motif à maintenir** : chargement paresseux, pool, pickle stdin/stdout —
   déjà éprouvés.

Détail dans **docs/34 §1**.

### 4.5 Stockage des modèles (spécifique Windows)

Sur Windows, `download_root` de faster-whisper est forcé vers
`%LOCALAPPDATA%\debriefMeet\modeles` (et **pas** le cache Hugging Face global
`~/.cache/huggingface`). Raison : la désinstallation complète (D4) doit pouvoir
supprimer les modèles sans risquer d'effacer le cache HF partagé avec d'autres
applications. Cf. docs/32 §5 et docs/34 §1.

### 4.6 Versions Python

| Contexte | Python |
|----------|--------|
| Dev quotidien Mac | `.venv` 3.14 (inchangé) |
| Build Windows sur la VM | **3.13** (aligné sur `.venv-build` : PyInstaller ne supporte pas 3.14) |

## 5. Prérequis avant tout développement Phase 5

1. **Durcissement `OrchestrateurReunion._demarrer()`** : envelopper la séquence de
   démarrage dans un try/except avec rollback (arrêt des captures déjà démarrées si
   une étape échoue). C'était déjà un préalable listé dans docs/03. (~20 min + 1 test.)
2. **Vérifier la disponibilité de la roue AEC sur Windows** : la lib WebRTC/livekit
   utilisée par `core/aec.py` (cf. docs/06) doit avoir un wheel `win_amd64` Python
   3.13. Si oui → rien à faire (module commun). Si non → la Réunion démarre **sans
   AEC** avec un WARNING loggé (jamais un blocage), et on documente la limite.
   Cette vérification se fait par recherche PyPI, sans machine Windows.

## 6. Ordre d'exécution des specs (dépendances)

| Ordre | Doc | Contenu | Dépend de |
|-------|-----|---------|-----------|
| 1 | **docs/31** | Observabilité : logs DEBUG Windows, `_version.py` build, en-tête session, crash handler, export diagnostic | — |
| 2 | **docs/33** | Transposition des correctifs macOS → exigences et tests Windows | — (analyse, aucune ligne de code) |
| 3 | **docs/34** | Les adaptateurs Windows (moteur, capture système, presse-papiers, autostart, raccourcis, mutex) | 31 (ce qu'il faut logger), 33 (exigences) |
| 4 | **docs/32** | Packaging : PyInstaller onedir + Inno Setup, cycle install/update/uninstall | 31 (`_version.py`), 34 (mutex `AppMutex`) |
| 5 | **docs/35** | Livraison : checklist utilisateur, notice SmartScreen, procédure incident, cadence | 31, 32 |

docs/31/33/34 se développent et se testent **sur le Mac** (tout est mocké, la suite
`pytest -m "not integration"` doit rester verte, y compris les nouveaux tests Windows
qui mockent `sys.platform`/`winreg`/`soundcard`). docs/32 nécessite la VM.

## 7. Definition of Done — Phase 5 v1

- [ ] Suite `pytest -m "not integration"` verte sur Mac **et** sur la VM Windows.
- [ ] `debriefMeet-setup-<version>.exe` produit par la chaîne de build VM (docs/32).
- [ ] Install → l'app démarre, tray visible, en-tête de session dans les logs.
- [ ] Dictée, Réunion (AEC si roue dispo), Journal fonctionnels sur la VM (micro
      virtuel ou test utilisateur).
- [ ] Réinstallation par-dessus : config et transcriptions préservées.
- [ ] Désinstallation : tout supprimé sauf `Documents\debriefMeet`.
- [ ] « Exporter le diagnostic » produit un zip exploitable sur le Bureau.
- [ ] Notice utilisateur (docs/35) livrée avec le premier setup.

## 8. Hors périmètre v1 (rappels explicites)

- Accélération iGPU (attend le rapport spike docs/18 — l'architecture est prête, §4.3).
- Diarization.
- Signature Authenticode / suppression de l'avertissement SmartScreen.
- Auto-update intégré (même politique que macOS : réinstallation manuelle).
