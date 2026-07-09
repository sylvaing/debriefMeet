# Spike — Backends de transcription Windows (Bastien AMD / Alix Intel)

> **Statut :** ⬜ **À FAIRE** — spike comparatif, préalable au moteur Windows de la Phase 5.
> **Type :** spike **de mesure** (pas un go/no-go binaire) : comparer des backends sur le matériel réel et **choisir le meilleur par profil matériel**.
> **Décide :** quel(s) backend(s) de transcription Whisper le portage Windows doit embarquer, et **selon quelle règle d'auto-sélection** au runtime, pour tourner de façon optimisée sur les deux machines cibles (Bastien AMD, Alix Intel) et leurs semblables.
> Références : `02-specifications-techniques.md` (Bloc 2 — moteurs), `08-benchmark.md` (mécanique réutilisée), `17-analyse-benchmark-alix.md` (données + bugs déjà observés), `03-phases-implementation.md §Phase 5`.

---

## 1. Contexte

Le portage Windows (Phase 5) est, sur le papier, « adaptateurs + packaging » : l'architecture en
3 couches fait que le cœur métier, le micro (`CaptureMicroSounddevice`), les chemins
(`platformdirs`) et la surveillance des périphériques (Qt) sont déjà partagés. **Le seul vrai
risque technique est le moteur de transcription.**

Le moteur prévu à l'origine (faster-whisper / CTranslate2 : CUDA NVIDIA ou CPU) **n'exploite aucun
des iGPU des machines cibles**. Or les deux machines réelles n'ont pas de GPU NVIDIA et ont des
iGPU de fabricants différents :

| | Bastien | Alix |
|---|---|---|
| CPU | AMD Ryzen 5 PRO 5675U (12 cœurs) | Intel i5-1235U |
| iGPU | AMD Radeon | Intel UHD |
| CUDA | ❌ | ❌ |
| faster-whisper CPU int8 (mesuré, doc 17) | seul `small` < RTF 1.0 | seul `small` < RTF 1.0 ; WER `small` 54 % (médiocre) |
| OpenVINO GPU (mesuré, doc 17) | ❌ (plugin GPU = Intel uniquement) | ✅ large-v3 **temps réel** (RTF 0.546, WER 0) |

**Aucun backend unique évident ne couvre AMD *et* Intel avec une bonne qualité.** Avant d'écrire le
moteur Windows, on mesure les options réelles sur les deux machines plutôt que de parier.

---

## 2. Objectif & question

**Question :**
> Pour chaque profil matériel cible (iGPU Intel, iGPU AMD, CPU seul), **quel couple (backend, modèle)
> donne la meilleure qualité tout en suivant le temps réel** (RTF soutenu < 1.0, sans hallucination) ?
> Et quel **ensemble de backends** le produit doit-il embarquer, avec quelle **règle d'auto-sélection**,
> pour couvrir le parc ?

**Le but n'est PAS de trouver un backend commun.** Le produit final pourra embarquer plusieurs
backends (p. ex. OpenVINO pour Intel + un backend pour AMD + repli CPU) et choisir automatiquement
selon le matériel détecté au démarrage.

---

## 3. Décisions de cadrage (actées avec l'utilisateur)

| Sujet | Décision |
|---|---|
| **Forme** | Spike **autonome** sous `spike/backends_windows/`. On **s'inspire de la mécanique du benchmark** (mesures, sondes, bundle portable, build VM) en la **copiant/adaptant**, mais on **ne modifie pas** `benchmark/` (donc aucun garde-fou benchmark à synchroniser). |
| **Livrable** | Le spike produit **son propre rapport zippé**, auto-suffisant, qu'on analyse ensuite. Tout ce qui sert à décider doit y figurer (cf. §6). |
| **Matrice** | **4 backends × 4 modèles**, sur **2 machines** (Bastien, Alix). |
| **Périmètre** | Transcription **uniquement** (RTF, qualité, mémoire, accélérateurs). La capture/AEC et la diarisation sont **hors périmètre** de ce spike. |
| **Décision attendue** | L'**ensemble de backends à embarquer** + la **règle d'auto-sélection** (par profil matériel), pas un gagnant unique. |

---

## 4. Matrice & backends

**Modèles (4)** : `small` · `medium` · `large-v3` · **`large-v3-turbo`**.
> `large-v3-turbo` (large-v3 distillé, ~6-8× plus rapide, qualité quasi identique) est le pari clé :
> il pourrait rendre une qualité quasi-large en temps réel **même sans GPU**, et donc simplifier le
> choix. Mesuré sur **tous** les backends qui le supportent.

**Backends (4)** :

