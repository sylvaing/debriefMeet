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

## Commandes essentielles

```bash
make setup          # venv .venv (Python dev) + deps + build helper Swift
make test           # pytest sans matériel (~5 s) ← toujours lancer avant livraison
make test-all       # suite complète (intégration incluse)
make build-helpers  # recompiler le helper Swift SCKAudioCapture
make run            # lancer l'app
```

Suite attendue : **589 passed** (au 2026-07-03).

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
| **4 — Packaging macOS** | 🔄 en pause (build pas encore lancé) |
| **4b — Modèle large-v3-turbo** | ✅ TERMINÉ (2026-06-30, turbo = modèle par défaut) |
| **5 — Spike backends Windows** | 🔄 code terminé (505 tests), build VM à lancer — **ne bloque plus la Phase 5** (v1 = CPU, cf. docs/30) |
| **5 — Portage Windows** | 🔄 EN COURS (docs/30→35, implémentation dans l'ordre docs/30 §6) — prérequis §5 ✅, docs/31 (observabilité) ✅, **docs/34 (adaptateurs) ✅ TERMINÉ** (2026-07-03, 667 passed) : factory Windows sans repli stub, moteur `MoteurFasterWhisper` (CPU int8, pool 1 worker, registre+kill docs/26), capture système WASAPI (`soundcard`), raccourcis `RegisterHotKey` (Ctrl+Alt+D/R/J), autostart (`winreg`), presse-papiers Qt, mutex instance unique ; revue croisée E-1→E-8 (docs/33) close ; reste à faire : docs/32 (packaging, nécessite la VM) puis docs/35 (livraison) |
| **Correctifs fuites CoreAudio (docs/23)** | ✅ TERMINÉ (2026-07-02, 530 passed) |
| **Robustesse micro hot-plug (docs/25)** | ✅ TERMINÉ (2026-07-02, 542 passed) |
| **Fix dictée/journal muets (docs/27)** | ✅ TERMINÉ (2026-07-02, 556 passed) |
| **Raccourcis globaux paramétrables (docs/28)** | ✅ TERMINÉ + validé manuellement (2026-07-02, 573 passed) |
| **Fix diarization pyannote 4.x (docs/29)** | ✅ TERMINÉ + validé manuellement (2026-07-02, 576 passed) — offline via `HF_HUB_OFFLINE`, `local_files_only` supprimé |
| **Fix crash QThread à l'arrêt (docs/26)** | ✅ TERMINÉ (2026-07-03, 589 passed) — registre workers MLX + kill forcé, helper `arreter_thread`/`proteger_thread` |

## Packaging macOS (Phase 4) — pièges

- **Certificat local stable** `« debriefMeet Local »` (créé par `packaging/creer_certificat.sh`) — doit signer identiquement l'app ET le helper Swift à chaque build, sinon les permissions TCC (Micro + Enregistrement de l'écran) sont perdues.
- Vérifier : `codesign -dv dist/debriefMeet.app` — même Authority entre deux builds.
- Bundle id : `com.sylvaingarcia.debriefmeet` (aligné partout, y compris `demarrage_auto.py`, depuis 2026-07-02).
- **Pas d'auto-update en v1** — MAJ = re-téléchargement manuel du `.dmg`.
- La config (`platformdirs`) et les transcriptions (`~/Documents/debriefMeet`) vivent hors du bundle → survivent au remplacement.

## Build Windows (benchmark + Phase 5)

**Le build se fait en natif sur la VM Proxmox, jamais en cross-compile depuis le Mac.**

- VM : `192.168.1.29`, SSH `sylvaing` (mot de passe hors dépôt)
- Script benchmark : `scripts/build_windows_vm.sh`
- Script spike backends : `scripts/build_spike_backends_vm.sh` ← Phase 5
- Garder la session SSH **ouverte** pendant le build — un process détaché est tué à la fermeture de session.
- Build ~20-40 min (première fois). Rebuild plus rapide : modèles HF déjà en cache sur la VM.
- HF_TOKEN optionnel : `HF_TOKEN=hf_xxx bash scripts/build_spike_backends_vm.sh`
- Doc benchmark : `docs/08-benchmark.md` § « Build & distribution »
- Doc spike : `docs/18-spike-backends-windows.md` §11 (journal de build, pièges résolus)

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
