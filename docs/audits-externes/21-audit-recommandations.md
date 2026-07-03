# 21 — Audit du code & recommandations

> **Origine :** audit produit par une autre session/IA. Mis à part dans
> `docs/audits-externes/` pour consultation ultérieure — pas mis à jour au fil de l'eau
> avec le reste de `docs/`, à relire avec un œil critique avant d'agir dessus.
>
> Revue de l'état du projet **debrief-meet** au 2026-07-01.
> Document de pilotage : liste ce qui est fait, ce qu'il reste à faire, et les
> affinages concrets (avec localisation + correctif proposé) issus de l'audit du code.
>
> **Contre-analyse (Claude Code, 2026-07-02) :** chaque recommandation a été
> revérifiée contre le code réel — verdicts dans les encadrés « ⚖️ Contre-analyse »
> sous chaque point, synthèse et ordre d'attaque révisé en **§5**. À noter : l'audit
> précède les correctifs CoreAudio (`docs/23`, 2026-07-02) — la suite est passée de
> 505 à **530 tests** depuis.

---

## 1. État d'avancement

### ✅ Terminé (macOS complet)

| Phase | Tâche | Doc |
|---|---|---|
| 0 | Socle : archi en couches, tray, machine à états, IPC | `03` |
| 0.5 | POC capture audio système — ScreenCaptureKit retenu | `04` |
| 1 | Mode Dictée (mlx-whisper → presse-papiers) | `03` |
| 2 | Mode Réunion (SCK + .md incrémental, pool MLX isolé) | `03` |
| 3 | Journal + Préférences + Historique | `03` |
| 3.5 | Reconnexion micro à chaud (Qt Multimedia) | `20` |
| A | Annulation d'écho AEC (LiveKit AEC3) | `05`, `06` |
| D | Diarization « qui a parlé » (pyannote + onboarding token HF) | `07`, `13` |
| B | Outil benchmark cross-platform (bundle portable) | `08` |
| UX | Refonte Historique · transcription différée · spinner · prompts · titre/durée · modèle à chaud · onboarding diarization · identité d'icône | `09`→`15` |
| 4b | Modèle `large-v3-turbo` (modèle par défaut) | `19` |

### 🟡 En cours / ⬜ À faire

| Phase | Tâche | Statut | Détail |
|---|---|---|---|
| **4** | **Packaging macOS** (`.dmg`, permissions stables) | 🟡 en pause | Code prêt, certificat local créé. **Le build PyInstaller n'est pas lancé → verrou de la distribution.** |
| **5** | **Portage Windows** | 🔄 code spike terminé, build VM en attente | `factory._windows()` retourne **tous des stubs**. Moteur réel codé **après** décision du spike (4 backends × 4 modèles comparés sur Bastien/Alix). Périmètre v1 : Dictée + Réunion+AEC, **pas de diarization**. |
| **6** | **Portage Linux** | ⬜ | PipeWire, faster-whisper, systemd, AppImage. `factory._linux()` = stubs. |

### 🗺️ Roadmap post-v1 (prévue, non prioritaire)

- `whisper.cpp-Vulkan` (GPU AMD/Intel)
- **Raccourcis globaux natifs** — interface `RaccourcisGlobaux` déclarée mais **vide** (`platform/interfaces.py:139`)
- Compte-rendu via **LLM** depuis l'Historique
- CI multi-OS (GitHub Actions)
- Signature/notarisation macOS + Authenticode Windows

---

## 2. Recommandations d'affinage

Classées par priorité. Chaque entrée précise : **problème**, **localisation**,
**impact**, **correctif proposé** et **complexité estimée**.

### 🔴 Priorité 1 — Bloquant pour la distribution

#### R1. Incohérence de bundle id

- **Problème :** deux valeurs de bundle id coexistent dans le code.
- **Localisation :**
  - `packaging/debriefMeet.spec:23` → `"com.sylvaingarcia.debriefmeet"`
  - `src/debrief_meet/platform/macos/demarrage_auto.py:11` → `"net.bluemind.debriefmeet"`
- **Impact :** le LaunchAgent d'autostart ne pointera pas vers l'app signée →
  l'autostart cassera en production. Risque de dédoublement des permissions TCC
  (l'app signée et l'agent référencent deux identités différentes).
- **Correctif :** harmoniser sur `com.sylvaingarcia.debriefmeet` dans
  `demarrage_auto.py` (et vérifier qu'aucun autre fichier ne référence l'ancien id).
- **Complexité :** ~5 min.

