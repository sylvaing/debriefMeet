# Phase 5 — Transposition Windows des problèmes déjà traités sur macOS

> **Statut : 📝 ANALYSE de référence** (2026-07-03). Aucune ligne de code ici : ce
> document passe en revue chaque problème rencontré et corrigé sur macOS
> (docs/20, 22, 23, 24/26, 25, 27, 28, 29) et statue : *se reproduit-il sur
> Windows ? le fix du cœur couvre-t-il déjà ? sinon, quelle exigence pour les
> adaptateurs Windows ?* Ses conclusions sont **normatives pour docs/34** (chaque
> exigence E-xx y est reprise) et alimentent le plan de tests.

---

## 1. Synthèse

| Doc macOS | Problème | Transposabilité Windows | Verdict |
|-----------|----------|------------------------|---------|
| 20 — continuité micro 16 kHz | taux natifs variables (AirPods -10851) | mécanisme différent (WASAPI vs CoreAudio), **symptôme identique possible** | ✅ couvert par le cœur — à observer via logs |
| 25 — hot-plug micro / table PortAudio figée | énumération PortAudio figée au lancement | **PortAudio a le même comportement sur Windows** | ✅ couvert — tests + logs |
| 22 — hallucinations Whisper sur silence | Whisper hallucine sur tranches quasi silencieuses | **indépendant de l'OS** (propriété du modèle) | ⚠️ non fixé partout — sonde de détection requise (E-1) |
| 23 — fuites CoreAudio (double-start, helper orphelin) | ressources audio jamais libérées | CoreAudio n'existe pas, **les motifs oui** | 🔁 à transposer en exigences sur les adaptateurs (E-2, E-3) |
| 24/26 — crash QThread à l'arrêt | wait() ignoré + read() worker bloquant | **générique Qt/threads**, indépendant de l'OS | ✅ cœur fixé — exigence sur le nouveau moteur (E-4) |
| 27 — dictée/journal muets | porte anti-silence non compensée sur micro faible | générique (dépend du niveau micro, très variable sur Windows) | ✅ couvert par héritage — verrou de non-régression (E-5) |
| 28 — raccourcis globaux | Carbon = macOS uniquement | à réimplémenter (RegisterHotKey) | 🔁 réimplémentation (E-6) |
| 29 — diarization pyannote 4.x | API HF offline | diarization **hors périmètre v1 Windows** | ⛔ sans objet |

## 2. Analyses détaillées et exigences

### 2.1 docs/20 + docs/25 — micro : taux natifs, hot-plug, énumération figée

**macOS.** Deux bugs distincts : (a) CoreAudio refusait un taux imposé sur certains
périphériques BT (AirPods, erreur -10851) → fix = capturer au taux natif et
rééchantillonner vers un 16 kHz canonique dans `CaptureMicroSounddevice` ; (b) la
table de périphériques PortAudio est **figée au moment de `sd.query_devices()`
initial** → un micro branché après le lancement était invisible → fix docs/25
(réinitialisation PortAudio + `redemarrer()` sans vider le buffer, piloté par
`SurveillantPeripheriques`).

**Windows.** Même adaptateur (`platform/commun/micro_sounddevice.py`), même
PortAudio — qui a **exactement le même défaut d'énumération figée** sous WASAPI.
Les périphériques BT Windows exposent aussi des taux variables (casques en
profil headset 8/16 kHz vs A2DP 44.1/48 kHz — situation *pire* que sur Mac).
`SurveillantPeripheriques` (Qt Multimedia) est déjà cross-platform.

**Verdict : couvert par le cœur, rien à développer.** Exigences résiduelles :

