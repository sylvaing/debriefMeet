# 39 — Fix OpenVINO large-v3-turbo + re-spike minimal ciblé

**Statut** : spec à implémenter (session Sonnet dédiée).
**Contexte** : l'analyse des rapports spike (VM `claudebuild` du 2026-07-07 et
Alix du 2026-07-07) a validé les 3 correctifs de `docs/18`/commit `30ddbcb`
(WER KeyError, `use_fast=False`, marqueurs whisper.cpp). Il reste **un seul
échec, reproduit à l'identique sur les deux machines** : le chargement du modèle
**OpenVINO `large-v3-turbo`**.

Ce document couvre deux livrables enchaînés :

1. **Correctif** de l'empaquetage du modèle OpenVINO turbo.
2. **Re-spike minimal** ne testant QUE `openvino/large-v3-turbo` chez Alix
   (tout le reste y est déjà mesuré), avec un bundle réduit construit **sur le
   Mac** (pas la VM).

> Prérequis lecture : `docs/18` (spike backends), et le module
> `spike/backends_windows/` (assembleur + moteurs).

---

## 1. Bug à corriger — OpenVINO turbo : `vocab_file is None`

### 1.1 Symptôme

Au chargement de `openvino-whisper-large-v3-turbo`, `charger()` lève :

```
TypeError: expected str, bytes or os.PathLike object, not NoneType
  … transformers/models/whisper/tokenization_whisper.py:291, in __init__
      with open(vocab_file, encoding="utf-8") as vocab_handle:
```

Trace complète : rapport VM `claudebuild` (`journal.log` lignes 66–94) et
rapport Alix du 2026-07-07 (même erreur, ligne « openvino/large-v3-turbo :
ÉCHEC »).

### 1.2 Cause racine (confirmée)

- `spike/backends_windows/moteur_openvino.py:36` charge le processeur avec
  `AutoProcessor.from_pretrained(chemin, use_fast=False)` (correctif du commit
  `30ddbcb`, qui contournait le bug `'list' object has no attribute 'keys'` du
  tokenizer *fast* sous transformers 4.57.6).
- Le tokenizer **lent** (`WhisperTokenizer`) exige `vocab.json` **et**
  `merges.txt` dans le dossier du modèle.
- Or `convertir_openvino_turbo()`
  (`spike/backends_windows/assembler.py:179`) produit le modèle turbo via
  `optimum-cli export openvino --model openai/whisper-large-v3-turbo
  --weight-format int8`, qui écrit le tokenizer **fast** (`tokenizer.json`)
  mais **pas** `vocab.json`/`merges.txt`.
- Les autres modèles OpenVINO (small/medium/large-v3) proviennent des repos
  `OpenVINO/whisper-*-int8-ov` qui, eux, **contiennent** `vocab.json` +
  `merges.txt` → ils chargent correctement avec `use_fast=False`. Le turbo est
  le seul converti localement, donc le seul incomplet.

### 1.3 Correctif demandé

Compléter `convertir_openvino_turbo()` pour que le dossier du modèle contienne
les fichiers du tokenizer **lent** après l'export. Approche recommandée :
après le `subprocess.run([optimum_cli, "export", ...])`, écrire le
tokenizer/processeur source dans `dest`, p. ex. :

```python
from transformers import WhisperTokenizer, WhisperFeatureExtractor
WhisperTokenizer.from_pretrained(OV_TURBO_MODEL_ID).save_pretrained(dest)      # → vocab.json + merges.txt
WhisperFeatureExtractor.from_pretrained(OV_TURBO_MODEL_ID).save_pretrained(dest)  # → preprocessor_config.json
```

- `WhisperTokenizer` (classe lente explicite) garantit `vocab.json` +
  `merges.txt`, sans passer par l'auto-résolution *fast* buguée.
- Ne rien retirer de l'export optimum existant (l'IR OpenVINO + `tokenizer.json`
  restent utiles ; on **ajoute** juste les fichiers manquants).
- Ces appels tournent **côté Mac uniquement** (prebuild, torch+optimum
  présents) — conforme à la note de `convertir_openvino_turbo` : jamais sur la
  VM.