> ⚖️ **Contre-analyse (2026-07-02) : CONFIRMÉ — à traiter.** Vérifié : les deux
> valeurs coexistent bien (seules occurrences dans `src/` et `packaging/`).
> Point déjà connu (CLAUDE.md) et **déjà inscrit** dans `docs/16` §5.4 — à faire
> avant le premier build PyInstaller.

#### R2. Téléchargement du modèle = fausse barre de progression

- **Problème :** la progression réelle n'est jamais remontée pendant le téléchargement.
- **Localisation :** `src/debrief_meet/platform/macos/moteur_mlx.py:212`
  ```python
  def telecharger_modele(self, nom, progression=None):
      snapshot_download(resoudre_mlx(nom))   # bloque ~1 min, aucun callback
      if progression:
          progression(1.0)                    # saute direct à 100 %
  ```
- **Impact :** au premier lancement (DL initial ~1 Go), l'utilisateur n'a aucun
  feedback réel. L'UI affiche une barre « indéterminée » ; peut passer pour un freeze.
- **Correctif :** `snapshot_download` accepte un `callback` de progression :
  ```python
  snapshot_download(resoudre_mlx(nom), callback=progression if progression else None)
  ```
- **Complexité :** ~10 min.

> ⚖️ **Contre-analyse (2026-07-02) : problème RÉEL, correctif proposé FAUX.**
> Vérifié sur la signature réelle de `snapshot_download` (huggingface_hub du venv) :
> **aucun paramètre `callback` n'existe** — appliquer ce correctif tel quel plante.
> Le vrai levier est le paramètre `tqdm_class` (sous-classe relayant la progression),
> soit ~1-2 h avec tests, pas 10 min. Impact aussi surestimé : l'UI affiche déjà une
> barre indéterminée, pas un freeze. **Reclassé : confort UX (P3), non bloquant Phase 4.**

---

### 🟡 Priorité 2 — Robustesse

#### R3. État partiel si exception dans `_demarrer()` (Réunion)

- **Problème :** un échec entre l'init du micro et le `timer.start()` laisse
  l'orchestrateur dans un état incohérent (`_actif=True` mais timer mort).
- **Localisation :** `src/debrief_meet/core/reunion.py:140` (`OrchestrateurReunion._demarrer`)
  ```python
  self._actif = True                       # positionné tôt
  ...
  self._micro.demarrer(...)                # protégé (try/except)
  if self._avec_systeme:
      self._systeme.demarrer()             # ← PAS protégé : peut lever
  ...
  self._timer.start(...)                   # pas atteint si crash au-dessus
  ```
- **Impact :** si `systeme.demarrer()` lève (ex. permission SCK révoquée), `_arreter()`
  suppose un état cohérent → comportement indéfini à l'arrêt.
- **Correctif :** envelopper la séquence dans un `try/except` appelant un nettoyage
  (`_arreter()` partiel / rollback) en cas d'échec, ou tester
  `self._systeme.disponible()` avant `demarrer()` (symétrique à la branche micro).
- **Complexité :** ~20 min.

> ⚖️ **Contre-analyse (2026-07-02) : CONFIRMÉ, mais l'option (b) du correctif est
> déjà en place.** `disponible()` est bien testé avant `demarrer()`
> (`reunion.py:146` → `_avec_systeme`) — l'audit l'a manqué. Le risque résiduel :
> `systeme.demarrer()` qui lève *malgré* `disponible()`==True (permission SCK
> révoquée entre-temps, helper qui ne spawn pas). L'exception remonte dans un slot
> Qt → avalée, `_actif=True` sans timer → mode Réunion zombie. Rare sur macOS, mais
> l'orchestrateur est du `core/` partagé : les adaptateurs Windows (Phase 5) rendront
> ce chemin d'échec bien plus probable. **À traiter (option (a), try/except +
> rollback) avant de coder `platform/windows/` — inscrit dans `docs/03` Phase 5.**

#### R4. `Config.get()` silencieux vs `Config.set()` strict

- **Problème :** asymétrie — `get()` retourne `None` silencieusement sur une clé
  inconnue, alors que `set()` lève `KeyError`.
- **Localisation :** `src/debrief_meet/core/config.py:66`
  ```python
  def get(self, cle):    return self._donnees.get(cle, _DEFAUTS.get(cle))   # → None
  def set(self, cle, v): ... raise KeyError(...)                             # → lève
  ```
- **Impact :** un `None` qui se propage (ex. typo sur `intervalle_reunion`)
  devient un `TypeError: None * 1000` loin de la cause, difficile à diagnostiquer.
