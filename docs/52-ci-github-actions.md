# CI GitHub Actions — builds Windows (.exe) et Linux (.deb)

> **Statut : 🔄 workflow écrit le 2026-10-20** (`.github/workflows/build.yml`), validé
> par `actionlint`, Windows + Linux **verts en réel** (runs 3-4, §9), job macOS ajouté le
> même jour (§6 — son premier run est consigné en §9). Les machines de build locales
> (Mac de Sylvain, VM Windows `192.168.1.29`, LXC Ubuntu `192.168.1.32`) **restent
> utilisables** telles quelles : les scripts natifs qu'elles exécutent sont ceux que la
> CI rejoue, à trois variables d'environnement près (§4).

---

## 1. Ce que fait le workflow

Un seul fichier, `.github/workflows/build.yml`, cinq jobs :

| Job | Runner | Rôle | Durée attendue |
|-----|--------|------|----------------|
| `version` | `ubuntu-latest` | Lit `__version__` (`src/debrief_meet/__init__.py`) et `version` (`pyproject.toml`), exige qu'ils soient **identiques**, et sur un tag exige `tag == v<__version__>`. Échoue en quelques secondes **avant** les builds. | < 1 min |
| `windows` | `windows-latest` | Python 3.13 (`actions/setup-python`), Inno Setup 6 (déjà sur l'image, `choco` en secours), `BUILD_INFO`, puis **`packaging\windows\build_app.cmd`** tel quel : venv, `pip install -e .[windows,dev]`, ffmpeg BtbN (SHA256 vérifié, miroir §5), `generer_version.py`, **pytest bloquant**, PyInstaller onedir, ISCC. Artefact `debriefMeet-setup-windows`. | **≈ 9 min** mesurés (caches chauds ou froids) |
| `linux` | `ubuntu-latest` + conteneur **`ubuntu:26.04`** | Paquets apt de `scripts/provisionner_lxc_ubuntu.sh`, `BUILD_INFO`, puis **`sh packaging/linux/build_app.sh`** tel quel : venv sur le Python système 3.14, `pip install -e .[linux,dev] pyinstaller`, `generer_version.py`, **pytest bloquant** (segfault de teardown toléré par le script, docs/49), PyInstaller, `dpkg-deb`. Artefact `debriefmeet-deb-linux`. | **≈ 5 min** mesurés |
| `macos` | `macos-latest` (Apple Silicon) | **Tag, ou dispatch avec `macos=true`.** Trousseau temporaire + identité « debriefMeet Local » (secrets, §6), venv 3.13 `[macos,dev]`, ffmpeg LGPL compilé (cache) + helper Swift, **pytest bloquant** (`test_build.py` inclus, sur le binaire réel), puis **`make dmg`** tel quel. Artefact `debriefMeet-dmg-macos`. | ≈ 15-25 min (ffmpeg en cache ou non) — **×10** en facturation |
| `release` | `ubuntu-latest` | **Tags seulement.** Télécharge les trois artefacts et crée la Release GitHub du tag (`softprops/action-gh-release`) avec `.exe`, `.deb` et `.dmg`, notes minimales. | < 1 min |

Les gates pytest sont **exactement celles des scripts** (mêmes `--ignore`, mêmes
marqueurs, `QT_QPA_PLATFORM=offscreen` posé au niveau du workflow) : un test rouge
bloque le binaire, comme sur la VM et le LXC.

Pourquoi `ubuntu:26.04` en conteneur plutôt que `ubuntu-latest` nu : c'est la cible du
`.deb` (docs/49) **et** son Python système 3.14 (décision L7). L'image existe sur Docker
Hub (vérifiée le 2026-10-20) ; si elle disparaissait, le repli serait
`runs-on: ubuntu-latest` + `actions/setup-python` 3.14 — mais le bundle lierait alors
contre les libs système de l'image du runner, pas celles d'Ubuntu 26.04.

## 2. Déclencheurs

| Déclencheur | Builds | Où vont les binaires |
|-------------|--------|----------------------|
| `git push origin v0.3.1` (tag `v*`) | windows + linux + **macos**, **puis release** | **Release GitHub** `v0.3.1` : `debriefMeet-setup-0.3.1+<date>.<hash>.exe`, `debriefmeet_0.3.1+<date>.<hash>_amd64.deb`, `debriefMeet-0.3.1+<date>.<hash>.dmg` |
| `workflow_dispatch` (à la demande) | windows + linux (+ macos si `macos=true`) | **Artefacts du run** (onglet Actions → le run → « Artifacts »), conservés 30 jours ; pas de release |

Le garde-fou `version` refuse un tag qui ne correspond pas à `__version__` : bumper
`src/debrief_meet/__init__.py` **et** `pyproject.toml` (la version vit aux deux endroits,
`generer_version.py` ne lit que le premier), committer, puis tagger.

## 3. Lancer à la demande

```bash
gh workflow run build.yml --ref main
```

Avec le DMG macOS en plus (minutes ×10, §7) :

```bash
gh workflow run build.yml --ref main -f macos=true
```

Puis suivre et récupérer :

```bash
gh run list --workflow=build.yml --limit 3
```

```bash
gh run watch
```

```bash
gh run download <run-id> --dir dist/ci
```

`--ref` accepte une branche ou un tag ; un dispatch sur un tag ne crée **pas** de
release (seul le push du tag le fait).

## 4. Ce qui a changé dans les scripts natifs

Trois retouches **sans effet sur les machines locales** (les défauts sont leurs chemins
d'avant) :

- `packaging/windows/build_app.cmd` : `BUILD_DIR` (racine des sources, défaut
  `C:\Users\sylvaing\build\debrief-meet`) et `PYTHON_EXE` (défaut `py -3.13`). Le
  workflow passe `BUILD_DIR=${{ github.workspace }}` et `PYTHON_EXE=python`
  (celui que `actions/setup-python` met dans le `PATH`).
- `packaging/windows/telecharger_ffmpeg.cmd` : `FFMPEG_CACHE_DIR` (défaut
  `C:\Users\sylvaing\build\ffmpeg-cache`), pour que `actions/cache` restaure le zip.
  **Et un ré-épinglage forcé** : le build BtbN du 2026-07-12 répondait **404** au premier
  run — BtbN purge ses autobuilds datés au bout de quelques semaines, et la VM ne s'en
  apercevait pas (zip en cache depuis juillet). Épinglé désormais sur
  `autobuild-2026-10-20-13-08` (`ffmpeg-n8.1.3-18-g46d899d7a0`, même ligne 8.1 ;
  SHA256 `26634a5e…`). Conséquence pour la VM : son cache a l'ancien SHA → le script
  retéléchargera au prochain build (c'est son chemin nominal). ⚠️ Le prochain setup
  Windows embarque donc un ffmpeg 8.1.3 au lieu de 8.1.2 — à passer par la fumée
  `scripts/fumee_setup_vm.sh` comme n'importe quel build.

- `packaging/creer_certificat.sh` : `DEBRIEFMEET_KEYCHAIN` (défaut : le trousseau de
  session), pour que l'identité éphémère de CI aille dans le trousseau temporaire du
  job, jamais dans celui du runner.

`packaging/linux/build_app.sh`, `build_app.sh`, `build_dmg.sh` et le Makefile n'ont pas
bougé : ils se résolvent par rapport à leur propre chemin. `ISCC_EXE` n'a pas eu besoin
d'être défini — l'image `windows-latest` embarque Inno Setup 6 à l'emplacement que le
script cherche déjà.

## 5. Caches

| Cache | Clé | Pourquoi |
|-------|-----|----------|
| pip (Windows) | `actions/setup-python` `cache: pip` sur `pyproject.toml` | le venv `.venv-build` créé par le script lit le cache pip de l'utilisateur du runner |
| pip (Linux) | `pip-ubuntu2604-<hash pyproject.toml>` sur `/root/.cache/pip` (`PIP_CACHE_DIR`) | idem, dans le conteneur — pas `~/.cache/pip` : `HOME=/github/home` y appartient à l'uid du runner et pip refuse un cache dont il n'est pas propriétaire |
| zip ffmpeg BtbN (~170 Mo) | `ffmpeg-btbn-<hash telecharger_ffmpeg.cmd>` | l'URL et le SHA256 sont épinglés dans le script : changer de version ffmpeg change la clé. Le script revérifie le SHA256 à chaque build, cache ou pas. |
| pip (macOS) | `actions/setup-python` `cache: pip` sur `pyproject.toml` | idem Windows |
| ffmpeg LGPL macOS compilé (`packaging/vendor/ffmpeg` + licence) | `ffmpeg-macos-<arch>-<hash build_ffmpeg.sh>` | opus + ffmpeg compilés depuis les sources (~10 min, versions et SHA256 épinglés dans le script) ; `build_ffmpeg.sh` est idempotent et **revalide** le binaire restauré (muxers, filtres, dylibs système seules) |

Rien d'autre n'est mis en cache : aucun modèle n'est téléchargé au build, aucun secret
n'est requis (`GITHUB_TOKEN` suffit pour la release et le miroir ci-dessous).

### Miroir du zip ffmpeg — release `outils-build`

Deux mécanismes se cumulent contre la CI Windows : **BtbN purge ses autobuilds datés**
(404 au premier run) et **GitHub évince un cache inutilisé 7 jours**. Sans parade, tout
build lancé après une pause de plus d'une semaine échouerait en `[2/6]`. D'où un
miroir : le zip épinglé est aussi l'**asset `ffmpeg-win64-lgpl.zip` de la release
`outils-build`** du dépôt (pré-release, tag hors `v*` donc sans effet sur le workflow,
ce n'est pas une version de l'app). Quand `actions/cache` manque, un step
`gh release download` dépose cet asset dans le cache **avant** `build_app.cmd` ; le
script le trouve « déjà en cache », vérifie le SHA256 et continue. Le step est en
`continue-on-error` : miroir absent (fork, asset pas encore remplacé) → le script
retombe sur l'URL BtbN et échoue proprement si elle a été purgée. Rien à faire côté VM.

**Ré-épingler ffmpeg** (nouvelle ligne BtbN) = 3 gestes, dans cet ordre :
télécharger le zip et calculer son SHA256 ; mettre à jour `FFMPEG_URL` + `FFMPEG_SHA256`
dans `telecharger_ffmpeg.cmd` ; remplacer l'asset :

```bash
gh release upload outils-build ffmpeg-win64-lgpl.zip --clobber
```

## 6. macOS : local **et** CI, avec la même identité de signature

Le DMG se construit toujours en local (`make dmg`, docs/16), et la CI fait **la même
chose** sur un runner Apple Silicon : `make dmg` tel quel, précédé de la gate pytest.
Tout le sujet est la **signature** : TCC indexe l'app par sa signature, donc le runner
doit signer avec **la même identité « debriefMeet Local »** que le Mac de Sylvain, sinon
chaque release ferait redemander Micro + Enregistrement de l'écran. Cette identité est
un certificat auto-signé qui ne vit que dans son trousseau de session : il faut l'en
**exporter une fois** vers deux secrets du dépôt.

### 6.1 Mettre le certificat dans les secrets (une fois, à la main)

1. Trousseaux d'accès › trousseau *session* › catégorie *Mes certificats* › « debriefMeet
   Local » › clic droit › **Exporter…** › format `.p12`, avec un mot de passe (obligatoire :
   `security import` refuse un `.p12` sans mot de passe). Ne pas passer par `security
   export -t identities`, qui exporterait **toutes** les identités du trousseau.
2. Depuis un terminal, sans jamais coller la clé dans un chat ni un fichier du dépôt :

```bash
gh secret set MACOS_CERT_P12_BASE64 --body "$(base64 -i ~/Desktop/debriefMeet-Local.p12)"
```

```bash
gh secret set MACOS_CERT_P12_PASSWORD
```

   (le second lit le mot de passe au clavier), puis supprimer le `.p12` du Bureau.
3. Vérifier au run suivant que l'**Authority** affichée par le step « Signature du bundle
   produit » est identique à celle d'un `make dmg` local (`codesign -dv
   dist/debriefMeet.app`).

Ce que ça implique : la clé privée de ce certificat quitte le Mac pour les secrets
GitHub (chiffrés, lisibles seulement par les runs). Elle ne vaut rien en dehors de
debriefMeet (auto-signée, pas de chaîne Apple), et si elle est compromise, on en
régénère une et on accepte de re-cliquer deux permissions.

### 6.2 Ce que fait le job sans les secrets

Il crée un **trousseau temporaire** et y laisse `creer_certificat.sh` fabriquer une
identité **éphémère** (même nom, autre clé) : la chaîne entière est vérifiée, le DMG
produit est fonctionnel mais **fait redemander les permissions TCC** et ne doit pas
être diffusé — le job l'annonce en `::warning::`. Sur un **tag**, les secrets sont
**exigés** : échec explicite plutôt qu'une release à signature instable. Le trousseau
temporaire est supprimé en fin de job quoi qu'il arrive.

### 6.3 Ce qui reste hors CI

- **Notarisation** : hors périmètre v1 (docs/16 — le hardened runtime casse mlx/torch).
  Le DMG de release s'ouvre par clic droit › Ouvrir au premier lancement, comme le local.
- **Validation TCC** (docs/16 §6) : manuelle, sur le poste.
- **Intel** : `macos-latest` est Apple Silicon et mlx l'exige ; pas de build x86_64.

## 7. Coût

Dépôt privé : le forfait gratuit GitHub donne **2 000 min/mois**, les minutes Windows
comptent **×2**, Linux ×1, **macOS ×10**. Mesuré sur les runs du 2026-10-20 : ≈ 9 min
Windows (= 18 min facturées) + 5 min Linux + 1 min de garde-fou/release ≈ **25 min
facturées par run sans macOS**, soit ~80 runs par mois. Le job macOS ajoute ≈ 15-25 min
réelles, soit **150-250 min facturées** : c'est pourquoi il ne tourne que sur un tag ou
sur `-f macos=true`. Un run complet avec macOS ≈ 200-275 min facturées, soit ~7 à 10
releases par mois dans le forfait — largement assez, mais pas pour « voir si ça
passe » : `make test` en local fait ça en 45 s, et `make dmg` reste là pour un DMG
rapide.

## 8. Checklist du premier run

1. [x] `make test` vert en local sur la branche (2026-10-20, §9).
2. [x] Branche poussée ; `gh workflow run build.yml --ref <branche>` — ⚠️ répond **404
   tant que le workflow n'est pas enregistré** (premier événement sur sa branche, ou
   fusion dans `main`) : les runs 1-3 sont passés par un déclencheur `push` temporaire,
   retiré depuis ; le run 4 est le premier vrai `workflow_dispatch`.
3. [x] Job `version` : les deux versions lues sont identiques (10 s).
4. [x] Job `windows` : `[2/6]` prend le zip du miroir et vérifie le SHA256 ; `[4/6]`
   **1518 passed, 8 skipped** en `offscreen` sur l'image GitHub (la VM tournait avec
   un bureau — seule différence d'environnement, sans effet) ; `[6/6]` ISCC trouvé
   sans `choco` ; artefact `debriefMeet-setup-windows` de 176 Mo
   (`debriefMeet-setup-0.3.0+<date>.<hash>.exe`).
5. [x] Job `linux` : apt sans question ; **1502 passed, 24 skipped**, RC=139 de
   teardown toléré par le script ; artefact `debriefmeet-deb-linux` de 127 Mo.
6. [x] Caches **restaurés** au run suivant côté Windows (pip et ffmpeg, « Cache
   restored ») ; côté Linux le cache pip se réinitialise à chaque changement de
   `pyproject.toml` (c'est sa clé), restauré sinon.
7. [ ] Fumée des binaires produits sur les machines de test habituelles :
   `scripts/fumee_setup_vm.sh` (Windows) et `scripts/fumee_deb_lxc.sh` (Linux) savent
   installer un fichier local — c'est la validation qui compte, la CI ne lance pas
   l'app.
8. [ ] Secrets `MACOS_CERT_P12_BASE64` / `MACOS_CERT_P12_PASSWORD` posés (§6.1), puis
   `gh workflow run build.yml --ref <branche> -f macos=true` : Authority du bundle
   identique au local, pas de `::warning::` d'identité éphémère.
9. [ ] Premier tag réel : `v0.3.1` après bump des deux versions → Release créée avec
   les **trois** fichiers.

## 9. Journal

- **2026-10-20** — workflow écrit, `actionlint` 1.7.12 vert, `make test` vert en
  local (1722 passed, 10 skipped, 2 échecs d'environnement habituels : helper Swift non compilé,
  audio canonique du benchmark — tous deux dans `test_build.py`, que les gates de
  build excluent). Premier `workflow_dispatch` : résultat consigné ci-dessous par
  l'agent au moment du run.
- **2026-10-20, run 1** (push sur la branche, déclencheur temporaire — GitHub n'enregistre
  un workflow, donc n'accepte `gh workflow run`, qu'après un premier événement sur sa
  branche ou sa fusion dans `main`) : job `version` ✅ en 10 s ; `linux` ❌ en 1 min
  (`git rev-parse` : « dubious ownership », le workspace est monté dans le conteneur
  avec l'uid du runner et les steps tournent en root → `safe.directory` ajouté) ;
  `windows` ❌ en 1 min (`[2/6]` : **404 sur le zip BtbN**, cf. §4 et §5 — ré-épinglé +
  miroir `outils-build`). Tout ce qui précédait passait : setup-python 3.13, Inno Setup
  déjà sur l'image, `pip install -e .[windows,dev]` en 1 min, apt dans le conteneur en
  1 min.
- **2026-10-20, run 2** : `windows` ✅ en **9 min 33** — miroir `outils-build` pris
  (« Zip deja en cache »), SHA256 vérifié, **1518 passed, 8 skipped** en 1 min 41,
  PyInstaller + ISCC, artefact `debriefMeet-setup-windows` de 177 Mo ; caches pip et
  ffmpeg sauvegardés. `linux` ❌ : venv et version OK, puis **segfault au milieu de la
  gate**, dans `tests/test_surveillant.py` (pas le segfault de teardown connu, que le
  script tolère). Diagnostic par un workflow temporaire (matrice PySide6 6.12.0 /
  6.11.1, `faulthandler`, `ldd` du plugin multimédia, `QMediaDevices.audioInputs()`
  seul) : **aucune lib manquante** ; avec **6.11.1**, Qt Multimedia tente PulseAudio,
  échoue proprement (« pa_context_connect() failed »), rend une liste vide, 8 passed ;
  avec **6.12.0** (Qt 6.12, FFmpeg 9.0.1 embarqué), le constructeur de `QMediaDevices`
  **segfaulte** (`surveillant_peripheriques.py:63`). Ce n'est pas propre à la CI :
  `build_app.sh` recrée `.venv-build` à chaque build, le LXC prendrait aussi 6.12.0
  (sortie le mois précédent). → **`PySide6>=6.6,<6.12` dans `pyproject.toml`**, les 3
  OS — Windows avait passé la gate avec 6.12.0 (1518 passed) mais aucun build 6.12 n'a
  été fumé ; lever la borne = rejouer la gate Linux sans serveur audio. Le Mac (dev) est
  en 6.11.1, inchangé. Au passage : `PYTHONFAULTHANDLER=1` sur les deux jobs, et le
  cache pip Linux déplacé en `/root/.cache/pip` (pip le désactivait sous `/github/home`).
- **2026-10-20, run 3** ✅ **tout vert** : `version` 7 s ; `linux` **5 min 07** (PySide6
  6.11.2, 1502 passed / 24 skipped en 49 s, teardown RC=139 toléré,
  `debriefmeet_0.3.0+20261020.dd79dae_amd64.deb`, 127 Mo) ; `windows` **8 min 44**
  (caches pip et ffmpeg restaurés, PySide6 6.11.2, 1518 passed / 8 skipped en 1 min 25,
  setup de 176 Mo). Déclencheur `push` temporaire retiré dans la foulée.
- **2026-10-20, run 4** ✅ — premier vrai **`workflow_dispatch`** (`gh workflow run
  build.yml --ref claude/sleepy-neumann-8d6867`, accepté maintenant que le workflow est
  enregistré) : `linux` **4 min 35** (cache pip restauré), `windows` **7 min 53**,
  les deux artefacts présents, `release` sauté comme prévu hors tag.