| Backend | Couverture matérielle | Lib | Modèles | État dans le projet |
|---|---|---|---|---|
| **faster-whisper** (CTranslate2) | CPU (universel) | `faster-whisper` | `Systran/faster-whisper-*` + turbo `deepdml/faster-whisper-large-v3-turbo-ct2` | déjà utilisé (benchmark) |
| **OpenVINO** | CPU + **iGPU Intel** | `optimum-intel[openvino]` | `OpenVINO/whisper-*-int8-ov` (+ turbo converti à l'assemblage si pas de repo) | déjà utilisé (benchmark) |
| **DirectML** (ONNX Runtime) | **iGPU Intel + AMD** (tout GPU DX12) | `onnxruntime-directml` + `optimum[onnxruntime]` | ONNX pré-convertis (`onnx-community/whisper-*` sur HF), turbo inclus, variante **`fp16`** explicite (cf. §12.3) | **nouveau** |
| **Vulkan** (whisper.cpp) | **iGPU Intel + AMD** (multi-fournisseurs) | binaire `whisper-cli.exe` Vulkan officiel, en **subprocess** | ggml depuis `ggerganov/whisper.cpp` (`ggml-*.bin`, turbo dispo), quantifiés `q5_0` (medium/large-v3/turbo) / `q5_1` (small — `q5_0` absent en amont, cf. §12.4) | **nouveau** |

**Pourquoi le binaire whisper.cpp en subprocess et pas `pywhispercpp` :** les wheels PyPI de
`pywhispercpp` sont compilées **CPU-only** (Vulkan absent). Le binaire Vulkan officiel découple la
brique compilée du Python embeddable du bundle et évite de compiler une extension.

**Gates (un backend non pertinent sur une machine est sauté proprement)** :
- OpenVINO GPU : `available_devices` contient une entrée `GPU*` (Intel) — sinon CPU/sauté.
- DirectML : `"DmlExecutionProvider" in onnxruntime.get_available_providers()`.
- Vulkan : `sonde_vulkan()` voit un GPU **ET** le binaire whisper.cpp est présent.

---

## 5. Architecture du spike

Package importable `spike/backends_windows/` (lancé `python -m spike.backends_windows`).
On crée `spike/__init__.py` (vide) pour rendre le sous-paquet importable. Les modules sont
adaptés du benchmark (préfixe d'env `SPIKE_*`, logger `spike_backends`), **sans dépendre de
`benchmark/`** ; on réutilise seulement `debrief_meet.core.audio` et
`debrief_meet.platform.interfaces` (contrats `ResultatTranscription` / `Segment`).

```
spike/backends_windows/
├── README.md                  # lancer + lire le rapport
├── __init__.py                # VERSION_SPIKE
├── __main__.py                # orchestrateur : matrice complète → rapport zippé
├── journalisation.py          # logger fichier DEBUG + console INFO
├── chemins.py                 # résolution assets/modèles/sortie (SPIKE_*)
├── audio_io.py                # chargement audio → float32 mono 16 kHz
├── qualite.py                 # WER + détection d'hallucination (ratio de répétition)
├── mesure.py                  # MesureMemoire + boucle de mesure RTF + WER relatif + découpe tranches
├── materiel.py                # inventaire machine (CPU, iGPU+fabricant, RAM, alimentation, driver)
├── accel.py                   # sondes accélérateurs + gates DirectML/Vulkan
├── vulkan_probe.py            # énumération GPU Vulkan (sous-processus isolé)
├── modeles.py                 # tables 4 backends × 4 modèles + résolution chemins locaux
├── moteur_faster.py           # faster-whisper CPU int8
├── moteur_openvino.py         # OpenVINO (GPU Intel sinon CPU)
├── moteur_directml.py         # ONNX Runtime + optimum (DmlExecutionProvider)
├── moteur_whispercpp.py       # whisper.cpp Vulkan (binaire en subprocess)
├── rapport.py                 # rapport.json + rapport.md + zip
├── assembler.py               # bundle portable Windows + verif wheels
└── assets/                    # audio canonique (réutilise celui du benchmark)
```

Chaque moteur expose la même interface : `charger(taille)` / `transcrire(audio, langue) ->
ResultatTranscription` / `liberer()`. La boucle de mesure (`mesure._mesurer`) est **générique** :
elle prend n'importe quel moteur et produit toute l'instrumentation. Chaque (backend × modèle) est
isolé en `try/except` : un échec dégrade **une ligne** du rapport, ne casse jamais le run.

---

## 6. Contenu exhaustif du rapport (le cœur du spike)

Sortie = **un zip** `spike_backends_<host>_<os>_<horodatage>.zip` contenant :
- `rapport.json` (structuré, pour analyse),
- `rapport.md` (lisible),
- `journal.log` (verbeux : versions de libs, devices, timings, tracebacks),
- `transcription_<backend>_<modele>.txt` (transcription brute, pour juger la qualité à l'œil).

`rapport.json` — clés de premier niveau :

- **`machine`** : `hostname, os, os_version, arch, cpu, cpu_cores{physiques,logiques}, cpu_freq_mhz,
  ram_gb, gpu{type,name,fabricant,vram_mb,driver}, alimentation{source,niveau_pct}`.
  *(L'alimentation contextualise le throttling : batterie ≠ secteur.)*
- **`libs`** : versions (`python, faster-whisper, ctranslate2, onnxruntime-directml, optimum,
  transformers, openvino, sounddevice, numpy, scipy, huggingface-hub`) + version/build whisper.cpp.
- **`accelerateurs`** : `cuda{disponible,version,cudnn}`, `openvino{disponible,version,gpu_intel}`,
  `directml{disponible,providers}`, `amd_rocm{disponible}`, `vulkan{disponible,gpus[{nom,fabricant,api_version}]}`.
- **`audio`** : `fichier, duree_s, duree_transcription_s` (sweep borné), `langue`.
- **`resultats[]`** : **un objet par (backend × modèle)** —
  `backend`, `modele`, `device_reel` (cpu/gpu/dml/vulkan), `compute_type`/`quantization`,
  `statut` (`ok` | `indisponible` | `erreur`) + `erreur` éventuelle,
  `load_s`, `infer_s`,
  `rtf_moyen`, **`rtf_fin`** (moyenne des dernières tranches → throttling), `rtf_tranches[]` (courbe),
  `ram_pic_mb`, `vram_pic_mb` *(⚠ `null` sur iGPU et en subprocess — limite documentée, pas une erreur)*,
  `n_segments`, `n_mots`, `langue_detectee`,
  **`wer`** (relatif au plus gros modèle réussi **du même backend**) + `wer_reference`,
  **`ratio_repetition`** + **`hallucination`** (bool) *(Alix a halluciné en boucle sur OpenVINO
  small/medium — doc 17 ; il FAUT le détecter pour disqualifier ces couples)*,
  `taille_modele_mo` (pèse sur le bundle produit final),
  `artefact_txt`.
- **`verdict_machine`** : par machine, le **meilleur** couple (backend, modèle) tel que
  RTF soutenu `max(rtf_moyen, rtf_fin) < 1.0`, `hallucination = false`, meilleur WER ; + `niveau`
  (`viable` / `limite` / `insuffisant`).
- **`synthese`** : recommandation lisible **par profil matériel** (iGPU Intel / iGPU AMD / CPU seul) :
  quel backend+modèle est optimal pour chacun, l'**ensemble de backends à embarquer** pour couvrir le
  parc, et la **règle d'auto-sélection** associée.

> Le WER est **relatif par backend** (large-v3 du même backend = référence) : on lit la dégradation
> small/medium/turbo **à l'intérieur** d'un backend, pas un WER cross-backend trompeur. Pour la qualité
> absolue, lire les `transcription_*.txt`.

---

## 7. Métriques & critères de décision

- **RTF soutenu** = `max(rtf_moyen, rtf_fin)`. Viable si **< 1.0** (le mode Réunion transcrit par
  tranches de 30 s → doit suivre le temps réel). `rtf_fin ≫ rtf_moyen` = throttling thermique
  (la machine décroche en réunion longue).
- **Qualité** = WER relatif + jugement des transcriptions brutes ; un couple **halluciné** est
  **disqualifié** quel que soit son RTF.
- **Mémoire** = `ram_pic_mb` (dimensionne le mode Réunion à 2 flux : 2 modèles chargés ou sérialisés).
- **Décision** = pour chaque profil matériel, le meilleur couple viable & non halluciné ; puis
  l'ensemble minimal de backends couvrant Intel + AMD + repli CPU, et la règle de sélection.

---

## 8. Livraison & build

- **Bundle portable, sans installation** (adapté de `benchmark/assembler_bundle.py`) : Python
  embeddable + wheels Windows (`pip --target`) + sources spike + 4 backends × 4 modèles + binaire
  whisper.cpp Vulkan (`whisper-cli.exe`, tiers — cf. §13.6) + audio, zippé, avec `lancer.bat`
  (fixe `PYTHONPATH` / `HF_HUB_OFFLINE`, lance `python -m spike.backends_windows`). Côté
  Bastien/Alix : **dézipper + double-cliquer**, aucun pip, aucun réseau, aucun droit admin.
- **Prebuild Mac** (`scripts/prebuild_spike_modeles.sh`, Python 3.13 — cf. Problème 9 §11) :
  télécharge/convertit les modèles et `whisper-cli.exe` en local, transférés vers la VM par tar
  (aucun réseau modèles côté build Windows — cf. §13).
- **Build NATIF sur la VM Proxmox** (`192.168.1.29`, cf. doc 08) : résolution de wheels en natif.
  Script `scripts/build_spike_backends_vm.sh` (squelette de `build_windows_vm.sh`).
- **Vérifier les wheels d'abord** : `python -m spike.backends_windows.assembler --verifier --os windows`
  (`onnxruntime-directml`, `optimum`, etc. en cp311 `win_amd64`).
- ⚠ **Taille du bundle** : risque 15-20 Go (4 backends × 4 modèles, formats non dédupables).
  Mitigations : modèles quantifiés (ggml `q5_0`/`q5_1` selon taille, OV int8, DirectML **fp16**
  filtré — pas int8, cf. §12.3) ; option pour n'embarquer que les backends pertinents par machine.

### Assets non versionnés (git)

Les modèles ML (`spike/backends_windows/assets/models/`) **et** les binaires prébuild tiers
(`whisper-cli.exe`, `ggml*.dll`, `whisper.dll` — ~58 Mo) sont **exclus du dépôt** (`.gitignore`) :
trop lourds et reconstructibles. Sur un nouveau clone, les régénérer avec le prebuild Mac :

```bash
scripts/prebuild_spike_modeles.sh   # (re)télécharge modèles + whisper-cli.exe / DLL Vulkan
```

(Les binaires whisper.cpp Vulkan proviennent des releases tierces — cf. §13.6.)

---

## 9. Pièges connus (doc 17 — déjà observés sur le parc Windows)

- **COM par thread** : `CoInitializeEx`/`CoUninitialize` requis dans chaque thread utilisant
  soundcard ou DirectML (DX12/MediaFoundation) — sinon `CO_E_NOTINITIALIZED (0x800401F0)`.
- **VRAM non mesurable hors CUDA** : sur iGPU et en subprocess, `vram_pic_mb` reste `null` (attendu).
- **Hallucinations iGPU** : OpenVINO small/medium ont halluciné en boucle sur Alix ; large-v3 non.
  → détection par `ratio_repetition`.
- **DLL torchaudio / VC++ Redist** : `[WinError 127]` déjà vu (hors périmètre transcription, mais à
  garder en tête pour le bundle).
- **Offline strict** : `HF_HUB_OFFLINE=1` posé par le lanceur → tous les moteurs résolvent les modèles
  depuis un **chemin local du bundle**, jamais de téléchargement runtime.
- **Caractères de contrôle** : filtrer la saisie `input()` sur Windows (`\x01` déjà observé).

---

## 10. Livrables & Definition of Done

- Dossier `spike/backends_windows/` (isolé, hors app) + `scripts/build_spike_backends_vm.sh`.
- Sur Mac : `assembler --verifier --os windows` au vert ; sweep faster-whisper CPU jouable en dev
  (au moins `small` sur l'audio canonique) ; rapport.json/md générés ; tests de fumée des primitives
  (WER, détection hallucination, matériel, sondes).
- Build VM → bundle produit ; exécution sur **Bastien et Alix** → **2 zips rapport**.
- Analyse des 2 rapports → **décision documentée** : backends à embarquer + règle d'auto-sélection,
  reportée dans `03-phases-implementation.md §Phase 5` et exploitée par le moteur Windows.
- **Aucune intégration moteur dans l'app** tant que la décision n'est pas prise.

---

## 11. Journal de build — problèmes et solutions (2026-06-30)

> Cette section documente les obstacles rencontrés lors du build du bundle sur la VM Proxmox.
> Elle est utile pour le portage réel (Phase 5) qui reproduira la même mécanique de build.

### Architecture du build

> Mise à jour 2026-07-01 (§13) : le prebuild (modèles + `whisper-cli.exe`) se fait désormais
> côté Mac (`scripts/prebuild_spike_modeles.sh`, Python 3.13 — cf. Problème 9), pas sur la VM.

```
Mac : scripts/prebuild_spike_modeles.sh (venv dédié Python 3.13, une fois)
  ├── faster-whisper : snapshot_download HF
  ├── OpenVINO : snapshot_download HF (turbo : conversion optimum-cli locale)
  ├── DirectML : snapshot_download HF, filtré fp16 seulement
  ├── Vulkan/ggml : download direct HTTP (q5_1 pour small, q5_0 sinon)
  └── whisper-cli.exe (Vulkan) : binaire tiers jonasthilo/whisper.cpp, SHA256 vérifié (§13.6)

Mac (scripts/build_spike_backends_vm.sh)
  ├── [0/4] python -m spike.backends_windows.assembler --verifier-modeles (échoue si prebuild incomplet)
  └── SSH → VM Windows 11 (192.168.1.29)
        └── scripts/spike_build.cmd
              ├── VC++ Redistributable
              ├── py -3.11 -m venv .venv-spike
              ├── pip install outils de build (huggingface-hub seulement — zéro réseau modèles)
              └── python -m spike.backends_windows.assembler --natif
                    ├── [1/7] pip install --target libs/ (wheels natives Windows)
                    ├── [2/7] copier sources spike + debrief_meet
                    ├── [3/7] modèles déjà présents (transférés par tar) → aucun téléchargement
                    ├── [4/7] copier whisper-cli.exe + DLLs (déjà présents, transférés par tar)
                    ├── [5/7] copier audio canonique
                    ├── [6/7] Python embeddable
                    └── [7/7] lancer.bat + zip
```

### Problème 1 — `rsync` non disponible sur Windows

**Symptôme :** `rsync: command not found` lors de la sync Mac → VM.

**Cause :** Le script initial de spike (`build_spike_backends_vm.sh`) copiait le patron du benchmark
mais utilisait `rsync` au lieu de `tar over SSH`. `rsync` n'est pas installé sur la VM Windows 11
par défaut.

**Solution :** Utiliser `tar czf - | ssh "tar -xzf - -C dest"` comme le script benchmark original.
Avantage : `COPYFILE_DISABLE=1` évite les fichiers `._*` macOS dans l'archive.

### Problème 2 — Guillemets littéraux dans le chemin `tar -C`

**Symptôme :** `tar: could not chdir to ''C:\Users\sylvaing\spike_backends_build''`

**Cause :** `ssh_vm "tar -xzf - -C '$VM_REPO'"` — les guillemets simples sont dans une chaîne
double-quotée : le shell Mac les passe *littéralement* à SSH, donc le chemin transmis est
`'C:\...'` (avec apostrophes). `tar` sur Windows ne gère pas ça.

**Solution :** Supprimer les guillemets simples : `ssh_vm "tar -xzf - -C $VM_REPO"` (comme
le script benchmark original).

### Problème 3 — `scp` upload refusé avec le format `/c/Users/...`

**Symptôme :** `scp: dest open "/c/Users/sylvaing/.../audio_canonique.wav": No such file or
directory` alors que le répertoire existe.

**Cause :** Le format de chemin `/c/Users/...` (style Cygwin/MinGW) fonctionne pour les *downloads*
depuis la VM (le serveur SCP Windows résout `/c/` → `C:\`), mais pas pour les *uploads* vers la VM
(le client SCP Mac ne le résout pas pareil).

**Solution :** Utiliser `tar over SSH` pour les uploads aussi (le même mécanisme que la sync
sources). Pour les downloads, `/c/` continue de fonctionner.

### Problème 4 — `optimum-cli` n'est pas un package pip

**Symptôme :** `ERROR: No matching distribution found for optimum-cli`

**Cause :** `optimum-cli` est la *commande* fournie par le package `optimum`, pas un package
séparé. Le script tentait `pip install optimum-cli`.

**Solution :** `pip install "optimum[exporters]"` (installe optimum avec ses dépendances
d'export, dont la commande `optimum-cli`).

### Problème 5 — `pip install --upgrade pip` échoue sur Windows

**Symptôme :** `ERROR: To modify pip, please run the following command: python.exe -m pip install
--upgrade pip`

**Cause :** Sur Windows, un processus ne peut pas remplacer sa propre DLL/exe en cours d'exécution.
`pip install --upgrade pip` essaie de remplacer le `pip.exe` actif — Windows le refuse.

**Solution :** `python -m pip install --upgrade pip` (passe par le launcher Python qui gère
le remplacement différé).

### Problème 6 — CLI `optimum-cli export onnx` cassée en optimum 2.x

**Symptôme :** `optimum-cli error: unrecognized arguments: onnx --model openai/whisper-small ...`

**Cause :** Le code de l'assembleur appelait `optimum-cli export onnx --model ...` (syntaxe
d'optimum 1.x). En optimum 2.x, la hiérarchie de sous-commandes a changé ; le sous-commande
`onnx` n'est plus reconnue sous `export`.

**Solution :** Utiliser l'API Python directement dans `assembler.py` :
```python
from optimum.exporters.onnx import main_export
main_export(
    model_name_or_path=REPOS_DIRECTML_SRC[taille],
    output=str(dest),
    task="automatic-speech-recognition",
)
```
L'API `main_export` est stable entre optimum 1.x et 2.x.

**Leçon pour Phase 5 :** Préférer l'API Python aux CLI des outils HuggingFace/Optimum —
les CLI évoluent vite entre versions majeures. Épingler les versions ou tester l'import
au démarrage du moteur.

### Problème 7 — VC++ Redistributable absent de la VM de build

**Symptôme :**
```
Microsoft Visual C++ Redistributable is not installed, this may lead to the DLL load failure.
OSError: [WinError 126] Le module spécifié est introuvable.
Error loading "...\torch\lib\c10.dll" or one of its dependencies.
```

**Cause :** `torch 2.x+cpu` pour Windows requiert le **Visual C++ Redistributable 2015–2022**
(`msvcp140.dll`, `vcruntime140.dll`, etc.). La VM Proxmox fraîche ne l'a pas.
Ce n'est pas spécifique à torch : `numpy`, `onnxruntime`, et la plupart des wheels native
Windows ont la même dépendance implicite.

**Solution dans le build :** Télécharger et installer en silence dans `spike_build.cmd` :
```batch
powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' ^
    -OutFile 'vc_redist.x64.exe' -UseBasicParsing; ^
    Start-Process 'vc_redist.x64.exe' -ArgumentList '/install','/quiet','/norestart' -Wait; ^
    Remove-Item 'vc_redist.x64.exe'"
```
Le flag `/quiet /norestart` est idempotent : aucun prompt, pas de reboot, aucun effet si déjà
installé.

**Leçon pour Phase 5 (machines cibles Bastien et Alix) :** Les PC des utilisateurs ont
quasiment toujours VC++ installé (inclus par Office, Teams, Visual Studio, de nombreux jeux).
Mais pour un déploiement propre, le vérifier dans l'installateur ou le bundler :
- PyInstaller peut embarquer les DLLs via `--add-binary`
- Ou vérifier la présence de `msvcp140.dll` au démarrage et guider l'utilisateur

**URL de référence :** https://aka.ms/vs/17/release/vc_redist.x64.exe (VC++ 2022 = rétrocompatible
avec toutes les libs compilées pour VS 2015–2022).

### Problème 8 — Cassure API interne torch dans `optimum.exporters.onnx`

**Symptôme :**
```
ImportError: cannot import name '_attention_scale'
  from 'torch.onnx.symbolic_opset14'
  (file: optimum/exporters/onnx/model_patcher.py)
```

**Cause :** `optimum 2.1.0` importe `_attention_scale` depuis les internals de torch
(`torch.onnx.symbolic_opset14`). Cet attribut privé a été supprimé dans `torch 2.12.x`.
C'est une cassure silencieuse de l'API interne de torch, non couverte par les contraintes de
dépendances d'optimum (`requires torch>=2.1` ne suffit pas à détecter ça).

**Cause détaillée :** `optimum.exporters.onnx.model_patcher` tente d'importer depuis
`torch.onnx.symbolic_opset14` des noms comme `_attention_scale`, `_causal_attention_mask`,
`_onnx_symbolic`, `jit_utils`, `symbolic_helper`. Ces symboles **n'ont jamais été publics** :
ils étaient présents dans `symbolic_opset14.py` de torch ≤ 2.3.x (côté ONNX exporter
TorchScript) et ont été supprimés dans le **refactoring ONNX de torch 2.4.0** (passage au
dynamo-based exporter). Dans torch 2.4.0+, `symbolic_opset14` n'expose plus que 8 fonctions
publiques (`batch_norm`, `hardswish`, `reshape`, `scaled_dot_product_attention`, etc.).

**Solution retenue pour le spike :** Utiliser des **modèles ONNX pré-convertis** depuis
HuggingFace (`onnx-community/whisper-*`) au lieu de convertir à la volée. Cela supprime
complètement torch et optimum du venv de build — seul `huggingface-hub` est nécessaire pour
télécharger les modèles.

```batch
REM venv de build — AVANT
python -m pip install "torch<2.4" --extra-index-url https://download.pytorch.org/whl/cpu
python -m pip install "optimum[exporters]" huggingface-hub

REM venv de build — APRÈS (solution retenue)
python -m pip install huggingface-hub
```

Repos utilisés (2026-06-30) :
- `onnx-community/whisper-small`
- `onnx-community/whisper-medium`
- `onnx-community/whisper-large-v3`
- `onnx-community/whisper-large-v3-turbo`

**Point d'attention :** Les repos `onnx-community` stockent les fichiers ONNX dans un
sous-dossier `onnx/` (pas à la racine). `ORTModelForSpeechSeq2Seq.from_pretrained` doit
recevoir `subfolder="onnx"` ; le `AutoProcessor` se charge depuis la racine. Le moteur
(`moteur_directml.py`) détecte la présence du sous-dossier à l'initialisation.

**Solution alternative non retenue :** Pincer `torch<2.4` + `optimum[exporters]` dans le venv
de build. Fonctionne techniquement mais crée une dette de version (torch pinné = impossible de
profiter des améliorations torch sans revérifier la compatibilité optimum à chaque bump).

**Leçon pour Phase 5 :** Privilégier les modèles ONNX pré-convertis dès le départ. Si la
conversion à la volée s'avère nécessaire pour un modèle non disponible sur HF, **tester la
combinaison exacte torch × optimum** sur la VM avant de passer en production. Les libs
HuggingFace couplent régulièrement à des internals torch non documentés ; les contraintes de
dépendances pip ne protègent pas contre ces cassures.

### Problème 9 — `optimum-intel` cassé sous Python 3.14 (prebuild Mac, 2026-07-01)

**Symptôme :** `optimum-cli export openvino --model openai/whisper-large-v3-turbo ...` échoue
systématiquement (y compris avec `openai/whisper-tiny`, donc pas spécifique à turbo) :
```
TypeError: NormalizedConfig.__init__() got multiple values for argument 'allow_new'
```

**Cause :** `optimum-intel` définit `NORMALIZED_CONFIG_CLASS` comme attribut de **classe** via
`NormalizedSeq2SeqConfig.with_args(..., allow_new=True)`, qui retourne un `functools.partial`.
Le code fait ensuite `self.NORMALIZED_CONFIG_CLASS(self._config)` en s'appuyant sur le fait
qu'un `functools.partial` stocké comme attribut de classe **n'est pas un descripteur** — accéder
à `self.NORMALIZED_CONFIG_CLASS` doit renvoyer le partial tel quel, sans injecter `self`.
**Python 3.14 a changé ça** : `functools.partial` implémente désormais `__get__`, donc
`self.NORMALIZED_CONFIG_CLASS` se comporte comme une méthode liée et injecte l'instance
`WhisperOpenVINOConfig` en tant que 1er argument positionnel. Résultat : l'appel devient
`NormalizedSeq2SeqConfig(whisper_openvino_config_instance, whisper_config, allow_new=True, ...)`
— `whisper_config` atterrit sur le paramètre `allow_new` en position, qui entre en conflit avec
le mot-clé `allow_new=True` déjà fourni. Confirmé par instrumentation directe (3 positionnels
reçus au lieu de 2) et par un micro-repro isolé (`hasattr(functools.partial, '__get__')` →
`True` sous 3.14.6, `False` avant).

**Solution retenue : exécuter le prebuild (`scripts/prebuild_spike_modeles.sh`) avec Python
3.13**, pas le `.venv` de dev (3.14). Cohérent avec `.venv-build` déjà utilisé à 3.13 pour
PyInstaller (cf. CLAUDE.md) — même classe de contrainte : outillage HuggingFace/ML pas encore
qualifié sous 3.14 au 2026-07.

**Leçon :** ce n'est pas un bug applicatif du spike — c'est une régression de compatibilité
ascendante dans `functools.partial` (changement CPython 3.14) qui casse un pattern répandu
dans l'écosystème `optimum`/`optimum-intel` (attribut de classe = factory via `partial`).
À surveiller si d'autres libs HuggingFace sont un jour exécutées sous 3.14.

---

## 12. Questions ouvertes pour Phase 5 — tranchées en discussion le 2026-07-01

### 12.1 Vérification des repos ONNX utilisés — RÉSOLU

Les 4 repos ont été vérifiés (HTTP + API HF, structure, downloads/likes) :

| Taille | Repo utilisé dans le spike | Statut |
|--------|---------------------------|--------|
| `small` | `onnx-community/whisper-small` | ✅ 200 + ONNX confirmé (97 179 dl, 1 like, maj 2025-06-19) |
| `medium` | `Xenova/whisper-medium` | ✅ 200 (`onnx-community/whisper-medium` → 401) (1 754 dl, 9 likes, maj 2025-12-16) |
| `large-v3` | `Xenova/whisper-large-v3` | ✅ 200 + ONNX confirmé (`onnx-community/whisper-large-v3` → 401) (470 dl, 14 likes, maj 2025-12-16) |
| `large-v3-turbo` | `onnx-community/whisper-large-v3-turbo` | ✅ 200 + ONNX confirmé (12 489 dl, 74 likes, maj 2025-03-06) |

**Conclusion : les repos ne sont pas disparates.** `onnx-community` et `Xenova` produisent la
même structure de fichiers (pipeline d'export Transformers.js/optimum) : `onnx/encoder_model*.onnx`,
`onnx/decoder_model*.onnx`, `onnx/decoder_with_past_model*.onnx`, avec les mêmes variantes de
quantization partout (`fp32` défaut, `fp16`, `int8`, `uint8`, `quantized`, `bnb4`, `q4`, `q4f16`).
`Xenova` = ancienne org, `onnx-community` = org HF qui a repris/officialisé — migration partielle
(d'où le 401 sur `onnx-community/whisper-medium`), format identique. **Rien à changer côté choix
de repo.** Le vrai problème trouvé était ailleurs — cf. §12.3.

---

### 12.2 Build vs téléchargement des modèles ONNX — RÉSOLU (garder le téléchargement)

**Décision : garder le téléchargement pré-converti** pour faster-whisper / OpenVINO / DirectML /
ggml — pas de conversion systématique depuis `openai/whisper-*`. Ces repos partent tous des mêmes
poids OpenAI (vérifié : `openai/whisper-small|medium|large-v3|large-v3-turbo` existent tous en
200 sur HF) ; la conversion n'apporte donc aucun gain de comparabilité, alors qu'elle ajouterait
4 pipelines de conversion à maintenir (dont whisper.cpp `convert-hf-to-ggml.py` + `quantize`, le
plus lourd) pour un problème qui n'existe pas réellement.

**Seule exception : OpenVINO `large-v3-turbo`**, qui n'a pas de repo public — conversion locale
obligatoire. Décision : cette conversion se fait **sur le Mac** (pas sur la VM), via
`optimum-cli export openvino` (ou `OVModelForSpeechSeq2Seq.from_pretrained(..., export=True)` +
`.save_pretrained()`), avec `torch` + `optimum-intel[openvino]` installés temporairement sur le
Mac uniquement — jamais dans le bundle Windows (cohérent avec le Problème 8 / torch retiré du
build Windows pour DirectML, cf. §11).

---

### 12.3 Variante DirectML chargée — bug trouvé, RÉSOLU (fp16)

**Bug :** `moteur_directml.py` (méthode `charger`) appelle `ORTModelForSpeechSeq2Seq.from_pretrained()`
sans préciser de variante (`encoder_file_name`/`decoder_file_name`/`decoder_with_past_file_name`)
→ charge par défaut les `.onnx` **fp32 non quantifiés**, alors qu'OpenVINO tourne en int8 et
ggml en q5_0/q5_1. Comparaison biaisée (DirectML pénalisé en taille/vitesse) + téléchargement
inutile de ~28-31 fichiers `.onnx` par repo (toutes variantes) alors qu'une seule est utilisée.

**Décision : variante `fp16` pour DirectML.** Pas `int8`/`uint8`/`quantized`/`bnb4`/`q4`/`q4f16` :
ces variantes des repos onnx-community/Xenova sont issues d'une quantization dynamique **sans
calibration**, pensée pour CPU/WASM navigateur (Transformers.js), pas pour l'encoder Whisper sur
GPU — dégradation WER connue. `fp16` = mêmes opérateurs que fp32 en demi-précision, bien
supportés par `DmlExecutionProvider`, pas de perte de qualité liée à une quantization agressive.
Cohérent avec la philosophie du spike : quantization **native** de la plateforme cible (int8 OV,
q5_0/q5_1 ggml, fp16 DML), pas une quantization commune forcée.

**À vérifier empiriquement au prochain build** : si `fp16` échoue à charger/tourner sur Bastien/Alix
via DML (op non supporté → fallback CPU ou erreur), repli sur `fp32` — **pas** sur une variante
int8/quantized, pour ne pas fausser la comparaison avec un artefact non calibré.

---

### 12.4 Quantization ggml `small` — bug trouvé, RÉSOLU (`q5_1`)

**Bug :** `ggml-small-q5_0.bin` **n'existe pas** sur `ggerganov/whisper.cpp` (404 confirmé).
Quantizations réellement publiées par taille (vérifié via l'API HF) :

| Taille | q5_0 | q5_1 | q8_0 | fp16 complet |
|---|---|---|---|---|
| small | ❌ | ✅ | ✅ | ✅ |
| medium | ✅ | ❌ | ✅ | ✅ |
| large-v3 | ✅ | ❌ | ❌ | ✅ |
| large-v3-turbo | ✅ | ❌ | ✅ | ✅ |

Aucune quantization unique n'est disponible pour les 4 tailles à la fois (incohérence de
publication en amont, pas un choix du spike) — sauf le fp16 complet, qui annulerait l'intérêt du
test (fichiers ~2× plus gros, pas représentatif d'un déploiement edge). `q8_0` casserait
`large-v3` (le modèle de référence le plus important). **Décision : `q5_0` pour medium/large-v3/
turbo, `q5_1` pour small** — même tier de précision (5 bits) partout ; `q5_0`/`q5_1` ne sont pas
des "versions" successives mais deux schémas de quantization par bloc coexistants dans ggml
(symétrique vs asymétrique avec offset), aucun n'est "plus récent" que l'autre.

---

## 13. Plan de correctifs & prebuild — à coder (décidé le 2026-07-01, rien codé encore)

> Cette section est le cahier des charges pour la session de code qui suivra. Ordre proposé :
> corriger les 2 bugs (rapides, indépendants) → construire le prebuild Mac → adapter le build VM.
> Ne pas relancer `scripts/build_spike_backends_vm.sh` avant l'étape 13.1/13.2 minimum (le bug
> ggml small ferait échouer le téléchargement, cf. §12.4).

### 13.1 Fix ggml `small` (rapide, indépendant)

- `spike/backends_windows/modeles.py` — `TABLE_VULKAN_GGML["small"]` :
  `"ggml-small-q5_0.bin"` → `"ggml-small-q5_1.bin"`.
- `spike/backends_windows/assembler.py` — `GGML_FICHIERS["small"]` : même correction.
- Pas d'autre changement : `resoudre_vulkan_ggml()` et `telecharger_modeles()` (boucle ggml)
  fonctionnent déjà par nom de fichier, aucune logique conditionnelle à toucher.
- Test de fumée : relancer le test existant qui couvre `resoudre_vulkan_ggml("small")` (505 tests
  actuels) — doit maintenant résoudre vers `ggml-small-q5_1.bin`.

### 13.2 Fix variante DirectML (rapide, indépendant)

- `spike/backends_windows/moteur_directml.py`, méthode `charger()` (lignes ~34-39) : passer
  explicitement la variante `fp16` à `ORTModelForSpeechSeq2Seq.from_pretrained()`. Vérifier au
  moment du code le nom exact des kwargs supportés par la version d'`optimum` installée
  (`encoder_file_name` / `decoder_file_name` / `decoder_with_past_file_name`, ou `file_name`
  unique selon version) — l'API a bougé entre versions d'optimum (cf. Problème 6/8 en §11).
  Garder le test `(_Path(chemin) / "onnx").is_dir()` existant pour le `subfolder="onnx"`.
- `spike/backends_windows/assembler.py`, `telecharger_modeles()` (boucle DirectML, lignes
  ~143-158) : filtrer `snapshot_download` avec `allow_patterns` pour ne récupérer que
  `onnx/*_fp16.onnx` (encoder/decoder/decoder_with_past) + les fichiers hors `onnx/` (config,
  tokenizer, preprocessor, generation_config) — au lieu du repo entier (~28-31 fichiers .onnx).
- Test de fumée : `MoteurDirectML.charger("small")` doit charger sans erreur et produire une
  transcription cohérente sur l'audio canonique (pas seulement ne pas lever d'exception — vérifier
  que le texte n'est pas vide/dégénéré, signe d'un mauvais nom de fichier chargé silencieusement).
- Point de vigilance noté en §12.3 : si `fp16` échoue sur DML au build VM, repli sur `fp32`
  (retirer juste les kwargs de variante), jamais sur une variante quantifiée.

### 13.3 Prebuild local Mac — nouveau composant

**But :** déplacer le téléchargement (et la seule vraie conversion, OV-turbo) du côté Mac,
pour (a) ne plus dépendre du réseau/rate-limit HF pendant le build VM, (b) garantir des modèles
strictement identiques entre Bastien/Alix/VM (un seul téléchargement, redistribué), (c) éviter de
réintroduire torch dans l'environnement Windows.

- **Réutiliser, pas dupliquer** : extraire `telecharger_modeles()` (et ses tables `REPOS_*`) de
  `assembler.py` pour qu'elle soit appelable indépendamment de l'assemblage du bundle — soit en
  l'important directement depuis un nouveau petit script, soit en ajoutant un flag CLI à
  `assembler.py` (ex. `python -m spike.backends_windows.assembler --prebuild-modeles-seulement`)
  qui n'exécute que l'étape `[3/6]` en ciblant `spike/backends_windows/assets/models/` en local
  (macOS), sans le reste de l'assemblage (wheels Windows, Python embeddable, etc. n'ont pas de
  sens sur Mac).
- **Ajout : conversion OpenVINO turbo.** Seul cas sans repo pré-converti (cf. §12.2). Nouvelle
  fonction (ex. `convertir_openvino_turbo(dest: Path)`) utilisant `optimum-cli export openvino
  --model openai/whisper-large-v3-turbo --weight-format int8 <dest>` (ou l'API Python
  `OVModelForSpeechSeq2Seq.from_pretrained(..., export=True)` + `.save_pretrained(dest)`) —
  nécessite `torch` + `optimum-intel[openvino]` dans l'environnement d'exécution du prebuild (pas
  dans `DEPS_SPIKE`, qui reste réservé aux wheels Windows du bundle).
- **Idempotence** : chaque étape doit vérifier l'existence avant d'agir. `telecharger_modeles()`
  le fait déjà pour DirectML/ggml (`if dest.exists(): skip`) mais **pas** pour faster-whisper/
  OpenVINO (appel `snapshot_download` inconditionnel, lignes ~132-141) — ajouter le même garde
  partout pour un prebuild réellement instantané au second passage.
- **Où faire tourner ce prebuild** : environnement Python du Mac avec accès à `torch`/`optimum-intel`
  — soit le `.venv` de dev existant (3.14, si les libs y sont compatibles), soit un venv dédié
  éphémère créé par le script de prebuild lui-même (plus sûr, évite de polluer `.venv`). À trancher
  au moment du code selon compatibilité des wheels macOS arm64.

### 13.4 Adapter `scripts/build_spike_backends_vm.sh`

- Ajouter, avant la connexion SSH, un appel (ou une vérification préalable) au prebuild local
  §13.3 — échouer explicitement si `assets/models/` n'est pas complet plutôt que de laisser la VM
  retenter un téléchargement partiel.
- Inclure `spike/backends_windows/assets/models/` dans le tar transféré vers la VM, en réutilisant
  le mécanisme `tar czf - | ssh "tar -xzf -"` déjà en place pour le code/l'audio (Problème 1/3 en
  §11) — pas de nouvelle mécanique de transfert à inventer.
- Côté VM, `assembler.py --natif` doit **sauter entièrement** l'étape `[3/6] Modèles` quand les
  fichiers sont déjà présents (pas juste "réseau rapide car cache HF chaud") : poser
  `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` pour cette étape côté VM, ou ajouter un flag explicite
  qui lève une erreur claire si un fichier attendu manque plutôt que de retenter un téléchargement.
- Mettre à jour le journal de build (§11) une fois le nouveau flux validé sur la VM.

### 13.5 Definition of Done du chantier « prebuild + fixes »

- [x] `ggml-small-q5_1.bin` résolu correctement (13.1)
- [x] DirectML charge explicitement la variante `fp16`, téléchargement filtré (13.2)
- [x] Prebuild Mac exécutable indépendamment, idempotent, produit les 4×4 modèles + OV-turbo
      converti (13.3) — `scripts/prebuild_spike_modeles.sh` (venv dédié torch+optimum-intel)
      + `assembler.py --prebuild-modeles-seulement` / `--verifier-modeles`
- [x] `build_spike_backends_vm.sh` transfère les modèles pré-remplis, la VM ne télécharge plus rien
      pour l'étape modèles (13.4)
- [x] `whisper-cli.exe` (Vulkan) téléchargé et intégré au bundle (13.6)
- [ ] Relance complète du build VM → bundle produit → test sur Bastien et Alix
- [ ] `docs/18` §11 mis à jour avec le nouveau journal de build si de nouveaux pièges apparaissent

Code écrit le 2026-07-01, prebuild Mac exécuté avec succès (modèles + whisper-cli.exe présents
et vérifiés localement). Reste à tester : `scripts/build_spike_backends_vm.sh` sur la VM réelle,
puis exécution sur Bastien et Alix.

### 13.6 `whisper-cli.exe` (Vulkan) — binaire tiers, ajouté le 2026-07-01

**Constat (audit du bundle avant premier build) :** `lancer.bat` positionne `SPIKE_WHISPER_CLI`
vers `libs/spike/backends_windows/assets/whisper-cli.exe`, et `chemins.py`/`moteur_whispercpp.py`
s'attendent à l'y trouver — mais **rien dans `assembler.py` ne le téléchargeait, compilait, ou
copiait** (contrairement à l'audio canonique, qui a sa propre étape). Sans correctif, le backend
Vulkan/ggml aurait planté au runtime sur Bastien et Alix, sur les 4 tailles.

**Recherche :** `ggml-org/whisper.cpp` (upstream officiel) ne publie **aucun binaire Windows
Vulkan** dans ses releases — vérifié sur la dernière release (`v1.9.1`, 2026-06-19) via l'API
GitHub : seulement CPU (`whisper-bin-Win32/x64.zip`), BLAS et cuBLAS (CUDA 11.8/12.4). C'est un
manque connu et toujours ouvert côté projet :
[issue ggml-org/whisper.cpp#3673 « Add Vulkan Windows binaries to release assets »](https://github.com/ggml-org/whisper.cpp/issues/3673).

**Décision (exception assumée) : binaire tiers.** Trois candidats évalués :

| | `jonasthilo/whisper.cpp` (retenu) | `jerryshell/whisper.cpp-windows-vulkan-bin` | `DomoticX/whisper.cpp-windows-vulkan` |
|---|---|---|---|
| Provenance | Fork direct de `ggml-org/whisper.cpp`, build **CI GitHub Actions** (`build-vulkan-windows.yml`) — c'est le PR candidat de l'issue #3673 | Binaire uploadé à la main, pas de CI dans le repo | Guide de compilation manuelle, pas de pipeline automatisé |
| Traçabilité | ✅ compilé depuis les sources visibles, logs CI publics | ❌ boîte noire | ❌ boîte noire |
| Fraîcheur | v1.8.5, 2026-06-01 | v1.0.0, 2025-08-21 | v1.0, 2026-03-12 |
| Signal de confiance | Fork technique, peu d'usage tiers connu | 24★, utilisé par le projet **Subtitle Edit** | 5★ |

`jonasthilo/whisper.cpp` retenu : c'est un build CI depuis les sources upstream, pas un exécutable
opaque envoyé par un inconnu — le plus cohérent avec la philosophie du projet (reproductible,
traçable) même en faisant une exception pour un tiers.

**Implémentation (`spike/backends_windows/assembler.py`) :**
- `WHISPER_CLI_URL` = `https://github.com/jonasthilo/whisper.cpp/releases/download/v1.8.5/whisper-vulkan-bin-x64.zip`
- `WHISPER_CLI_SHA256` = empreinte pinnée de l'archive entière (intégrité + reproductibilité —
  même binaire à chaque build, pas de « latest » qui bouge sous les pieds).
- `WHISPER_CLI_FICHIERS` = `whisper-cli.exe` + 5 DLL (`ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`,
  `ggml-vulkan.dll`, `whisper.dll`) — l'archive contient aussi `bench.exe`, `main.exe`,
  `test-vad*.exe`, `whisper-server.exe`, etc., non nécessaires au spike, non extraits.
- `telecharger_whisper_cli()` : télécharge l'archive, vérifie le SHA256 (lève `ValueError` et
  n'installe rien si l'empreinte diverge — pas d'installation silencieuse d'un binaire altéré),
  extrait uniquement les fichiers nécessaires. Appelée par le prebuild Mac
  (`assembler.py --prebuild-modeles-seulement`), pas sur la VM (même logique que les modèles —
  zéro téléchargement runtime côté build Windows).
- `copier_whisper_cli()` : copie ces fichiers depuis `assets/` (prebuild Mac) vers
  `libs/spike/backends_windows/assets/` du bundle, à l'étape `[4/7]` de `assembler()` — nouvelle
  étape car `copier_sources()` exclut `assets/` du bundle (`ignore_patterns(..., "assets")`),
  seuls `telecharger_modeles()` et `copier_audio()`/`copier_whisper_cli()` y écrivent explicitement.
- `--verifier-modeles` et `--prebuild-modeles-seulement` vérifient aussi la présence de
  `whisper-cli.exe` + DLLs (pas seulement les modèles) — `build_spike_backends_vm.sh` échoue donc
  avant la connexion SSH si le binaire manque.

---

## 14. Résultats mesurés — Alix (Intel) & décision (2026-07-09)

> Machine : **Alix** — 12th Gen Intel i5-1235U (12 cœurs), 16.8 Go RAM, iGPU
> **Intel UHD Graphics**, sur secteur. Audio canonique (1800 s, fr).
> Rapports bruts (gitignore) : `spike/backends_windows/resultats/`
> — run complet `…Alix_home…20260707-215655.zip`, complément openvino turbo
> `…Alix_home…20260709-171910.zip`.

### 14.1 Correctifs de harnais appliqués avant ces mesures

Le premier rapport Alix (run cassé) était **incomplet et partiellement
corrompu**. Trois bugs du harnais (pas du matériel), corrigés depuis :

1. **`qualite.appliquer_wer_relatif`** supprimait le `_texte` de la référence en
   pleine boucle → `KeyError` → **tout le backend jeté** dès que la référence
   (large-v3) n'était pas traitée en dernier. Effet : faster-whisper **et**
   vulkan totalement absents du rapport malgré ~2 h de calcul réel.
2. **`moteur_openvino`** : tokenizer *fast* buggé sous transformers 4.57
   (`'list' object has no attribute 'keys'`) → chargé désormais avec
   `use_fast=False`.
3. **`moteur_whispercpp`** : flag `--print-special` injectait des marqueurs
   internes (`[_BEG_]`, `[_TT_nnn]`) dans le texte → WER vulkan gonflé
   artificiellement (0.42 au lieu de 0.17 réel). Flag retiré.

Puis (docs/39) : le modèle **OpenVINO turbo** ne chargeait pas
(`vocab_file is None` — `vocab.json`/`merges.txt` absents de la conversion
`optimum-cli`, requis par le tokenizer lent) ; complété côté prebuild Mac, puis
re-testé via un **bundle minimal ciblé** (openvino turbo seul, construit sur le
Mac). C'est ce qui donne la ligne openvino turbo ci-dessous.

### 14.2 Matrice complète Intel — RTF soutenu / ratio_répétition

RTF soutenu = `max(rtf_moyen, rtf_fin)` (conservateur, < 1.0 = temps réel).
WER **relatif** à openvino large-v3 (réf. commune ; les trois large-v3
s'accordent à ~0.17 → tous fiables). ⚠️ = dégradation (répétition élevée).

| Modèle | faster-whisper (CPU) | openvino (GPU Intel) | vulkan (whisper.cpp, UHD) |
|---|---|---|---|
| small | 0.674 · rep 0.016 | 0.257 · **rep 0.118 ⚠️** | 0.243 · rep 0.018 |
| medium | 1.656 ✗ · rep 0.019 | 0.488 · **rep 0.152 ⚠️** | 0.542 · rep 0.024 |
| large-v3 | 2.546 ✗ · rep 0.014 | **0.694** · rep 0.038 | 0.919 · rep 0.012 |
| large-v3-turbo | 1.570 ✗ · rep 0.020 | **0.287** · **rep 0.129 ⚠️** | 0.447 · rep 0.021 |

WER vs openvino large-v3 (proxy qualité) : faster small/med/lg3/turbo =
0.272 / 0.242 / 0.166 / 0.256 ; vulkan = 0.300 / 0.266 / 0.170 / 0.263 ;
openvino small/med/turbo = 0.414 / 0.476 / 0.295. RAM au pic : vulkan ~2.0–2.5 Go
(constant), openvino large-v3 **7.4 Go**, openvino turbo 3.1 Go.

### 14.3 Constats

- **faster-whisper CPU** : propre partout, mais **trop lent au-delà de `small`**
  sur cet Intel (medium 1.7×, large 2.5×, turbo 1.6× le temps réel). Confirme
  « CPU seul = repli, pas la cible ».
- **openvino** : **seul large-v3 est propre** (rep 0.038). small/medium/**turbo**
  dégradent tous (rep 0.12–0.15 — partiellement répétitifs), signature
  systématique de la conversion openvino sur iGPU (déjà notée doc 17). openvino
  large-v3 est le plus rapide des large-v3 (0.694) **mais** coûte 7.4 Go de RAM.
- **vulkan** : **tout propre** (rep ≤ 0.024), tout viable (large-v3 juste serré à
  0.919), RAM ~2 Go quelle que soit la taille. Backend le plus robuste sur toute
  la gamme. **vulkan large-v3-turbo (0.447)** = meilleur compromis
  vitesse/qualité/RAM/marge batterie.
- **openvino turbo (0.287)** est le plus rapide du spike, mais dégradé
  (rep 0.129) → **écarté** malgré le verdict auto « VIABLE » (le moteur de
  verdict ne pondère pas la répétition — limite connue).

### 14.4 Décision Intel (Alix-classe)

- **Défaut recommandé : vulkan `large-v3-turbo`** — propre, RTF 0.447 (marge
  confortable, y compris batterie), RAM ~2 Go, disponible sur iGPU Intel **et**
  AMD (un seul chemin pour les deux profils).
- **Option qualité max : openvino `large-v3`** (0.694, propre) si l'on privilégie
  la qualité et que la RAM (7.4 Go) est acceptable.
- **À proscrire sur Intel** : openvino small/medium/turbo (répétition), et
  faster-whisper au-delà de `small` (trop lent).

→ **La règle de cadrage « Intel → OpenVINO GPU » est à réviser** : openvino n'est
gagnant qu'au large-v3 pleine qualité et reste lourd en RAM. **vulkan est un
candidat sérieux comme backend primaire sur Intel aussi**, pas seulement sur AMD
— à confirmer/arbitrer avec le run **Bastien (AMD)**, seul trou restant.

### 14.5 Reste à faire

- ⏳ **Run Bastien (AMD)** — valider empiriquement la branche « AMD → Vulkan »
  (vulkan impeccable sur l'UHD Intel : bon présage).
- Éventuel **run batterie** sur Alix (openvino large-v3 à 0.694 sur secteur
  pourrait franchir 1.0 sous throttle ; vulkan turbo à 0.447 garde la marge).
- Empaquetage openvino turbo : ✅ corrigé (docs/39) — utile seulement si l'on
  garde openvino ; vulkan turbo couvre déjà le besoin « turbo » sur Intel.