### 1.4 Critères d'acceptation (bug)

1. Après conversion, `dest` contient `vocab.json`, `merges.txt`,
   `preprocessor_config.json`, `tokenizer_config.json`, et l'IR OpenVINO
   (`openvino_*.xml`/`.bin`).
2. Sur le Mac, dans le venv `.venv` :
   `AutoProcessor.from_pretrained(dest, use_fast=False)` **ne lève pas**.
3. Idéalement, chargement complet vérifié :
   `MoteurOpenVINO(device="CPU").charger("large-v3-turbo")` puis une
   `transcrire()` sur ~30 s d'audio renvoie un texte non vide (le device GPU
   n'est pas requis pour ce test de non-régression).
4. Test unitaire ajouté à `tests/test_spike_backends_modeles.py` (ou
   `_materiel`) vérifiant qu'après `convertir_openvino_turbo` simulé/monkeypatché
   les fichiers attendus sont présents — sans télécharger le vrai modèle
   (mock `subprocess.run` + `save_pretrained`).
5. `make test` (hors intégration) reste vert.

> ⚠️ Ne PAS revenir sur `use_fast=False` dans `moteur_openvino.py` : c'est le
> correctif validé sur small/medium/large-v3. On complète le modèle, on ne
> touche pas au moteur.

---

## 2. Re-spike minimal — openvino turbo seulement, bundle réduit, build Mac

### 2.1 Objectif

Chez Alix, tout est déjà mesuré **sauf** `openvino/large-v3-turbo`. On veut un
run ciblé qui :

- ne teste QUE `openvino large-v3-turbo` (pas de re-run des 11 combos réussis,
  ~4 h économisées) ;
- s'appuie sur un **bundle réduit** (un seul modèle turbo int8 ~1,6 Go au lieu
  du bundle complet ~5+ Go, sans faster-whisper/ggml/whisper-cli.exe/directml) ;
- est construit **directement sur le Mac** (les wheels `openvino`,
  `optimum-intel`, `transformers`, `numpy`, `scipy`, `psutil`, `py-cpuinfo`,
  `huggingface-hub` existent en `win_amd64` → cross-download via
  `pip download --platform` déjà en place dans `telecharger_wheels(natif=False)`).
  **Aucune VM, aucun sync 20 Go.**

### 2.2 Modifications de l'assembleur (`spike/backends_windows/assembler.py`)