- **Correctif :** rendre symétrique — soit `get()` lève aussi sur clé inconnue,
  soit les deux replient avec un `logger.warning`.
- **Complexité :** ~10 min.

> ⚖️ **Contre-analyse (2026-07-02) : CONFIRMÉ, mais mineur.** L'asymétrie est réelle
> (`config.py:66`), le fix (faire lever `get()` sur clé hors `_DEFAUTS`) est bon et
> pas cher. Aucune typo n'existe aujourd'hui (suite verte). **Hygiène : à faire au
> prochain passage dans `config.py`, pas en chantier dédié. Reclassé P3.**

---

### 🟢 Priorité 3 — Finesse (nice-to-have)

#### R5. Démarrage worker MLX en fire-and-forget

- **Problème :** `charger_modele()` lance les workers en threads daemon sans
  attendre ; `transcrire()` fait `pool.get(timeout=90)`. Sur disque lent
  (modèle ~1 Go), le timeout peut être atteint → message d'erreur générique.
- **Localisation :** `src/debrief_meet/platform/macos/moteur_mlx.py:148` (`charger_modele`)
- **Correctif :** exposer l'`threading.Event` « prêt » du `_WorkerSubprocess`
  (déjà présent) au niveau du moteur pour attendre proprement avec feedback UI
  (« Préparation du moteur… ») plutôt qu'un timeout brut.
- **Complexité :** ~30 min.

> ⚖️ **Contre-analyse (2026-07-02) : CONFIRMÉ, classement P3 correct.** Le pattern
> fire-and-forget est bien là (`charger_modele`, threads daemon sans attente). Cas
> limite réel mais rare (premier chargement sur disque lent), avec repli existant
> (erreur + retry possible). **À garder pour la finition, comme le dit l'audit.**

#### R6. Médiane de cross-corrélation AEC instable sur audio court

- **Problème :** le calcul de `qualite` (pic/médiane) peut exploser sur des
  fenêtres courtes où peu de valeurs de corrélation sont positives.
- **Localisation :** `src/debrief_meet/core/aec.py:93`
  ```python
  mediane = float(np.median(corr[corr > 0])) if np.any(corr > 0) else 0.0
  ```
- **Impact :** risque de valider un faux délai sur audio court (faux verrou).
  Le seuil `QUALITE_CORR_MIN = 10.0` filtre les pires cas, mais reste perfectible.
- **Correctif :** ajouter (a) un seuil absolu sur le pic en complément du ratio, et
  (b) un nombre minimum d'échantillons positifs avant de calculer la médiane.
- **Complexité :** ~20 min (+ validation sur les benchs réels).

> ⚖️ **Contre-analyse (2026-07-02) : NE PAS TOUCHER sans bug observé.** Le scénario
> d'échec est spéculatif et il existe déjà **deux** garde-fous : le seuil
> `QUALITE_CORR_MIN = 10.0` **et** la calibration différée (pic pas franc → on
> retente plus tard, `aec.py:241`) — l'audit ne mentionne que le premier. Modifier
> un algo de calibration validé sur bancs réels sans défaillance constatée = risque
> sans bénéfice démontré. **À ne reprendre que si un faux verrou survient en vrai.**

#### R7. `decoder_audio_16k` lance ffmpeg sans vérifier sa présence

- **Problème :** si ffmpeg est absent, `subprocess.run(["ffmpeg", ...])` lève un
  `FileNotFoundError` peu clair pour l'utilisateur.
