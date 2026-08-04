# debriefMeet

Transcription vocale locale — dictée, réunion, journal.  
Application de bureau (macOS d'abord, puis Windows et Linux), basée sur Whisper.

---

## Prérequis

| Outil | Version | Comment l'installer |
|---|---|---|
| Python | 3.11+ | `brew install python` |
| Xcode Command Line Tools | macOS 14+ | `xcode-select --install` |
| make | — | inclus avec Xcode CLT |

---

## Installation

```bash
# Cloner le dépôt
git clone <url> debriefMeet
cd debriefMeet

# Installation complète : venv + dépendances + helpers Swift + tests
bash scripts/setup.sh
```

Le script vérifie les prérequis, installe tout, compile les helpers Swift et lance les tests.  
Si tout est vert, l'environnement est prêt.

---

## Commandes

```bash
make setup          # Réinstaller l'environnement depuis zéro
make test           # Tests unitaires rapides (~5 s, sans matériel)
make test-all       # Tous les tests (y compris intégration)
make run            # Lancer debriefMeet
make build-helpers  # Recompiler les helpers Swift
make clean          # Supprimer le venv et les artefacts
```

---

## Benchmark machine (Windows / Linux)

Outil pour savoir si une machine cible fait tourner le soft, et dans quel mode
(CUDA, CPU int8…). Il rejoue le pipeline réel (transcription + diarisation) sur un
audio de ~30 min et produit **un seul `.zip`** à transmettre.

```bash
python -m benchmark.assembler_bundle --os windows --token hf_xxx  # assemble depuis le Mac
# côté utilisateur : dézipper le bundle, double-cliquer lancer.bat (aucune installation)
```

Détails, schéma du rapport et guide d'interprétation : [`docs/08-benchmark.md`](docs/08-benchmark.md).

---

## État d'avancement

| Phase | Fonctionnalité | État |
|---|---|---|
| 0 | Socle : tray, icône, machine à états, IPC | ✅ |
| 0.5 | POC capture audio système (ScreenCaptureKit) | ✅ |
| 1 | Mode Dictée macOS (mlx-whisper → presse-papiers) | ✅ |
| 2 | Mode Réunion macOS (SCK + fichier .md incrémental) | ✅ |
| 3 | Journal + Préférences + Historique | ✅ |
| 3.5 | Reconnexion micro à chaud (Qt Multimedia) | ✅ |
| A | Annulation d'écho sans casque (AEC, LiveKit AEC3) | ✅ |
| D | Diarization « qui a parlé » (pyannote, passe finale) | ✅ macOS, validée |
| B | Outil benchmark machine cross-platform | ✅ outil prêt |
| UX | Refonte Historique (listing filtré, actions, jobs en tâche de fond) — [doc 09](docs/09-refonte-historique.md) | ✅ |
| UX | Transcription différée + mode « enregistrement seul » — [doc 10](docs/10-transcription-differee.md) | ✅ |
| UX | Spinner animé des tâches de fond — [doc 11](docs/11-spinner-anime.md) | ✅ |
| UX | Prompts de copie (onglet Préférences, préfixe à la copie) — [doc 12](docs/12-prompts.md) | ✅ |
| UX | Identité d'icône (carré arrondi + ondes ; tray + `AppIcon.icns`) | ✅ |
| UX | Titre éditable + durée dans l'Historique — [doc 14](docs/14-titre-duree.md) | ✅ |
| UX | Changement de modèle à chaud (téléchargement + rechargement) — [doc 15](docs/15-changement-modele.md) | ✅ |
| UX | Onboarding diarization (token HF + assistant guidé + illustrations) — [doc 13](docs/13-diarization-onboarding.md) | ✅ |
| 4 | Packaging macOS (`.dmg`, permissions stables) | ⬜ à faire |
| 5 | Portage Windows | ⬜ à faire |
| 6 | Portage Linux | ⬜ à faire |

---

## Éditions Windows

Deux installeurs sont produits depuis le même code — un poste en reçoit **un seul**,
installer l'un remplace l'autre :

| Édition | Setup | Transcription | Taille |
|---|---|---|---|
| **Complète** | `debriefMeet-setup-<version>.exe` | locale (Whisper CPU) + diarization ; dictée et journal disponibles | ~159 Mo + ~1,5 Go de modèle téléchargé au 1ᵉʳ lancement |
| **Lite** | `debriefMeet-lite-setup-<version>.exe` | **API Mistral uniquement** (Voxtral pour la transcription, `mistral-small` pour le CR) ; réunions seulement | ~95-115 Mo, aucun modèle à télécharger |

⚠️ L'édition **Lite** exige une **clé API Mistral** : sans elle elle enregistre l'audio
mais ne peut jamais le transcrire. Détails : [doc 44](docs/44-edition-lite-windows.md).

---

## Permissions macOS (une fois par machine)

Deux permissions sont demandées automatiquement au premier usage :

- **Microphone** — au premier enregistrement (Dictée ou Réunion)
- **Enregistrement de l'écran** — au premier démarrage du mode Réunion (pour capter l'audio des participants via ScreenCaptureKit)

En développement (app non packagée), la permission "Enregistrement de l'écran" doit être accordée au **terminal** (Terminal.app, iTerm2…) :

> Réglages Système → Confidentialité et sécurité → Enregistrement de l'écran → activer le terminal utilisé

---

## Structure du projet

```
debriefMeet/
├── src/debrief_meet/        # code Python (cœur + UI + adaptateurs)
│   ├── core/              # logique métier partagée (modes, config, logs)
│   ├── ui/                # interface PySide6 (tray, icônes, fenêtres)
│   └── platform/          # adaptateurs par OS (interfaces + implémentations)
├── helpers/macos/         # helpers Swift compilés (capture audio)
├── benchmark/             # outil de benchmark cross-platform (bundle portable)
├── tests/                 # suite de tests (pytest)
├── docs/                  # spécifications
│   ├── 01-specifications-fonctionnelles.md
│   ├── 02-specifications-techniques.md
│   └── 03-phases-implementation.md
├── scripts/
│   └── setup.sh           # installation complète
└── Makefile               # commandes de build
```

---

## Documentation

Les specs complètes sont dans [`docs/`](docs/) :

- [`01-specifications-fonctionnelles.md`](docs/01-specifications-fonctionnelles.md) — ce que fait l'app (modes, UI, formats de fichiers)
- [`02-specifications-techniques.md`](docs/02-specifications-techniques.md) — architecture, stack, build, packaging
- [`03-phases-implementation.md`](docs/03-phases-implementation.md) — découpage en phases, état d'avancement
- [`08-benchmark.md`](docs/08-benchmark.md) — outil de benchmark cross-platform (schéma rapport, interprétation)

---

## Dépannage

| Problème | Solution |
|---|---|
| `python3: command not found` | `brew install python` |
| `xcrun: error: …` | `xcode-select --install` |
| `ModuleNotFoundError: PySide6` | `make clean && make setup` |
| Mode Réunion silencieux | Accorder "Enregistrement de l'écran" au terminal (voir ci-dessus) |
| mlx-whisper pas installé | `make clean && make setup` (ou `pip install mlx-whisper` dans le venv) |
| Téléchargement au premier lancement (≈1 min) | Une fenêtre de progression télécharge le modèle mlx (~1 Go) — une seule fois ; ensuite l'app est prête |
| Erreur de compilation Swift | `softwareupdate --all --install` pour mettre à jour Xcode CLT |
