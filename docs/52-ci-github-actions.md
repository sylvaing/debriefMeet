# CI GitHub Actions — builds Windows (.exe) et Linux (.deb)

> **Statut : 🔄 workflow écrit le 2026-10-20** (`.github/workflows/build.yml`), validé
> par `actionlint`, premier run réel en `workflow_dispatch` lancé le même jour (résultat :
> §8). Le Mac reste hors CI (§6). Les machines de build locales (VM Windows
> `192.168.1.29`, LXC Ubuntu `192.168.1.32`) **restent utilisables** telles quelles :
> les scripts natifs qu'elles exécutent sont ceux que la CI rejoue, à deux variables
> d'environnement près (§4).

---

## 1. Ce que fait le workflow

Un seul fichier, `.github/workflows/build.yml`, quatre jobs :

| Job | Runner | Rôle | Durée attendue |
|-----|--------|------|----------------|
| `version` | `ubuntu-latest` | Lit `__version__` (`src/debrief_meet/__init__.py`) et `version` (`pyproject.toml`), exige qu'ils soient **identiques**, et sur un tag exige `tag == v<__version__>`. Échoue en quelques secondes **avant** les builds. | < 1 min |
| `windows` | `windows-latest` | Python 3.13 (`actions/setup-python`), Inno Setup 6 (déjà sur l'image, `choco` en secours), `BUILD_INFO`, puis **`packaging\windows\build_app.cmd`** tel quel : venv, `pip install -e .[windows,dev]`, ffmpeg BtbN (SHA256 vérifié), `generer_version.py`, **pytest bloquant**, PyInstaller onedir, ISCC. Artefact `debriefMeet-setup-windows`. | 20-35 min |
| `linux` | `ubuntu-latest` + conteneur **`ubuntu:26.04`** | Paquets apt de `scripts/provisionner_lxc_ubuntu.sh`, `BUILD_INFO`, puis **`sh packaging/linux/build_app.sh`** tel quel : venv sur le Python système 3.14, `pip install -e .[linux,dev] pyinstaller`, `generer_version.py`, **pytest bloquant** (segfault de teardown toléré par le script, docs/49), PyInstaller, `dpkg-deb`. Artefact `debriefmeet-deb-linux`. | 10-20 min |
| `release` | `ubuntu-latest` | **Tags seulement.** Télécharge les deux artefacts et crée la Release GitHub du tag (`softprops/action-gh-release`) avec le `.exe` et le `.deb`, notes minimales. | < 1 min |

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
| `git push origin v0.3.1` (tag `v*`) | windows + linux, **puis release** | **Release GitHub** `v0.3.1` : `debriefMeet-setup-0.3.1+<date>.<hash>.exe` et `debriefmeet_0.3.1+<date>.<hash>_amd64.deb` |
| `workflow_dispatch` (à la demande) | windows + linux | **Artefacts du run** (onglet Actions → le run → « Artifacts »), conservés 30 jours ; pas de release |

Le garde-fou `version` refuse un tag qui ne correspond pas à `__version__` : bumper
`src/debrief_meet/__init__.py` **et** `pyproject.toml` (la version vit aux deux endroits,
`generer_version.py` ne lit que le premier), committer, puis tagger.

## 3. Lancer à la demande

```bash
gh workflow run build.yml --ref main
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

Deux retouches **sans effet sur la VM** (les défauts sont ses chemins d'avant) :

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

`packaging/linux/build_app.sh` n'a pas bougé : il se résout par rapport à son propre
chemin. `ISCC_EXE` n'a pas eu besoin d'être défini — l'image `windows-latest`
embarque Inno Setup 6 à l'emplacement que le script cherche déjà.

## 5. Caches

| Cache | Clé | Pourquoi |
|-------|-----|----------|
| pip (Windows) | `actions/setup-python` `cache: pip` sur `pyproject.toml` | le venv `.venv-build` créé par le script lit le cache pip de l'utilisateur du runner |
| pip (Linux) | `pip-ubuntu2604-<hash pyproject.toml>` sur `/root/.cache/pip` (`PIP_CACHE_DIR`) | idem, dans le conteneur — pas `~/.cache/pip` : `HOME=/github/home` y appartient à l'uid du runner et pip refuse un cache dont il n'est pas propriétaire |
| zip ffmpeg BtbN (~170 Mo) | `ffmpeg-btbn-<hash telecharger_ffmpeg.cmd>` | l'URL et le SHA256 sont épinglés dans le script : changer de version ffmpeg change la clé. Le script revérifie le SHA256 à chaque build, cache ou pas. |

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

## 6. Ce que fait encore le Mac

Le `.dmg` macOS reste **local** : signature avec le certificat « debriefMeet Local »
(docs/16 — un runner n'a pas le trousseau, et une signature différente ferait perdre
les permissions TCC), helper Swift, ffmpeg LGPL compilé. Donc, pour une release
complète :

```bash
make dmg
```

```bash
gh release upload v0.3.1 dist/debriefMeet-0.3.1+*.dmg
```

Le second est optionnel : la release créée par la CI est valide avec les deux binaires
Windows/Linux seuls, et le corps de la release le dit.

## 7. Coût

Dépôt privé : le forfait gratuit GitHub donne **2 000 min/mois**, les minutes Windows
comptent **×2**, Linux ×1. Un run complet ≈ 30 min Windows (= 60 min facturées) +
15 min Linux + 1 min de garde-fou/release ≈ **75-80 min facturées**. Soit ~25 runs par
mois dans le forfait. Un `workflow_dispatch` coûte la même chose qu'un tag : ne pas le
lancer pour « voir si ça passe » — `make test` en local fait ça en 25 s.

## 8. Checklist du premier run

1. [ ] `make test` vert en local sur la branche (fait le 2026-10-20 : voir §9).
2. [ ] Branche poussée, `gh workflow run build.yml --ref <branche>`.
3. [ ] Job `version` : les deux versions lues sont identiques.
4. [ ] Job `windows` : `[2/6]` télécharge le zip (1ᵉʳ run) et vérifie le SHA256 ;
   `[4/6]` pytest passe en `offscreen` sur l'image GitHub (la VM tournait avec un
   bureau — c'est la seule différence d'environnement) ; `[6/6]` ISCC trouvé ;
   artefact `debriefMeet-setup-windows` présent, nom `debriefMeet-setup-0.3.0+<date>.<hash>.exe`.
5. [ ] Job `linux` : apt sans question interactive ; pytest passe (ou RC=139 toléré
   avec `N passed`) ; artefact `debriefmeet-deb-linux` présent.
6. [ ] 2ᵉ run : les caches pip et ffmpeg sont **restaurés** (ligne « Cache restored »).
7. [ ] Fumée des binaires produits sur les machines de test habituelles :
   `scripts/fumee_setup_vm.sh` (Windows) et `scripts/fumee_deb_lxc.sh` (Linux) savent
   installer un fichier local — c'est la validation qui compte, la CI ne lance pas
   l'app.
8. [ ] Premier tag réel : `v0.3.1` après bump des deux versions → Release créée avec
   les deux fichiers ; `gh release upload` du `.dmg` local.

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
