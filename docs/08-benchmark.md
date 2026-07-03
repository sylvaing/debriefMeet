# 08 — Outil de benchmark cross-platform

> Clé d'interprétation des rapports. **À tenir synchrone du code** (`benchmark/rapport.py`) :
> tout changement de schéma se reflète ici, et un test garde-fou
> (`tests/test_benchmark_doc.py`) compare les clés produites à celles listées plus bas.

## Objectif

Les choix techno (transcription, diarisation, AEC) n'ont été validés que sur le Mac
(Apple Silicon / Metal). Avant les ports Windows (Phase 5) et Linux (Phase 6), il faut
savoir **si une machine donnée fait tourner le soft, et dans quel mode** (CUDA NVIDIA,
CPU int8 si seul un iGPU Intel est présent…).

L'outil rejoue le pipeline réel — chargement/resampling → transcription → diarisation —
sur un **audio canonique embarqué (~30 min)**, mesure perf **et** qualité, sonde la
capture audio système et les accélérateurs, et produit **un seul `.zip`** à transmettre.

## Périmètre

- **Perf pipeline** : sweep `small → medium → large-v3` (faster-whisper sur Win/Linux,
  mlx en baseline Mac), RTF + qualité (WER).
- **Validation capture + AEC** : scénario guidé (YouTube, lecture à voix haute),
  disponibilité de `livekit`.
- **Sondes accélérateurs** : CUDA/cuDNN, Intel OpenVINO/DirectML, AMD ROCm, Vulkan.
- *Hors périmètre* : intégration UI/OS (tray GNOME, presse-papiers, autostart).

## Build & distribution

Bundle **portable, sans installation** : un Python portable + les wheels de l'OS cible
posées par `pip --target` (sans exécution) + sources + modèles + audio, le tout zippé.
Côté utilisateur : **dézipper + double-cliquer `lancer.bat`** (`lancer.sh` sous Linux).
Aucun `pip install`, aucun réseau, aucun droit admin — le lanceur ne fait que fixer
`PYTHONPATH`/`HF_HUB_OFFLINE` et exécuter `python -m benchmark`.

> Les modèles gated **pyannote** sont téléchargés une fois (avec le token HF) puis
> embarqués → pas de token sur la machine de test.

Deux façons d'assembler, selon la cible :

### Build croisé depuis le Mac (Linux, macOS Intel, dépannage Windows)

```bash
# 1. Vérifier que toutes les dépendances ont une wheel pour la cible (rapide) :
python -m benchmark.assembler_bundle --os windows --verifier
# 2. Assembler (wheels --platform win_amd64 + sources + modèles + audio) :
python -m benchmark.assembler_bundle --os windows --token hf_xxx
```

⚠ **Limite du build croisé** : `pip --target --platform win_amd64` évalue les *markers*
(`platform_system`, etc.) contre le **Mac**, pas contre la cible. Les dépendances gardées
par marqueur (CUDA de torch sur Linux, certaines deps Windows) sont écartées → bundle GPU
potentiellement incomplet. OK pour les cibles sans GPU torch ; pour Linux+CUDA il faut
`--natif` (build dans Docker `linux/amd64`).

### Build NATIF Windows sur la VM Proxmox (recommandé pour `--os windows`)

Pour coller au parc Windows réel, on assemble **sur une VM Windows 11** : pip résout les
dépendances contre la vraie plateforme → markers corrects, wheels Windows réelles (torch,
sherpa-onnx, sounddevice, livekit…) telles que l'utilisateur final les aura.

```bash
# Depuis le Mac, tout-en-un (sync sources → build sur la VM → rapatrie le zip) :
scripts/build_windows_vm.sh           # → bundles/benchmark-windows.zip
```

**VM (labo, Proxmox)** — `192.168.1.29`, SSH `sylvaing` (mot de passe hors dépôt), OpenSSH server actif :

| Élément | Emplacement sur la VM |
|---|---|
| Python 3.11 « full » (pip + huggingface_hub) | `C:\Users\sylvaing\AppData\Local\Programs\Python\Python311\python.exe` |
| Dépôt synchronisé (sources Mac) | `C:\Users\sylvaing\build\debrief-meet` |
| Script de build (token HF en dur) | `C:\Users\sylvaing\build.cmd` |
| Sortie | `C:\Users\sylvaing\out\benchmark-windows.zip` |
| Journal + témoin de fin | `C:\Users\sylvaing\build.log`, `build.done` (`RC=<code>`) |

`build.cmd` lance `python -m benchmark.assembler_bundle --os windows --token hf_xxx
--sortie out` (résolution native, **sans** `--platform`) et écrit `RC=…` dans `build.done`.

