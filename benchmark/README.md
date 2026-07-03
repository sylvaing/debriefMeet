# Benchmark debriefMeet

Mesure si une machine Windows ou Linux peut faire tourner l'application debriefMeet
(transcription, diarisation, AEC) et dans quel mode.

## À quoi ça sert

Les choix techniques (moteur de transcription, diarisation, AEC) n'ont été validés que
sur Mac Apple Silicon. Avant les ports Windows (Phase 5) et Linux (Phase 6), cet outil
rejoue le pipeline réel sur la machine cible et répond à :

- **La machine est-elle assez puissante ?** (verdict : confortable / viable / insuffisant)
- **Quel mode utiliser ?** (CUDA float16 si NVIDIA, CPU int8 sinon)
- **La capture audio système fonctionne-t-elle ?** (WASAPI / PipeWire, AEC livekit)
- **Quels accélérateurs sont disponibles ?** (CUDA/cuDNN, Intel OpenVINO/DirectML, AMD ROCm, Vulkan)

Il produit **un seul `.zip`** à transmettre pour analyse.

### Moteur de transcription testé selon le GPU

| GPU | Moteur principal (clé `transcription`) | Comparatif additionnel |
|---|---|---|
| **NVIDIA** | faster-whisper CUDA float16 | — |
| **Intel** (iGPU) | faster-whisper CPU int8 | **OpenVINO INT8 sur GPU Intel** (clé `openvino`) — Windows/Linux |
| **AMD** | faster-whisper CPU int8 | — (sondes ROCm/Vulkan seulement) |
| **Aucun** | faster-whisper CPU int8 | — |

CTranslate2 (faster-whisper) n'a pas de backend Intel ni AMD → sur ces machines il tourne
sur CPU. Sur une machine **Intel**, le bundle Windows/Linux lance **en plus** un sweep
**OpenVINO** (small/medium/large-v3 INT8) sur le GPU Intel, pour mesurer le gain RTF/WER vs
CPU — ce qui dira s'il faut un backend OpenVINO pour le port. AMD reste à arbitrer (aucune
voie GPU AMD compatible avec l'assemblage 100 % depuis le Mac).

## Utilisation (côté machine de test)

Distribué sous forme de bundle portable — **aucune installation, aucun droit admin**.

```
1. Dézipper  benchmark-windows.zip  (ou benchmark-linux.zip)
2. Double-cliquer  lancer.bat        (Windows)
   ou              ./lancer.sh       (Linux, rendre exécutable si besoin)
3. Suivre les consignes à l'écran :
     - Lancer une vidéo YouTube avec du son
     - Lire le texte affiché à voix haute
4. Envoyer le fichier  bench_<hôte>_<os>_<date>.zip  affiché à la fin
```

Le run dure **20 à 60 min** selon la puissance de la machine (transcription d'un
audio de 30 min avec trois tailles de modèle Whisper).

## Construire les bundles depuis le Mac

### Prérequis

```bash
cd debrief-meet/
source .venv/bin/activate
```

### Bundle Windows (assemblé intégralement depuis le Mac)

```bash
# Étape 1 — vérifier que toutes les dépendances ont une wheel win_amd64 (~1 min) :
python -m benchmark.assembler_bundle --os windows --verifier

# Étape 2 — assembler le bundle complet (~20-40 min, 4-5 Go téléchargés) :
python -m benchmark.assembler_bundle --os windows

# Avec un token HF si pyannote n'est pas dans le cache local :
HF_TOKEN=hf_xxx python -m benchmark.assembler_bundle --os windows

# Sortie : bundles/benchmark-windows.zip
```

Le script télécharge automatiquement :
- le Python embeddable Windows 3.11 (depuis python.org)
- les wheels de toutes les dépendances pour `win_amd64`
- les modèles faster-whisper small / medium / large-v3
- le modèle sherpa-onnx (copie depuis `spike/diarization/models/`)
- le modèle pyannote (depuis le cache HF local, ou HF si token fourni)

