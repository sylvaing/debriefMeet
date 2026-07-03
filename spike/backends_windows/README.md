# Spike — Backends de transcription Windows

Spike comparatif **4 backends × 4 modèles** sur **2 machines** (Bastien AMD, Alix Intel).
But : choisir le meilleur backend par profil matériel avant de coder le moteur Windows (Phase 5).

Spec complète : `docs/18-spike-backends-windows.md`.

## Lancer le spike (bundle)

Sur Bastien ou Alix — **dézipper + double-cliquer `lancer.bat`** :

```
spike-backends-windows/
├── lancer.bat          ← double-cliquer
├── python/             ← Python 3.11 embeddable
└── libs/               ← wheels + sources + modèles
```

Le run produit un zip `spike_backends_<host>_windows_<horodatage>.zip` à envoyer pour analyse.

## Lancer en développement (Mac)

```bash
# Sur Mac : teste faster-whisper CPU sur l'audio canonique
source .venv/bin/activate
python -m spike.backends_windows --backends faster-whisper --modeles small

# Avec l'audio par défaut (benchmark/assets/audio_canonique.wav)
SPIKE_AUDIO=benchmark/assets/audio_canonique.wav python -m spike.backends_windows \
  --backends faster-whisper --modeles small --sans-emballage
```

## Build du bundle Windows (VM Proxmox)

```bash
# Sur Mac : sync + build natif + rapatriement
bash scripts/build_spike_backends_vm.sh

# Vérifier les wheels d'abord (rapide)
python -m spike.backends_windows.assembler --verifier
```

## Structure

```
spike/backends_windows/
├── __main__.py          # orchestrateur : matrice → rapport zippé
├── journalisation.py    # logger spike_backends
├── chemins.py           # SPIKE_* env vars
├── audio_io.py          # float32 mono 16 kHz
├── qualite.py           # WER + détection hallucination
├── mesure.py            # MesureMemoire + boucle RTF
├── materiel.py          # inventaire machine
├── accel.py             # sondes + gates DirectML/Vulkan/OpenVINO
├── vulkan_probe.py      # énumération Vulkan (subprocess isolé)
├── modeles.py           # tables 4 backends × 4 modèles
├── moteur_faster.py     # faster-whisper CPU int8
├── moteur_openvino.py   # OpenVINO (GPU Intel ou CPU)
├── moteur_directml.py   # ONNX Runtime + DmlExecutionProvider
├── moteur_whispercpp.py # whisper.cpp Vulkan (subprocess)
├── rapport.py           # rapport.json + rapport.md + zip
└── assembler.py         # bundle portable Windows
```

## Rapport produit

Chaque run produit un zip contenant :
- `rapport.json` — résultats structurés (RTF, WER, hallucination, verdict, synthèse)
- `rapport.md` — tableau lisible
- `journal.log` — trace complète (DEBUG)
- `transcription_<backend>_<modele>.txt` — transcription brute

## Pièges connus (doc 17)

- **VRAM non mesurable** sur iGPU et en subprocess → `vram_pic_mb` = null (attendu)
- **Hallucinations OpenVINO** small/medium sur Alix → détectées par `ratio_repetition`
- **COM par thread** : `CoInitializeEx` requis pour DirectML/MediaFoundation
- **HF_HUB_OFFLINE=1** posé par le lanceur → modèles résolus localement uniquement