- **Localisation :** `src/debrief_meet/core/audio.py:82` (`_decoder_ffmpeg`)
- **Impact :** message d'erreur cryptique lors de la diarization sur audio Opus.
- **Correctif :** vérifier `shutil.which("ffmpeg")` en amont et lever une erreur
  typée avec message explicite (« ffmpeg requis pour relire l'audio Opus ») +
  rappel du repli WAV.
- **Complexité :** ~10 min.

> ⚖️ **Contre-analyse (2026-07-02) : le point tel quel est mineur, mais il cache un
> vrai sujet Phase 4.** Côté **écriture**, le repli existe déjà : sans ffmpeg,
> `EnregistreurAudioReunion` enregistre en `.wav` relisible via scipy
> (`fichiers.py:229`, `_ffmpeg_present()`) — pas de blocage. Les vrais restes :
> (a) message cryptique à la **relecture** d'un `.opus` existant si ffmpeg a disparu
> depuis l'enregistrement ; (b) surtout, **dans l'app packagée** : lancée depuis le
> Finder, le `PATH` est minimal (sans `/opt/homebrew/bin`) → `shutil.which("ffmpeg")`
> échouera dans le bundle *même avec ffmpeg installé via brew* → rétention en WAV
> (volumineux) et `.opus` historiques (enregistrés depuis le venv de dev) illisibles
> depuis l'app. **Décision à prendre en Phase 4 — inscrite dans `docs/16` §5.5.**

---

## 3. Qualité générale (verdict)

| Dimension | Note | Commentaire |
|---|---|---|
| **Architecture** | ⭐⭐⭐⭐⭐ | Couches, ABC, factory, injection — modèle |
| **Robustesse concurrence** | ⭐⭐⭐⭐⭐ | Pièges Qt (SIGBUS, SIGSEGV, `sender()`) traqués et résolus |
| **Tests** | ⭐⭐⭐⭐ | 505 tests, couverture configurée, fakes propres |
| **Documentation** | ⭐⭐⭐⭐⭐ | 20 docs numérotés + CLAUDE.md + README — exemplaire |
| **Gestion d'erreurs** | ⭐⭐⭐⭐ | Replis partout ; quelques états partiels à durcir (R3) |
| **Sécurité / privé** | ⭐⭐⭐⭐⭐ | 100 % offline, token HF à la volée jamais stocké |
| **Maintenabilité** | ⭐⭐⭐⭐⭐ | Les commentaires expliquent le *pourquoi*, pas le *quoi* |

Les recommandations ci-dessus sont des **affinements**, pas des défauts de
conception. L'architecture est saine et prête pour le portage.

---

## 4. Ordre d'attaque suggéré

1. **R1 + R2** (~15 min) → les deux seuls **vraiment** bloquants pour la Phase 4 (packaging).
2. **Lancer le build PyInstaller** (Phase 4) → c'est LE verrou de la distribution.
3. **R3 + R4** (~30 min) → sécurisent le cœur avant le portage Windows.
4. **Phase 5 Windows** → relancer `scripts/build_spike_backends_vm.sh`, récupérer
   les zip, décider les backends à embarquer, puis coder `platform/windows/`.
5. **R5, R6, R7** → finition, non bloquante.

---

## 5. Contre-analyse — synthèse & ordre révisé (Claude Code, 2026-07-02)

Chaque point revérifié contre le code réel (localisations toutes exactes).
Verdicts détaillés dans les encadrés ⚖️ ci-dessus.

| # | Verdict | Priorité révisée | Suivi |
|---|---------|------------------|-------|
| R1 | ✅ Confirmé | 🔴 avant build PyInstaller | `docs/16` §5.4 (déjà inscrit) |
| R2 | ⚠️ Problème réel, **correctif halluciné** (`callback` n'existe pas ; vrai fix = `tqdm_class`, ~1-2 h) | 🟢 confort UX, non bloquant | ce doc |
| R3 | ✅ Confirmé (mais option (b) déjà en place — `disponible()` testé) | 🟡 avant `platform/windows/` | `docs/03` Phase 5 |
| R4 | ✅ Confirmé, mineur | 🟢 hygiène au passage | ce doc |
| R5 | ✅ Confirmé | 🟢 finition | ce doc |
| R6 | ❌ Spéculatif — 2 garde-fous déjà en place, ne pas toucher sans bug observé | ⬜ sur incident seulement | ce doc |
| R7 | ⚠️ Repli WAV écriture déjà là ; le vrai sujet = **ffmpeg introuvable depuis le bundle** (PATH Finder) | 🔴 décision Phase 4 | `docs/16` §5.5 |

### Ordre d'attaque révisé

1. **R1** (5 min) avant le premier build PyInstaller — voir `docs/16` §5.4.
2. **Décision ffmpeg** (R7 élargi) pendant la validation du build — voir `docs/16` §5.5.
3. **R3** (try/except + rollback dans `_demarrer()`) avant de coder `platform/windows/` — voir `docs/03` Phase 5.
4. **R4** par hygiène au prochain passage dans `config.py` ; **R2** (via `tqdm_class`) et **R5** en confort UX plus tard ; **R6** seulement sur bug observé.

> Différences avec le §4 original : **R2 sort du bloquant** (l'UI a déjà une barre
> indéterminée, et le correctif proposé ne compile pas) ; **R7 monte en Phase 4**
> sous sa vraie forme (comportement de l'app packagée sans ffmpeg dans le PATH).