**Le token HF n'est utilisé qu'à cette étape, jamais embarqué dans le bundle.**
Régénérer le token HF après le build si transmis en clair.

### Bundle Linux (assemblé depuis le Mac, sans Docker)

Comme pour Windows : les wheels `manylinux` se résolvent depuis le Mac, et le
runtime Python est un build **portable et relocatable** (python-build-standalone),
téléchargé et embarqué automatiquement. Le bundle est donc **entièrement autonome** —
aucun `python` requis sur la machine cible.

```bash
python -m benchmark.assembler_bundle --os linux --verifier   # contrôle des wheels
python -m benchmark.assembler_bundle --os linux              # assemblage complet

# Sortie : bundles/benchmark-linux.zip
```

> Le bundle Linux cible **x86_64/glibc** (Ubuntu, Debian, Fedora… récents).
> Côté collègue : dézipper puis `./lancer.sh` (le script restaure lui-même le bit
> exécutable si l'archive a été extraite via une interface graphique).

### Bundle macOS Intel (x86_64)

```bash
python -m benchmark.assembler_bundle --os macos-intel --verifier
python -m benchmark.assembler_bundle --os macos-intel

# Sortie : bundles/benchmark-macos-intel.zip
```

> ⚠️ **Limite Intel Mac** : PyTorch ne publie plus de wheel macOS x86_64
> (≥ 2.3 = Apple Silicon uniquement). La diarisation **pyannote n'est donc pas
> embarquée** sur cette cible — le bundle couvre la **transcription**
> (faster-whisper CPU) + la diarisation **sherpa** (ONNX, sans torch) + les sondes.
> pyannote apparaîtra « absent » dans le rapport ; c'est attendu (le comparatif
> pyannote/sherpa est établi par la baseline Apple Silicon).
>
> Côté collègue : dézipper puis double-cliquer **`lancer.command`** (au 1er lancement,
> macOS Gatekeeper peut demander un clic droit → « Ouvrir »). Apple Silicon n'a pas
> besoin de ce bundle : le benchmark s'y lance en dev via `mlx` (cf. plus bas).

## Options de lancement

```bash
# Sur la machine de test (via le bundle) :
lancer.bat [options]       # Windows
./lancer.sh [options]      # Linux
./lancer.command           # macOS Intel (ou double-clic Finder)

# En développement sur Mac Apple Silicon (sans bundle, moteur mlx) :
python -m benchmark [options]
```

| Option | Défaut | Description |
|---|---|---|
| `--audio CHEMIN` | audio canonique embarqué | Fichier audio de test alternatif |
| `--modeles small medium large-v3` | tous | Modèles Whisper à balayer |
| `--langue fr` | `fr` | Langue forcée pour la transcription |
| `--sortie DOSSIER` | `./resultats_benchmark` | Dossier de sortie |
| `--auto-skip` | non | Passe la phase guidée — pour tests/CI |
| `--sans-diarisation` | non | Désactive la diarisation |
| `--sans-capture` | non | Désactive la sonde capture audio |
| `--sans-accel` | non | Désactive les sondes accélérateurs |
| `--sans-emballage` | non | Ne produit pas le zip final |

## Contenu du zip de sortie

`bench_<hôte>_<os>_<date>.zip` — seul fichier à transmettre :

```
rapport.json              # résultats structurés (schéma complet → docs/08-benchmark.md)
rapport.md                # version lisible
journal.log               # log verbeux : versions, timings, erreurs avec tracebacks
transcription_small.txt   # transcription brute de chaque modèle (jugement qualitatif)
transcription_medium.txt
transcription_large-v3.txt
diarisation_sherpa.md     # qui parle quand (sherpa-onnx, sans licence)
diarisation_pyannote.md   # qui parle quand (pyannote/speaker-diarization-community-1)
```

## Interpréter un rapport

Voir **[docs/08-benchmark.md](../docs/08-benchmark.md)** :
guide complet du schéma JSON, lecture RTF/throttling/WER/mémoire,
verdict, et comment reprendre avec Claude quand un rapport arrive.