**Pièges appris (encodés dans le script) :**
- **Garder la session SSH ouverte** pendant tout le build. Un process lancé détaché
  (`start /b`, `Start-Process -WindowStyle Hidden`) est **tué quand la session SSH se
  ferme** → le build ne démarre jamais. Le script lance `cmd /c build.cmd` en synchrone
  et attend (run_in_background côté lanceur).
- **Connexions SSH sérielles**, jamais en parallèle : sshd limite les rafales d'auth
  password (`MaxStartups`) → `Permission denied` sporadique. `NumberOfPasswordPrompts=1`
  fait échouer vite au lieu de reboucler.
- **Sync via `tar` over ssh** avec `COPYFILE_DISABLE=1` (évite les fichiers AppleDouble
  `._*` côté Windows). On ne renvoie que `benchmark/`+`src/`, pas les assets/audio (déjà
  sur la VM) ni `rapports/` (zips lourds).
- La **capture loopback Windows** ne passe **pas** par sounddevice (qui en est incapable,
  cf. section dédiée plus bas) mais par la lib `soundcard`, embarquée dans le bundle.

## Capture loopback Windows (soundcard) — décision & spike à prévoir

**Contexte.** Le premier bench Windows (Bastien, 2026-06-29) a planté sur
`sd.WasapiSettings(loopback=True)` → `TypeError`. Après inspection : `WasapiSettings`
de **sounddevice** n'accepte que `exclusive`/`auto_convert`/`explicit_sample_format` ;
**PortAudio (sous sounddevice) n'a aucun flag loopback WASAPI** et la demande upstream
([python-sounddevice #281](https://github.com/spatialaudio/python-sounddevice/issues/281))
est ouverte sans suite depuis 2020. Conclusion : `loopback=True` ne pouvait jamais marcher
— ce n'est pas un bug de version, c'est une impasse structurelle de sounddevice.

**Décision (benchmark).** On capture le son système Windows via **`soundcard`**
(`benchmark/sondes_capture.py:_capturer_loopback_windows`) : ouverture du haut-parleur
par défaut comme micro loopback (`get_microphone(hp.name, include_loopback=True)`).
Raisons : (1) **même auteur (Bastian Bechtold) que `soundfile`**, déjà dépendance du
bundle ; (2) **pur Python + cffi** (cffi déjà tiré par sounddevice → pas de nouvelle
brique compilée, pas de compilateur) ; (3) multi-OS, BSD-3, mainteneu actif (0.4.6, 2026).
On capture en **stéréo puis downmix mono** : `soundcard` rend du bruit si on lui demande
explicitement **un seul** canal sur WASAPI (limite documentée).

**Alternative gardée en réserve.** [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)
(fork PortAudio patché « façon Audacity », Apache-2, wheels Windows) — purpose-built pour
le loopback WASAPI, mais extension compilée et Windows-only. Plan B si `soundcard` se
révèle capricieux sur le parc réel.

> ⚠ **À faire : un spike / une campagne de tests dédiée** avant de figer le choix —
> notamment pour le **port Windows du produit (Phase 5)**, où le loopback est dans le
> hot-path et doit être vraiment fiable (sample rates variés, périphériques BT, changement
> de sortie à chaud, sous-alimentation de buffers signalée par `soundcard`). Les deux libs
> sont des projets **individuels « hobby »** sans backing corporate : pour la production,
> évaluer aussi une implémentation WASAPI maison (ctypes / `pycaw`-like). Le choix
> `soundcard` ci-dessus vaut **pour le benchmark** (sonde courte, hors hot-path), pas
> nécessairement pour le produit.

## Lancement & options

`python -m benchmark` enchaîne la **phase guidée interactive** (capture/AEC, utilisateur
présent) puis la **phase automatique** (sweep + diarisation + sondes).

| Option | Effet |
|---|---|
| `--audio CHEMIN` | Audio de test (défaut : canonique embarqué) |
| `--modeles small medium large-v3` | Tailles balayées |
| `--duree-max-s 600` | Durée max d'audio pour le sweep transcription (défaut 600 s = 10 min ; `0` = tout). La diarisation utilise toujours l'audio complet. |
| `--langue fr` | Langue forcée |
| `--sortie DOSSIER` | Dossier de sortie (défaut `./resultats_benchmark`) |
| `--auto-skip` | Phase guidée non-interactive (tout sauté) — tests/CI |
| `--sans-diarisation` / `--sans-capture` / `--sans-accel` | Désactive une phase |
| `--sans-emballage` | Ne produit pas le zip |

### Audio de test — non versionné (confidentiel)

Les fichiers audio (`*.wav`, `*.mp3`…) sont **exclus du dépôt git** (`.gitignore`) car ils
contiennent des enregistrements de réunions réelles. Sur un nouveau clone, ils sont donc
**absents** — il faut les fournir soi-même :

1. Déposer un ou plusieurs enregistrements dans `spike/diarization/audio/` (formats acceptés :
   `.mp3`, `.wav`), en respectant les motifs attendus par le script de montage
   (voir `SEGMENTS` dans `benchmark/assets/construire_audio_canonique.py`, ex.
   `Recording at *.mp3`).
2. Reconstruire l'audio canonique de référence :

   ```bash
   python benchmark/assets/construire_audio_canonique.py
   # → régénère benchmark/assets/audio_canonique.wav
   ```

3. Alternative ponctuelle : pointer un audio arbitraire sans reconstruire, via
   `python -m benchmark --audio /chemin/vers/audio.wav` (ou la variable
   d'environnement `BENCH_AUDIO`).

> La suite de tests (`make test`) ne dépend d'**aucun** de ces fichiers : elle génère ses
> propres `.wav` à la volée. Seul le benchmark a besoin d'un vrai audio.

## Contenu du zip `bench_<host>_<os>_<horodatage>.zip`

Seul fichier à renvoyer. Contient :

- `rapport.json` — le rapport structuré (schéma ci-dessous) ;
- `rapport.md` — la version lisible ;
- `journal.log` — journal verbeux (versions de libs, périphériques, timings, tracebacks) ;
- `transcription_<taille>.txt` — transcription brute de chaque modèle (jugement qualité) ;
- `transcription_openvino_<taille>.txt` — transcription brute via OpenVINO GPU Intel (si applicable) ;
- `diarisation_sherpa.md` / `diarisation_pyannote.md` — qui parle quand ;
- WAV courts des sondes de capture.

## Schéma du rapport JSON

Clés de premier niveau (le garde-fou vérifie cette liste) :

<!-- CLES-RAPPORT-DEBUT -->
- `schema_version` — version du schéma (entier)
- `horodatage` — ISO-8601 local
- `machine` — matériel détecté
- `mode` — moteur/device/compute retenus
- `audio` — fichier + durée (s)
- `transcription` — liste, un objet par taille de modèle
- `diarisation` — liste, un objet par moteur (sherpa, pyannote)
- `openvino` — liste, comparatif transcription sur GPU Intel (vide si pas de GPU Intel)
- `capture` — résultats du scénario guidé
- `accelerateurs` — sondes CUDA/Intel/AMD/Vulkan
- `verdict` — niveau + modèle max viable
- `observations` — texte libre saisi par l'utilisateur
<!-- CLES-RAPPORT-FIN -->

Détail des sous-objets importants :

- `machine` : `hostname, os, os_version, arch, cpu, cpu_cores{physiques,logiques},
  cpu_freq_mhz, ram_gb, gpu{type,name,vram_mb,cuda}, alimentation{source,niveau_pct}`.
- `audio` : `fichier, duree_s` (durée totale du fichier), `duree_transcription_s`
  (durée réellement transcrite par le sweep — bornée par `--duree-max-s`, défaut 600 s ;
  la diarisation utilise `duree_s` complet).
- `mode` : `moteur` (`faster-whisper`|`mlx`), `device` (`cuda`|`cpu`|`metal`),
  `compute_type` (`float16`|`int8`).
- `transcription[]` : `modele, load_s, infer_s, rtf_moyen, rtf_fin, rtf_tranches[],
  ram_pic_mb, vram_pic_mb, n_segments, langue, n_mots, wer, wer_reference, artefact_txt`
  — ou `{modele, erreur}` si l'étape a échoué.
- `diarisation[]` : `moteur, rtf, n_locuteurs, ram_pic_mb, artefact_md` — ou `{moteur, erreur}`.
- `openvino[]` : comparatif transcription sur **GPU Intel** (Windows/Linux, si GPU Intel détecté ;
  sinon liste vide). Un objet par taille : `moteur` (`openvino`), `modele`, `device` (`GPU`),
  `load_s, infer_s, rtf_moyen, rtf_fin, rtf_tranches[], ram_pic_mb, vram_pic_mb, n_segments,
  langue, n_mots, wer, wer_reference, artefact_txt` — ou `{moteur, modele, erreur}`. Modèles
  INT8 ; WER interne au sweep OV (OV large-v3 = référence). À confronter au sweep `transcription`
  (faster-whisper CPU) pour mesurer l'apport du GPU Intel.
- `capture` : `youtube{realise,son_capte,rms,format_capte{sample_rate,canaux,dtype}}`,
  `lecture_voix{realise,wer_avant_aec,wer_apres_aec,attenuation_echo_db}`,
  `peripheriques[]`, `aec_livekit{disponible,version,plateforme_wheel}`.
  (L'étape « Bluetooth » a été retirée : trop d'interactions utilisateur pour un gain
  faible — cf. `peripheriques[]` qui liste déjà les périphériques BT détectés.)
- `accelerateurs` : `cuda{disponible,cudnn,version_cuda,...}, intel_openvino, intel_directml,
  amd_rocm, vulkan` (chacun avec `disponible`).
  - `vulkan` : `{disponible, methode (`loader`|`vulkaninfo`|null), gpus[{nom, type, fabricant,
    api_version}], erreur?}`. Sondé via le **loader du driver** (ctypes, en sous-processus isolé
    pour qu'un crash natif ne tue jamais le run), avec repli sur le CLI `vulkaninfo` si le SDK est
    présent. Vulkan est **multi-fournisseurs** : `gpus` peut lister un GPU Intel, AMD **ou** NVIDIA.
- `verdict` : `modele_max_viable` (`small`|`medium`|`large-v3`|`null`),
  `niveau` (`viable`|`limite`|`insuffisant`), `details`.

## Guide d'interprétation

- **RTF (real-time factor)** = temps de traitement / durée audio. Le mode réunion
  transcrit en continu par tranches de 30 s → il faut **RTF < 1.0** pour suivre.
  `rtf_moyen` = global ; `rtf_fin` = moyenne des dernières tranches. Un `rtf_fin`
  nettement > `rtf_moyen` = **throttling thermique** (laptop) → la machine décroche en
  réunion longue même si la moyenne semble bonne. Le sweep est borné à `duree_transcription_s`
  (10 min par défaut) : sur une machine lente (RTF > 1) la charge horloge dépasse 10 min et le
  throttling reste visible ; pour un test de throttling définitif sur réunion très longue,
  relancer avec `--duree-max-s 1800`.
- **Verdict** : `modele_max_viable` = plus gros modèle dont le RTF **soutenu**
  (`max(moyen, fin)`) < 1.0. `viable` = large-v3 tient ; `limite` = seul small/medium
  tient (qualité moindre) ; `insuffisant` = rien ne suit le temps réel.
- **WER** : mode auto → large-v3 sert de référence (WER 0), on lit la **dégradation
  relative** de small/medium. Pour juger la qualité absolue, lire les `transcription_*.txt`.
- **Mémoire pic** (`ram_pic_mb`/`vram_pic_mb`) : dimensionne le besoin et tranche si le
  **mode réunion à 2 flux** (moi + participants) peut charger 2 modèles en parallèle ou
  doit sérialiser. (En dev sans `psutil`, ces champs valent `null` ; le bundle embarque psutil.)
- **Capture** : `youtube.son_capte` valide le loopback (WASAPI/PipeWire) ; `format_capte`
  donne le sample rate/canaux réels à coder dans l'adaptateur ; `aec_livekit.disponible`
  dit si l'AEC tient sur cet OS.
- **Accélérateurs** : `cuda` valide le bundling CUDA/cuDNN ; `intel_*`/`amd_rocm`/`vulkan`
  indiquent s'il vaut le coup d'ajouter un backend pour les machines sans NVIDIA. `vulkan.gpus`
  nomme le(s) GPU (fabricant inclus) et **recoupe `machine.gpu`** : si la détection matériel est
  floue, le `deviceName` Vulkan lève le doute. `vulkan.disponible` reflète le **runtime réel**
  (loader du driver), plus le simple fait que l'outil `vulkaninfo` soit installé.
- **OpenVINO (`openvino`)** : sur une machine Intel sans NVIDIA, faster-whisper tourne sur CPU
  (CTranslate2 n'a pas de backend Intel). Cette section donne le **RTF sur le GPU Intel** via
  OpenVINO INT8, à comparer au `rtf_moyen` du même modèle dans `transcription` (CPU). Si le GPU
  Intel fait passer large-v3 sous RTF 1.0 (ou réduit nettement le RTF), cela justifie d'ajouter
  un **backend OpenVINO** au port pour le parc bureautique Intel. Liste vide = pas de GPU Intel
  (NVIDIA, AMD, ou Mac) → comparatif non pertinent. AMD reste en CPU + sondes ROCm/Vulkan
  (aucune voie GPU AMD compatible avec l'assemblage depuis le Mac).

## Reprendre avec Claude quand un rapport arrive

Les rapports reviennent souvent dans une **autre session**. Transmettre **l'unique zip**
et demander : « *analyse ce rapport et propose les choix d'archi + le plan de port
Windows/Linux* ». Claude ouvre le zip, lit `rapport.json` + `journal.log` + artefacts,
s'appuie sur ce document, et enchaîne sur les Phases 5/6.