- **E-7 (tests)** : les tests existants de `micro_sounddevice` et du redémarrage à
  chaud tournent déjà sans matériel — vérifier qu'aucun ne dépend d'un comportement
  CoreAudio (noms de périphériques, codes d'erreur en dur).
- **E-8 (logs)** : chaque (re)démarrage du micro logge : nom du périphérique résolu,
  host API (attendu : WASAPI ou MME — **si MME apparaît dans un log utilisateur,
  c'est un indice de latence/qualité dégradée**), taux natif, taux de sortie.

### 2.2 docs/22 — hallucinations Whisper sur silence (⚠️ risque ouvert, tous OS)

**Constat.** Non corrigé (hors scope v1) : une tranche quasi silencieuse amplifiée
par la normalisation peut atteindre Whisper et produire des hallucinations (« CO CO
CO », crédits coréens). Whisper CT2 (faster-whisper) a le même comportement de fond
que MLX — le risque existe donc sur Windows, et on ne pourra pas le reproduire
localement.

- **E-1 (sonde de détection à distance)** : pour chaque tranche transcrite, le DEBUG
  logge RMS d'origine, décision de la porte anti-silence, longueur du texte produit
  (docs/31 §3.7.2). La signature « RMS très bas + texte long » devient détectable
  dans un zip diagnostic sans reproduction locale. Aucun autre développement en v1.
- Note : faster-whisper expose un VAD intégré (`vad_filter=True`). **Ne pas
  l'activer en v1** (comportement différent de macOS = résultats non comparables) ;
  le garder en réserve comme correctif activable si E-1 révèle le problème chez
  Bastien/Alix.

### 2.3 docs/23 — fuites de ressources audio (motifs à transposer)

**macOS.** Deux fuites : double-start du micro (deux flux ouverts, l'un jamais
fermé) et helper SCK orphelin après un SIGKILL de l'app. CoreAudio et le helper
n'existent pas sur Windows, **mais les motifs sont universels**.

- **E-2 (idempotence)** : `CaptureAudioSystemeWasapi.demarrer()` appelé deux fois
  sans `arreter()` ne doit **jamais** ouvrir deux flux (soit no-op loggé WARNING,
  soit arrêt propre du premier — même sémantique que le fix micro docs/23).
  Test unitaire obligatoire avec `soundcard` mocké.
- **E-3 (pas d'orphelins)** : inventaire des ressources à libérer sur Windows :
  - thread d'enregistrement `soundcard` (in-process — pas de process helper, le
    risque « orphelin » devient « thread non joint / flux WASAPI non fermé ») :
    `arreter()`/`terminer()` ferment le recorder et joignent le thread avec timeout ;
  - workers subprocess faster-whisper : couverts par E-4 ;
  - mutex Win32 (docs/34 §6) : libéré par l'OS à la mort du process — rien à faire.
  Un SIGKILL de l'app ne laisse rien tourner : les workers enfants doivent mourir
  avec le parent (voir E-4).

### 2.4 docs/24 + docs/26 — crash QThread à l'arrêt

**macOS.** Fix appliqué **dans le cœur** : `core/arret_threads.py`
(`arreter_thread`/`proteger_thread`), registre des workers dans `MoteurMLX` +
`kill()` forcé des workers jamais rendus au pool. Le mécanisme déclencheur
(un `read()` bloquant dans le worker) est exactement ce qu'aura le futur moteur
Windows s'il suit le pattern subprocess.

- **E-4 (moteur Windows = mêmes garanties que MoteurMLX post-docs/26)** :
  `MoteurFasterWhisper` (docs/34 §1) doit :
  1. tenir un **registre de tous les workers créés** (pas seulement ceux du pool) ;
  2. `terminer()` : vider le pool avec timeout, puis `kill()` inconditionnel de
     tout worker du registre encore vivant ;
  3. côté worker, une fermeture de pipe → sortie en erreur propre (pas de blocage) ;
  4. les orchestrateurs (`reunion.py`, `dictee.py`, `journal.py`) utilisent déjà
     `arreter_thread` — **aucune modification du cœur attendue** ; si l'implémentation
     du moteur en réclame une, c'est un signal d'erreur de design à remonter.
  C'est la raison principale du choix subprocess (docs/30 §4.4) : in-process, une
  transcription gelée serait intuable et le crash reviendrait.

### 2.5 docs/27 — dictée/journal muets (porte anti-silence)

**macOS.** Fix structurel : la normalisation + porte anti-silence vivent dans la
classe de base `MoteurTranscription.transcrire()` (`platform/interfaces.py:34-43`),
les backends n'implémentent que `_transcrire_pret()`.

- **E-5 (héritage obligatoire)** : `MoteurFasterWhisper` implémente
  `_transcrire_pret()` et **n'override jamais `transcrire()`**. Test de
  non-régression : vérifier `MoteurFasterWhisper.transcrire is MoteurTranscription.transcrire`
  (même motif que le test équivalent MLX s'il existe — sinon l'ajouter pour les deux).

### 2.6 docs/28 — raccourcis globaux

**macOS.** Carbon `RegisterEventHotKey` via ctypes (piège `c_void_p` documenté),
format portable `QKeySequence`, interface `RaccourcisGlobaux` déjà en place avec
stubs Windows/Linux.

- **E-6 (réimplémentation Win32)** : `RegisterHotKey` (user32) + interception
  `WM_HOTKEY` par un `QAbstractNativeEventFilter` — spec complète docs/34 §5.
  Différences avec macOS à respecter :
  - défauts Windows `Ctrl+Alt+D/R/J` (décision D3 ; `Meta` = touche Windows,
    réservée par l'OS pour beaucoup de combos → on ne la met pas dans les défauts) ;
  - `RegisterHotKey` retourne `FALSE` si le combo est pris par une autre app →
    retourner `False` + log WARNING avec `GetLastError()` (même contrat que macOS) ;
  - `Ctrl+Alt+<lettre>` = `AltGr+<lettre>` sur clavier AZERTY Windows — risque de
    conflit de frappe (AltGr+D n'écrit rien en AZERTY standard, mais vérifier) ;
    les combos restent paramétrables dans les Préférences, c'est l'échappatoire.

### 2.7 docs/29 — diarization pyannote 4.x

Hors périmètre v1 Windows (docs/30 §3). Le fix (offline via `HF_HUB_OFFLINE`) est
dans le cœur et sera hérité le jour où la diarization sera portée. **Aucune action.**
Seule précaution : les exclusions PyInstaller (docs/32 §3.2) écartent `pyannote`/
`torch` du bundle Windows.

### 2.8 Cas connexe — bug AirPods/-10851 (mémoire projet, docs/20)

Déjà couvert par §2.1 : le rééchantillonnage systématique absorbe les changements de
taux. Les casques BT Windows basculant headset/A2DP **en cours de capture** sont le
scénario analogue à surveiller — E-8 rend la bascule visible dans les logs
(changement de taux natif loggé), `redemarrer()` la gère.

## 3. Récapitulatif des exigences pour docs/34

| ID | Exigence | Adaptateur concerné |
|----|----------|---------------------|
| E-1 | log RMS/porte/longueur texte par tranche (sonde hallucinations) | moteur (+ cœur déjà en place docs/27/31) |
| E-2 | `demarrer()` idempotent, jamais deux flux | capture système WASAPI |
| E-3 | arrêt = recorder fermé + thread joint (timeout) ; rien ne survit à l'app | capture système WASAPI |
| E-4 | registre workers + kill forcé + worker qui meurt sur pipe fermé | moteur faster-whisper |
| E-5 | pas d'override de `transcrire()` (normalisation héritée) | moteur faster-whisper |
| E-6 | RegisterHotKey, contrat `False`+log en cas de conflit, défauts Ctrl+Alt+D/R/J | raccourcis |
| E-7 | tests micro existants exempts de suppositions CoreAudio | micro (commun) |
| E-8 | logs périphérique/host API/taux à chaque (re)démarrage micro et loopback | micro + capture système |

Chaque E-xx doit être tracée dans docs/34 (section de l'adaptateur concerné) et
couverte par au moins un test sans matériel.