1. **Filtre `--backends` générique** (miroir de l'orchestrateur `__main__.py`) :
   - Nouveau paramètre `backends: list[str] | None` à `assembler(...)` et option
     CLI `--backends` dans `main()`.
   - Quand `backends` est fourni, ne préparer/copier QUE ce qui sert :
     - modèles : filtrer dans `preparer_modeles`/`telecharger_modeles`
       (`faster-whisper-*` seulement si `"faster-whisper"` demandé ;
       `openvino-*` si `"openvino"` ; `ggml/*` si `"vulkan"` ;
       `directml-*` si `"directml"`) ;
     - `copier_whisper_cli()` : **sauté** si `"vulkan"` absent (évite les 58 Mo
       de `whisper-cli.exe` + DLL) ;
     - wheels : garder `DEPS_SPIKE` complet (les wheels sont petits face aux
       modèles et interdépendants — ne pas chercher à les trimmer dans cette
       itération).
   - `assembler(...)` reste rétrocompatible : `backends=None` → comportement
     actuel (tous).

2. **Args de run intégrés au lanceur** :
   - `generer_lanceur(args: str = "")` : injecter `args` à la fin de la ligne
     `python -m spike.backends_windows %*` (p. ex.
     `--backends openvino --modeles large-v3-turbo`), tout en gardant `%*` pour
     les surcharges manuelles éventuelles.
   - Objectif : Alix **dézippe + double-clique `lancer.bat`**, sans rien taper.

3. **Nom du bundle/zip** : suffixer pour ne pas écraser le bundle complet, p. ex.
   `spike-backends-windows-ovturbo.zip` (paramètre de sortie ou dérivé des
   `backends`/`tailles`).

### 2.3 Commande de build (sur le Mac)

Après avoir validé le fix (§1.4), et avec le modèle turbo re-converti :

```bash
# 1. (re)convertir le modèle turbo complété — prebuild Mac
bash scripts/prebuild_spike_modeles.sh   # ou cibler seulement le turbo si le script le permet

# 2. assembler le mini-bundle cross-platform (win_amd64) SUR LE MAC
python -m spike.backends_windows.assembler \
    --backends openvino --modeles large-v3-turbo \
    --sortie bundles
# → bundles/spike-backends-windows-ovturbo.zip
```

> Ni `--natif`, ni `scripts/build_spike_backends_vm.sh` : on reste sur le Mac.
> Vérifier que `telecharger_wheels(natif=False)` récupère bien les wheels
> `win_amd64` (c'est le chemin déjà utilisé pour la vérif `--verifier`).

### 2.4 Exécution chez Alix

1. Copier `spike-backends-windows-ovturbo.zip` sur Alix.
2. Dézipper → double-cliquer `lancer.bat` (les args sont intégrés).
3. Récupérer le zip rapport produit
   (`spike_backends_Alix_home_windows_<horodatage>.zip`).
4. Le ranger dans `spike/backends_windows/resultats/` (déjà gitignore).

### 2.5 Analyse du résultat (WER hors-ligne)

Le run ciblé n'a pas de `large-v3` openvino dans le même bundle → `wer` sera
`None` dans le rapport (pas de référence intra-backend). C'est **voulu**. Le WER
turbo se calcule **hors-ligne** contre la transcription `large-v3` **déjà
produite** par le run Alix complet du 2026-07-07
(`transcription_openvino_large-v3.txt`), avec le module `qualite` du dépôt :

```python
from spike.backends_windows import qualite
ref = open("…/openvino_large-v3.txt", encoding="utf-8").read()
hyp = open("…/openvino_large-v3-turbo.txt", encoding="utf-8").read()
print(qualite.wer(ref, hyp), qualite.calculer_ratio_repetition(hyp))
```

Attendu (repère, à confirmer) : WER turbo ~0.20–0.26 vs large-v3, ratio de
répétition faible (< 0.05), RTF soutenu clairement < 1.0 sur l'iGPU Intel — à
comparer au turbo **vulkan** déjà mesuré (RTF 0.447, WER ~0.263).

### 2.6 Critères d'acceptation (re-spike)

1. `python -m spike.backends_windows.assembler --backends openvino
   --modeles large-v3-turbo --sortie bundles` produit un zip **sans** modèles
   faster-whisper, **sans** `ggml/`, **sans** `whisper-cli.exe`, **sans**
   modèles directml — contenant le modèle openvino turbo complété.
2. Le `lancer.bat` du bundle contient
   `--backends openvino --modeles large-v3-turbo`.
3. Test unitaire : `assembler(..., backends=["openvino"],
   tailles=["large-v3-turbo"])` (avec téléchargements monkeypatchés) n'inclut
   que les artefacts openvino ; `generer_lanceur("--backends openvino …")`
   contient bien les args.
4. `make test` reste vert.

---

## 3. Ordre d'exécution

1. §1 — corriger `convertir_openvino_turbo`, valider localement (§1.4).
2. §2.2 — ajouter le filtre `--backends` + args lanceur à l'assembleur (§2.6).
3. §2.3 — construire le mini-bundle sur le Mac.
4. §2.4 — run chez Alix → zip rapport.
5. §2.5 — WER hors-ligne + consigner dans `docs/18` (tableau Alix complété avec
   la ligne openvino turbo) et, si pertinent, ré-arbitrer la règle
   d'auto-sélection Intel (openvino large-v3 vs vulkan turbo — cf. analyse
   session courante).

## 4. Hors périmètre

- Run **Bastien (AMD)** : non couvert ici (backend vulkan déjà validé sur iGPU
  Intel, bon présage ; run AMD à planifier séparément).
- Trimming des wheels du bundle : non (gain marginal vs risque de casser les
  dépendances).
- Retour sur `use_fast=False` : non (correctif validé).
