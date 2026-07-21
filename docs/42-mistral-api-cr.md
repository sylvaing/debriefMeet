# Interco Mistral — transcription cloud + génération de compte-rendu (CR)

> **Statut : 🔄 CODE + TESTS UNITAIRES TERMINÉS (2026-07-21, Sonnet) — 1032 passed sans
> réseau (+75 tests). Reste : validation manuelle avec Sylvain + clé API Mistral réelle
> (les deux branches — transcript local et repli Voxtral) et mise à jour de la doc
> utilisateur (mention transcription cloud UE).**
> Spike de faisabilité VALIDÉ au préalable (2026-07-20) — chaîne complète exécutée sur une
> vraie réunion (voir « Résultats du spike » ci-dessous).
> Branche de travail : `claude/mistral-api-transcription-cr-f15d4a` (worktree dédié).
> Code du spike : `spike/mistral-cr/` (`spike_mistral_cr.py` + `README.md`).
> Code produit : `src/debrief_meet/core/mistral/` (client, transcription, decoupage,
> fusion, cr, pipeline) + `ui/remote_ia_view.py`, `ui/assistant_mistral.py`,
> `ui/testeur_connexion_mistral.py`, `ui/generateur_cr_mistral.py` + intégration
> `preferences_view.py`/`reunion_view.py`/`fenetre_principale.py`/`__main__.py`.
> **Décisions de cadrage validées avec Sylvain (2026-07-20) :**
> 1. **CR adaptatif (tranché après spike)** — par défaut le CR est rédigé à partir du
>    **transcript local existant** (rapide ~15 s, seul le *texte* part au cloud).
>    **Repli automatique** sur la **transcription Voxtral** (endpoint à la minute) quand il
>    n'y a pas de transcript local (mode enregistrement-seul). **Option avancée** pour
>    forcer Voxtral (local médiocre, ou envie de diarisation). Dans tous les cas, l'étape CR
>    utilise un modèle *texte* Mistral — **jamais** le chat multimodal audio→CR (plus cher
>    en tokens audio, limité à ~20 min, perd la séparation Moi/Participants).
> 2. **Ajout strictement optionnel** — le moteur de transcription **local reste le défaut**
>    et le mode 100 % hors-ligne intact. Mistral **n'est PAS** une implémentation de
>    `MoteurTranscription` et **ne touche pas** `platform/factory.py`. C'est un service
>    cloud séparé, sur le modèle de l'interco BlueMind (`core/bluemind/`).
> 3. **Déclenchement manuel** — bouton « Générer le CR (Mistral) » sur une réunion de
>    l'Historique. Pas de génération automatique en fin de réunion en v1.
>
> Avant livraison : `make test` (tous les tests actuels + nouveaux, tous verts, **sans réseau**).

---

## Résultats du spike de faisabilité (2026-07-20) — À LIRE EN PREMIER

Spike autonome `spike/mistral-cr/spike_mistral_cr.py` (httpx + ffmpeg système, sans
dépendance à l'app), exécuté sur une vraie réunion : piste micro **37,6 min** + piste
système **3,7 min** (Ogg Opus 24 kbps). **Chaîne complète OK** : transcription → fusion →
CR. Ces mesures **priment** sur les hypothèses des sections suivantes ; elles ont été
répercutées dans §5.1, §7.1, §7.3, §7.4, §10, §11.

### Verdicts

| Question | Résultat empirique |
|----------|--------------------|
| **Format `.opus` accepté directement ?** | **OUI** — upload direct du `.opus` court **et** long. **Aucun transcodage WAV nécessaire** (renverse l'ancienne §7.1). |
| **Longues réunions en 1 requête ?** | **OUI, PAS de découpage nécessaire** : la piste de **37,6 min** a été transcrite en **un seul appel** (88 s, 31201 car / 682 segments), format accepté. La limite « ~15 min » de la doc ne s'applique pas à l'endpoint multipart. Le découpage est **relégué en repli** (§10). |
| **Séparation Moi/Participants sans `diarize` ?** | OK, mais valable surtout en **visio** (voir « présentiel vs visio »). |
| **Qualité FR + noms ?** | **Excellente** avec `mistral-small-latest` : CR structuré (titre, participants, contexte, points numérotés, **Actions par responsable**), noms bien orthographiés. |

### Format & découpage (tranche §7.1 + §10)
- L'endpoint **accepte l'Ogg Opus directement, piste entière** → on envoie l'`.opus` tel
  quel, **sans transcodage ni découpage** (validé 37,6 min en 1 appel).
- **Découpage = repli seulement** (piste refusée pour durée / timeout). Si déclenché, se
  fait **sans ré-encodage** (copie Opus, compact) :
  ```
  ffmpeg -y -i src.opus -f segment -segment_time 840 -reset_timestamps 1 -c copy seg_%03d.ogg
  ```
  → chunks ~2,4 Mo / 14 min. Offset externe = `index × 840 s` (timestamps remis à 0 par
  `-reset_timestamps 1`).
- Le WAV 16 kHz n'est qu'un **dernier recours** si un format était refusé (HTTP 400/415/422)
  — très improbable puisque l'Opus est accepté.

### Robustesse réseau (tranche §7.3)
- Premier essai en **WAV 27 Mo** → `Broken pipe` (upload lent + mise en veille probable du
  Mac). Corrigé par chunks Opus compacts **+ reprises sur `httpx.TransportError`**
  (broken pipe, `ReadError`, `ConnectError`) avec backoff. **Validé en réel** : une coupure
  a été récupérée automatiquement (`reprise 1/2`).
- Conseiller **`caffeinate -i`** pendant un long run (éviter la veille).

### Découpage inutile par défaut (tranche §10) — **1 requête par piste**
Test `--pas-de-decoupage` : la piste de 37,6 min passe en **un seul appel** → **le défaut
devient « pas de découpage »**, le chunking n'est qu'un **repli** (piste très longue refusée
ou timeout). Corollaire : **1 requête par piste** (2 au total) → le problème de concurrence
ci-dessous **disparaît** sur le chemin normal.

### Concurrence / rate-limit — NE PAS paralléliser sur le tier gratuit
- Historique (quand on découpait) : 4 requêtes **en parallèle** = **488 s** (vs **177 s** en
  séquentiel) + une connexion lâchée. Le tier gratuit **throttle la concurrence**
  (mise en file silencieuse, sans 429 franc) → paralléliser est **contre-productif**.
- Avec « pas de découpage », il n'y a que 2 requêtes (1/piste) : **séquentiel**, aucun souci.
- Le produit **doit** quand même gérer le **429** (respect de `Retry-After` + backoff) au cas
  où, et ne jamais paralléliser sur tier gratuit.

### Piège httpx multipart (déjà rencontré et corrigé dans le spike)
En multipart (`files=...`), `data` **doit être un `dict`** ; une valeur-liste devient des
champs répétés (pour `context_bias`). Une **liste de tuples** casse l'encodage du corps
(`TypeError: sequence item N: expected a bytes-like object, tuple found`).

### Présentiel vs visio — implication sur la séparation des locuteurs
La piste système du test était à **−91 dB (silence total)** → réunion **en présentiel**,
tout capté par le micro (d'où un CR excellent mais issu d'une seule piste). Conséquence :
la séparation 2 pistes **n'aide qu'en visio** (audio système = participants distants). En
**présentiel**, tout est sur le micro → pour distinguer les intervenants il faut
**diariser** (`diarize` Voxtral sur la piste micro, ou la diarisation pyannote déjà dans
l'app, docs/07). Le CR reste lisible sans, mais sans étiquette de locuteur fiable.
→ **détecter et sauter les pistes silencieuses** (§7.4) reste indispensable.

### Timing observé
- **Pistes entières (1 requête/piste) : ~90 s** pour 41 min d'audio + CR → **le plus rapide**.
- Découpé séquentiel : ~177 s. Découpé parallèle (tier gratuit) : ~488 s.
- Conclusion : envoyer la piste entière est **plus simple ET plus rapide** ; le découpage
  ne se justifie qu'en repli sur les cas extrêmes.

---

## 1. Contexte et objectif

Aujourd'hui debriefMeet **ne génère aucun CR** : il transcrit en local (mlx-whisper /
faster-whisper) et, à la copie, préfixe un **prompt** (`core/prompts.py`,
`CR_SIMPLE_CONTENU`) à la transcription pour que l'utilisateur le colle dans un LLM
externe. Chaque réunion conserve par ailleurs **deux pistes audio Opus** retenues
(`<stem>_moi.opus`, `<stem>_systeme.opus`, mono 16 kHz, 24 kbps — cf. `core/fichiers.py`).

Objectif : ajouter un chemin **cloud Mistral** qui, à la demande, transforme une réunion
enregistrée en **compte-rendu Markdown fini**. L'étape CR est toujours la même (modèle
*texte* + prompt CR) ; ce qui varie, c'est **d'où vient le transcript** — logique
**adaptative** (décision 1) :

1. **Source du transcript** :
   - **par défaut → le transcript local** déjà produit par l'app (le `.md` de la réunion,
     ou `<stem>_locuteurs.md` s'il existe) : rapide (~15 s) et **seul le texte** part au
     cloud (pas l'audio) ;
   - **repli automatique → transcription Voxtral** des pistes Opus (endpoint à la minute)
     quand il **n'y a pas** de transcript local exploitable (mode enregistrement-seul) ;
   - **forçable** (option avancée) vers Voxtral si le local est médiocre / pour diariser.
2. **Rédaction du CR** : transcript (quelle qu'en soit la source) + **prompt CR actif**
   (`prompts.contenu_actif`) → modèle *texte* Mistral.

Résultat écrit dans un fichier `<stem>_CR.md` à côté de la réunion.

> **Pourquoi réutiliser le transcript local par défaut.** Le CR (appel texte) est **rapide**
> et n'envoie que du texte ; re-transcrire l'audio via Voxtral est l'étape lente. Réutiliser
> le transcript local **évite** cette étape. Quand une transcription cloud est nécessaire,
> on passe par l'**endpoint transcription**, **jamais** le chat multimodal audio→CR (limité
> à ~20 min et sans séparation Moi/Participants).

### 1.1 Pourquoi ce n'est PAS un `MoteurTranscription`

L'ABC `MoteurTranscription` (`platform/interfaces.py`) prend un `np.ndarray` float32 16 kHz
et sert la transcription **en direct, par tranches de 30 s**, dans la boucle de réunion.
Le chemin Mistral est un **post-traitement à la demande sur fichiers**, réseau, hors ligne
de capture. Le brancher dans `factory.py` mélangerait deux responsabilités et casserait le
mode hors-ligne. On le modélise donc comme **service cloud** parallèle (comme BlueMind),
consommé par un bouton d'Historique — jamais par `OrchestrateurReunion`.

## 2. Contrainte transverse : opt-in, confidentialité, non-régression

Au même rang que la règle d'or des couches :

- **Confidentialité — le point sensible.** L'app se vend comme « transcription **locale** ».
  Ce chemin **envoie l'audio et la transcription aux serveurs Mistral** (UE, cf. §7.6).
  Donc : **opt-in explicite**, invisible tant que non configuré, et **confirmation au
  premier envoi** (« Cet enregistrement va être envoyé aux serveurs Mistral (UE) pour
  transcription et rédaction du CR. Continuer ? » + case « ne plus demander »).
- **Mistral non configuré → interco invisible.** Pas de clé API en config ⇒ aucun bouton,
  aucune requête, aucun message. Strictement additif (comme `bluemind_url` vide).
- **Aucune régression du local.** `platform/`, `factory.py`, `reunion.py`, la boucle de
  transcription live et le mode hors-ligne **ne changent pas**.
- **Toute I/O réseau vit dans un worker en tâche de fond** (jamais le thread UI). Comme
  l'action est **déclenchée par l'utilisateur**, les erreurs s'affichent clairement **au
  clic** (contrairement à BlueMind qui est silencieux) : message actionnable + log.
- **Aucune notion de coût dans l'app.** L'application n'affiche/loggue **jamais** de
  prix/coût/tarif (€, $) — ni UI, ni didacticiel, ni logs (§11). Observabilité = usage
  neutre (minutes audio, tokens). Un garde-fou de **durée max** (réglable) évite les envois
  géants accidentels.

## 3. Architecture

```
core/mistral/                 ← pur Python : aucun import OS-specific ni Qt (règle d'or)
├── __init__.py
├── client.py                 # ClientMistral : httpx sync, auth Bearer, erreurs typées, timeouts, reprises TransportError + 429/Retry-After
├── transcription.py          # transcrire_fichier(chemin, langue, context_bias) → TranscriptionMistral (Opus direct ; repli WAV si format refusé)
├── cr.py                     # generer_cr(transcription, prompt, modele) → markdown (source-agnostique)
├── decoupage.py              # REPLI seulement : découpe Opus par COPIE ffmpeg si une piste longue est refusée/timeout (pas le chemin normal — cf. spike)
├── fusion.py                 # entrelace les segments Moi + Participants par timestamp → transcript étiqueté
└── pipeline.py               # orchestration bout-en-bout (2 pistes → CR → <stem>_CR.md)
                              # (PAS de module de coût : aucune notion de prix dans l'app, §11)

ui/
├── preferences_view.py       # + section « Remote IA » (avant Journalisation), extensible — §9.1
├── remote_ia_view.py         # widget de la section : bloc par fournisseur (Mistral en v1) — §9.1
├── assistant_mistral.py      # mini-didacticiel création compte + clé API (miroir assistant_diarization.py) — §9.4
├── testeur_connexion_mistral.py  # bouton « Tester la connexion » (miroir testeur_connexion_bluemind.py)
├── reunion_view.py           # + action « Générer le CR (Mistral) » par réunion — §9.2
└── generateur_cr_mistral.py  # QThread worker + QProgressDialog (miroir gestionnaire_diarization.py)

core/config.py                # + clés mistral_* dans _DEFAUTS — §8
docs/42-mistral-api-cr.md     # ce document
tests/test_mistral_*.py       # respx (sans réseau) + tests d'intégration gated — §12
```

**Règle d'or à respecter :** `core/mistral/` n'importe **ni Qt ni module OS**. Le seul
appel « plateforme » toléré est `core/fichiers.chemin_ffmpeg()` (déjà pur, résout le binaire
embarqué) et `core/audio.decoder_audio_16k`. Toute la logique Qt (dialogs, thread, progress)
vit dans `ui/`.

## 4. Flux de bout en bout (le bouton « Générer le CR »)

1. **Pré-conditions.** Clé API configurée (sinon bouton absent).
2. **Choix de la source du transcript** (logique adaptative, décision 1) :
   - **par défaut** : chercher un **transcript local** — le `.md` de la réunion (ou
     `<stem>_locuteurs.md` si présent). Non vide → c'est la source, **on saute la
     transcription cloud** (pas d'upload audio).
   - **sinon** (pas de `.md`, ou vide → enregistrement-seul) : **repli Voxtral**. Retrouver
     les pistes via `core.fichiers.chemins_audio_reunion(stem)` → `_moi.opus`/`_systeme.opus`
     (repli `.wav`). Aucune piste ni transcript → message « rien à exploiter pour cette
     réunion ».
   - **forçage Voxtral** (option avancée, §9) : ignore le transcript local et re-transcrit.
3. **Confirmation confidentialité** (§2) au premier envoi — le message précise ce qui part
   (texte seul, ou audio si transcription Voxtral).
4. **Worker de fond** (`generateur_cr_mistral.py`, QThread) + `QProgressDialog`.
5. **[branche Voxtral uniquement] Transcription** (`transcription.py`) : **envoyer chaque
   piste ENTIÈRE** (`.opus`) en un seul appel `POST /v1/audio/transcriptions`
   (`voxtral-mini-latest`), `language` = config `langue`, `context_bias` = noms d'invités
   BlueMind si `<stem>.bluemind.json` existe (§7.5), `timestamp_granularities=["segment"]`.
   **1 requête par piste, en séquentiel** (§7.3). Détecter/sauter les pistes silencieuses (§7.4).
   → **Découpage = repli** (`decoupage.py`, §10) : seulement si une piste très longue est
   refusée (erreur durée) ou timeout ; alors segments Opus par copie + offset réappliqué.
   → **En visio, PAS de `diarize`** (séparation via les 2 pistes). **En présentiel** (piste
   système silencieuse), tout est sur le micro → `diarize` ou diarisation pyannote si on
   veut des étiquettes de locuteur (§14).
6. **[branche Voxtral uniquement] Fusion** (`fusion.py`) : entrelacer les segments Moi +
   Participants par timestamp → transcript étiqueté `**Moi :**` / `**Participants :**`
   (réutiliser `core/fichiers.py::_entrelaces`, l.455).
   → **Récupération en local** : si la réunion était un **placeholder « audio seul »**
   (transcription pas encore faite), la transcription Voxtral est **réécrite dans le `.md`
   local** (remplace le placeholder), avec la mention « Transcription générée par Voxtral
   (Mistral) » et préservation du titre + de la durée. On **n'écrase jamais** un transcript
   local déjà présent (cas forçage Voxtral).
7. **Rédaction CR** (`cr.py`, commun aux deux branches) : `POST /v1/chat/completions` avec
   un modèle **texte** (`mistral_modele_cr`), message = `prompts.contenu_actif(...)` +
   transcript, **+ éléments d'association BlueMind s'ils existent** : sujet (= titre de
   l'événement) et liste des **participants cochés**, injectés dans le prompt pour un CR
   mieux cadré, quelle que soit la source du transcript. `cr.py` prend **du texte en
   entrée** (source-agnostique) → même code que la source vienne du local ou de Voxtral.
8. **Écriture** : `<stem>_CR.md` à côté du `.md`. Rafraîchir l'Historique, proposer
   « Ouvrir » / « Copier ». Logger l'**usage** (source, minutes, tokens) — **jamais de coût**
   (§11).
9. **Erreurs** : toute exception `client.py` → message clair au clic (clé invalide, quota,
   429, réseau, format refusé, durée dépassée), rien d'écrit à moitié sur disque.

## 5. Détails API Mistral (vérifiés 2026-07-20)

> ⚠️ Les **IDs de modèles** évoluent. Sonnet doit **reconfirmer** les IDs exacts sur
> https://docs.mistral.ai au moment de l'implémentation (les `*-latest` ci-dessous sont
> stables mais un modèle daté peut être préféré).

### 5.1 Endpoint transcription (étape 1)
- **Route** : `POST /v1/audio/transcriptions` — SDK : `client.audio.transcriptions.complete(...)`.
- **Modèle** : `voxtral-mini-latest` (alias de `voxtral-mini-2507`, « Transcribe »).
- **Entrée** : upload fichier (multipart), ou `file_url`, ou `file_id` (via `/v1/files`).
  Formats acceptés : **mp3, wav, m4a, flac, ogg**, jusqu'à **1 Go**. **L'Ogg Opus (`.opus`)
  est accepté directement** — confirmé par le spike, mime `audio/ogg`.
- **Multipart** : `data` = **dict** (piège httpx, cf. Résultats du spike), champ fichier
  `files={"file": (nom, flux, "audio/ogg")}`.
- **Paramètres utiles** : `language` (ex. `"fr"`), `timestamp_granularities` (`"segment"`/`"word"`),
  `diarize` (bool — **on laisse `false`** en visio ; utile en présentiel, cf. spike),
  `context_bias` (jusqu'à 100 termes → noms d'invités), `temperature`.
- **Réponse** (confirmée par le spike) : `text`, `language`, `segments` (chaque segment a
  `start` / `end` / `text`), `usage` (`prompt_tokens` / `completion_tokens`).
- **Limite de durée par requête** : la doc annonce « ~15 min », mais le spike a transcrit
  **37,6 min en un seul appel** → cette limite **ne s'applique pas** à l'endpoint multipart.
  On envoie la piste entière ; le découpage n'est qu'un repli (§10). Plafond exact inconnu
  (batch documenté ~3 h, fichier ≤ 1 Go).

### 5.2 Endpoint chat texte (étape 2 — rédaction du CR)
- **Route** : `POST /v1/chat/completions` — SDK : `client.chat.complete(...)`.
- **Modèle** (config `mistral_modele_cr`, défaut proposé `mistral-small-latest`) :
  `mistral-small-latest` (économique) ; exposer aussi `mistral-medium-latest` /
  `mistral-large-latest` (meilleure qualité de synthèse) dans le combo Préférences.
  **Ne pas** utiliser un modèle Voxtral ici : c'est du texte pur.
- **Messages** : soit `system` = prompt CR + `user` = transcript, soit `user` unique
  reprenant `prompts.prefixer(transcript, contenu)`. Tester les deux ; garder le plus propre.

### 5.3 Auth & base URL
- Header `Authorization: Bearer <mistral_cle_api>`.
- Base URL par défaut `https://api.mistral.ai`, **surchargée** par `mistral_base_url`
  (utile pour tests / proxy). Valider l'URL comme `core/bluemind/client.py::valider_url`.

## 6. Réutilisation maximale de l'existant

| Besoin | Réutiliser |
|--------|-----------|
| Client HTTP sync + erreurs typées + timeouts | pattern `core/bluemind/client.py` (httpx déjà dépendance) |
| Décoder Opus/WAV → PCM 16 kHz | `core/audio.decoder_audio_16k` / `_decoder_ffmpeg` |
| Localiser ffmpeg embarqué | `core/fichiers.chemin_ffmpeg()` |
| Retrouver les pistes d'une réunion | `core/fichiers.chemins_audio_reunion(stem)` |
| Entrelacer Moi/Participants par timestamp | `core/fichiers.py::_entrelaces` (l.455) |
| Prompt CR actif | `core/prompts.contenu_actif` + `prefixer` |
| Noms d'invités (context_bias) | sidecar `<stem>.bluemind.json` (docs/40, `core/bluemind/association.py`) |
| Section Préférences + test connexion | `ui/preferences_view.py` section BlueMind + `ui/testeur_connexion_bluemind.py` |
| Assistant/didacticiel guidé (création compte + clé) | `ui/assistant_diarization.py` + docs/13-diarization-onboarding.md |
| Worker de fond + progress | `ui/gestionnaire_diarization.py`, `ui/chargeur_modele.py` (QThread + QProgressDialog) |
| Persistance réglages | `core/config.py` (`_DEFAUTS` + get/set validés) |
| Mock HTTP en test | `respx` (déjà en dépendance `dev`) |

## 7. Points techniques à trancher pendant l'implémentation

### 7.1 Format d'upload — Opus direct, piste entière (tranché par le spike)
**L'Ogg Opus est accepté directement par l'endpoint, y compris une piste longue** (37,6 min
transcrite en un seul appel — cf. Résultats du spike). **On envoie donc la piste `.opus`
entière telle quelle** (mime `audio/ogg`), **sans transcodage ni découpage**. Le découpage
Opus par copie n'intervient qu'en **repli** sur piste refusée/timeout (§10).

Le **décodage/transcodage WAV 16 kHz** n'est plus le chemin par défaut ; il ne subsiste
qu'en **repli** si un jour un format était refusé (HTTP 400/415/422) : dans ce cas
seulement, transcoder l'unité fautive via `core/audio` + ffmpeg puis réessayer. Cela évite
un upload lourd (~27 Mo/14 min en WAV vs ~2,4 Mo en Opus) et la fragilité réseau associée.

### 7.2 Fichiers temporaires
Segments **Opus** (`.ogg`, copie sans ré-encodage) dans le dossier scratch/temp
(`tempfile.mkdtemp`), **supprimés** en fin de worker (y compris sur erreur — `try/finally`).
**Ne jamais** écrire les temporaires dans `~/Documents/debriefMeet`.

### 7.3 Timeouts, reprises réseau, rate-limit (mesuré au spike)
- **Timeouts** longs (transcription lente) : connect ~10 s, **read ~600 s**. Réglables.
- **1 requête par piste** (piste entière, §7.1), **en séquentiel** → 2 appels max, pas de
  concurrence sur le chemin normal.
- **Reprises sur `httpx.TransportError`** (broken pipe, `ReadError`, `ConnectError`) : ~3
  essais, backoff. **Validé en réel** (une coupure récupérée automatiquement).
- **HTTP 429 (rate-limit)** : à gérer explicitement — respecter l'en-tête `Retry-After`,
  backoff exponentiel. Le tier gratuit **throttle silencieusement la concurrence** (spike :
  4 requêtes parallèles = 488 s vs 177 s séquentiel) → **ne jamais paralléliser** sur tier
  gratuit (de toute façon inutile puisqu'on n'a qu'1 requête/piste).
- **Erreur de durée (4xx) ou timeout** sur une piste longue → bascule sur le **découpage**
  (§10). **4xx de format** (très improbable, Opus accepté) → dernier recours = transcodage
  WAV puis réessai. **401/403** (clé invalide) → erreur claire, pas de retry.

### 7.4 Piste vide / silencieuse — CAS RÉEL confirmé
Confirmé par le spike : la piste système était à **−91 dB (silence numérique total)** →
Voxtral a renvoyé **0 caractère**. Détecter en amont (durée nulle, RMS ≈ silence, ou `text`
vide) et **ne pas envoyer** / étiqueter la piste comme absente — évite de transcrire du
silence (moitié des minutes audio en présentiel) et d'ajouter du vide au CR. Ne pas planter
la fusion.

### 7.5 Synergie BlueMind (context_bias)
Si `<stem>.bluemind.json` existe (réunion associée à un événement, docs/40), extraire les
noms d'invités et les passer en `context_bias` (max 100) → meilleure orthographe des noms
propres. Purement additif ; absent = liste vide.

### 7.6 RGPD / localisation
Mistral est **européen** (argument fort dans le contexte BlueMind/entreprise). Le
mentionner dans la notice de confidentialité (§2) et la doc utilisateur. La clé API est
stockée **en clair** dans `config.json` — **même posture que `bluemind_token`** (assumée
par le projet) ; le documenter, ne pas sur-ingénier un coffre en v1.

## 8. Nouvelles clés de configuration (`core/config.py`, `_DEFAUTS`)

```python
"mistral_cle_api": "",                        # secret ; vide = interco invisible
"mistral_base_url": "https://api.mistral.ai", # surchargeable (tests/proxy) ; validée
"mistral_source_transcription": "auto",       # "auto" (local sinon Voxtral) | "voxtral" (forcer)
"mistral_modele_transcription": "voxtral-mini-latest",
"mistral_modele_cr": "mistral-small-latest",
"mistral_duree_max_min": 180,                 # garde-fou (minutes) contre envoi accidentel géant
"mistral_confidentialite_acceptee": False,    # posé à True après confirmation §2
```

`mistral_source_transcription` porte la décision 1 : `"auto"` = transcript local s'il
existe, repli Voxtral sinon (défaut) ; `"voxtral"` = toujours re-transcrire via Voxtral.

`set`/`get` valident déjà contre `_DEFAUTS` et la migration JSON est générique
(cf. `config.py` l.111). Rien d'autre à câbler côté persistance.

## 9. UI

### 9.1 Préférences — nouvelle section « Remote IA »
Ajouter une entrée `_SECTIONS` (`preferences_view.py` l.68) intitulée **« Remote IA »**,
**placée juste AVANT « Journalisation »** (donc avant-dernière). Elle regroupe les
**fournisseurs d'IA distante** ; le contenu vit dans un widget dédié `remote_ia_view.py`.

**Conçue extensible** : la section est une liste de **blocs par fournisseur**. En v1, **un
seul bloc : Mistral**. Ajouter un fournisseur plus tard (ex. OpenAI, Anthropic…) = ajouter
un bloc + ses clés `*_cle_api` dans `_DEFAUTS` (préfixe par fournisseur, comme `mistral_*`),
sans toucher la structure. Ne pas sur-concevoir un système de plugins en v1 — un simple
empilement de `QGroupBox` par fournisseur suffit.

**Bloc « Mistral »** (auto-save, comme le reste) :
- **Choix du fournisseur / activation** : titre du bloc + court texte « Génère des
  comptes-rendus via l'API Mistral (Voxtral + modèles texte, serveurs UE) ».
- Champ **clé API** (echo masqué / `QLineEdit.Password`), lié à `mistral_cle_api`, avec un
  **bouton « Obtenir une clé »** ouvrant l'assistant §9.4.
- Champ **base URL** (avancé, repliable), validé.
- **Combo modèle transcription** (`voxtral-mini-latest`) et **combo modèle CR**
  (`mistral-small/medium/large-latest`).
- **Source du transcript** (`mistral_source_transcription`) : « Réutiliser la transcription
  locale quand elle existe (recommandé) » vs « Toujours transcrire via Voxtral ». Aide : le
  local est instantané et quasi gratuit ; Voxtral n'est utile qu'en enregistrement-seul ou
  si le local est médiocre.
- **Bouton « Tester la connexion »** → `testeur_connexion_mistral.py` (miroir de
  `testeur_connexion_bluemind.py`) : ping léger (ex. `GET /v1/models`) en worker, message
  vert/rouge.
- Ligne d'aide : rappel confidentialité (serveurs UE). **Aucune mention de coût** (§11).

### 9.2 Historique — action « Générer le CR (Mistral) »
Dans `reunion_view.py`, à côté des actions existantes (`_copier` l.366, diarization,
`_supprimer_*`) : un bouton/action **par réunion**, **visible seulement si
`mistral_cle_api` non vide**. Au clic → confirmation §2 (si pas encore acceptée) → lance
le worker §9.3. Si `<stem>_CR.md` existe déjà : proposer « Régénérer » / « Ouvrir ».

### 9.3 Worker + progression (`generateur_cr_mistral.py`)
QThread (jamais le thread UI), `QProgressDialog` non bloquant avec les 4 étapes du §4,
annulable. Signaux Qt pour : progression, succès (chemin du `_CR.md`), erreur (message).
Reprendre le pattern de `gestionnaire_diarization.py` (protection thread, arrêt propre —
attention aux crashs QThread déjà corrigés, docs/26).

### 9.4 Mini-didacticiel « obtenir une clé API Mistral » (`assistant_mistral.py`)
**Calqué sur l'onboarding diarisation** (`ui/assistant_diarization.py`, docs/13) : un
assistant guidé qui accompagne un utilisateur non technique de « je n'ai rien » à « ma clé
est saisie et testée ».

- **Déclenchement** : bouton « Obtenir une clé » du bloc Mistral (§9.1) **et** ouverture
  automatique de l'assistant quand l'utilisateur active/ouvre le bloc Mistral **sans clé
  configurée** (comme la diarisation propose son assistant quand le modèle manque).
- **Étapes** (avec liens cliquables `QDesktopServices.openUrl`, boutons « J'ai fait cette
  étape ») :
  1. **Créer un compte Mistral** → lien `https://console.mistral.ai` (« La Plateforme »).
  2. **Ouvrir la page des clés** → lien direct `https://console.mistral.ai/api-keys`.
  3. **Générer une clé** (« Create new key »), **la copier** (rappel : elle n'est affichée
     qu'une fois).
  4. **Coller la clé** dans le champ de l'assistant → écrit dans `mistral_cle_api`.
  5. **Tester** (réutilise `testeur_connexion_mistral.py`) → coche verte / message d'erreur.
- **Informations à afficher** (sans être bloquant) : mention **serveurs UE / RGPD** et
  rappel **confidentialité** (audio/texte envoyés au cloud). **Ne PAS afficher d'ordre de
  grandeur de coût** dans le didacticiel. Mentionner l'existence d'un **tier gratuit** avec
  limites (cf. §7.3) sans promettre de chiffres.
- **Style** : réutiliser les composants/États de `assistant_diarization.py` (mêmes patterns
  Qt, mêmes helpers de thread, pas de `QObject`/`QTimer` sans parent — docs/26). Textes en
  français, ton pédagogique.
- **Extensible** : l'assistant est **propre à Mistral** ; un futur fournisseur aura le sien
  (`assistant_<fournisseur>.py`). Pas de généralisation prématurée en v1.

## 10. Découpage = REPLI seulement (`decoupage.py`) — pas le chemin normal

**Défaut : PAS de découpage.** Le spike a transcrit une piste de **37,6 min en un seul
appel** (88 s) → on envoie **la piste entière**. Plus simple, plus rapide, une seule requête
par piste, pas d'artefact de frontière. Le module `decoupage.py` n'est qu'un **filet de
sécurité**, à déclencher **seulement** si :
- une piste très longue est **refusée** pour cause de durée (HTTP 4xx explicite), **ou**
- l'appel **timeout** malgré les reprises (§7.3).

Dans ce cas seulement, découper l'**Opus par copie** (aucun ré-encodage, chunks compacts) :
```
ffmpeg -y -loglevel error -i src.opus \
   -f segment -segment_time 840 -reset_timestamps 1 -c copy seg_%03d.ogg
```
(`840 s = 14 min`.) `-reset_timestamps 1` remet chaque segment à t=0 → **réappliquer
l'offset** (`index × 840 s`) aux `start`/`end` avant fusion. Ces segments repartent alors,
eux aussi, en séquentiel.

> On ne connaît pas le plafond exact de l'endpoint (validé 37,6 min ; doc batch ~3 h,
> fichier ≤ 1 Go). D'où « entier par défaut, découpage déclenché sur échec » plutôt que
> « jamais de découpage ». Un seuil de sécurité (ex. découper au-delà de ~90 min sans même
> tenter) est acceptable si on veut éviter un premier appel voué à l'échec.

## 11. Observabilité — RÈGLE : aucune notion de coût dans l'app

> **Règle : l'application ne mentionne JAMAIS de coût, prix, tarif, montant (€, $) — nulle
> part.** Ni UI, ni didacticiel (§9.4), ni section Préférences (§9.1), ni logs, ni récap de
> fin de génération. Pas de module de coût, pas de conversion minutes/tokens en argent. Le
> sujet tarif est **hors périmètre** (sans intérêt pour le projet).

**Observabilité à la place** — **usage neutre** (utile au diagnostic, sans dimension
monétaire) :
- log (niveau INFO/DEBUG, cf. docs/31) : source du transcript (local/Voxtral), minutes
  d'audio transcrites par piste, tokens `usage` (in/out) renvoyés par l'API ;
- récap de fin de génération : p. ex. « CR généré · source : Voxtral · ~41 min audio » ou,
  en mode local, « CR généré depuis la transcription locale ».

## 12. Tests (`tests/test_mistral_*.py`)

**Sans réseau (obligatoire, dans `make test`)** — avec `respx` :
- `client.py` : header `Bearer`, base URL surchargée, mapping des erreurs (401/429/4xx/5xx/timeout).
- `transcription.py` : parsing `text`/`segments`/`usage` ; passage `language`/`context_bias`.
- `decoupage.py` : durée < limite → 1 unité (origine) ; durée > limite → N segments +
  offsets corrects. Tester la logique offset/nombre de segments sans dépendre de ffmpeg
  (mock `subprocess`), ou avec une fixture audio courte reconstruite localement (rien de
  lourd commité — cf. `.gitignore` `*.ogg`/`*.opus`).
- `fusion.py` : entrelacement Moi/Participants par timestamp, piste vide gérée.
- `cr.py` : construction du message à partir du prompt actif ; réponse mockée → markdown.
- `pipeline.py` : bout-en-bout mocké (2 pistes → `<stem>_CR.md` écrit, temporaires nettoyés).
- `config` : nouvelles clés présentes, défauts, invisibilité si clé vide.

**Intégration (gated, marqueur `integration`, hors `make test`)** :
- `MISTRAL_TEST_API_KEY` défini → vrai appel sur un petit WAV → transcription non vide + CR.
  (Miroir des tests d'intégration BlueMind `BM_TEST_*`.)

**Non-régression** : `make test` reste vert (le nombre attendu passe de la baseline
actuelle à baseline + nouveaux tests). Aucun test existant modifié.

## 13. Pièges connus / à surveiller

- **Ne pas** router Mistral via `MoteurTranscription`/`factory.py` (§1.1).
- **httpx multipart** : `data` **doit être un `dict`** (valeurs-listes = champs répétés) ;
  une liste de tuples casse l'encodage du corps (`TypeError … tuple found`). Cf. spike.
- **Pas de découpage par défaut** (§10) : envoyer la piste `.opus` **entière** (validé
  37,6 min en 1 appel). Le découpage n'est qu'un repli sur refus-durée/timeout. **Ne pas**
  redécouper « par précaution ».
- **Ne pas paralléliser sur tier gratuit** : throttling silencieux → plus lent + coupures.
  De toute façon 1 requête/piste (2 max) en séquentiel ; gestion 429/`Retry-After` par
  sécurité (§7.3).
- **Opus accepté directement** (§7.1) : envoyer l'Opus tel quel. **Ne jamais** ré-encoder en
  WAV par défaut (upload lourd → coupures) ; WAV = dernier recours si format refusé.
- **Thread UI** : tout appel réseau et tout ffmpeg (découpage/décodage) en worker de fond
  — sinon l'UI gèle sur une longue réunion.
- **Crash QThread à l'arrêt** : réutiliser les helpers `arreter_thread`/`proteger_thread`
  (docs/26) ; ne pas créer de `QTimer`/`QObject` sans parent (crash natif en tests — cf.
  mémoire refonte UI).
- **Nettoyage temporaires** en `finally`, y compris sur annulation utilisateur.
- **IDs de modèles** à reconfirmer sur les docs Mistral au moment du code (§5).
- **Envoi accidentel géant** : garde-fou `mistral_duree_max_min` + confirmation avant envoi.
  (Aucune notion de coût affichée — §11.)

## 14. Extensions futures (hors périmètre v1)

> **Réutiliser la transcription locale = tranché (décision 1), plus une extension.** C'est
> le **défaut** de la v1 : CR depuis le transcript local, repli Voxtral si absent. Voir §1,
> §4, §8 (`mistral_source_transcription`). Ce qui suit reste hors périmètre v1 :

- **Diarisation en présentiel** : quand la piste système est silencieuse (réunion physique),
  tout est sur le micro → activer `diarize` (Voxtral) ou la diarisation pyannote (docs/07)
  pour étiqueter les intervenants. Sinon le CR n'a pas de séparation de locuteurs fiable.
- **Génération auto en fin de réunion** (réglage), une fois la v1 manuelle validée.
- **Transcription batch/long-form** (Voxtral « Transcribe 2 », jusqu'à ~3 h via `/v1/files`)
  pour éviter le découpage manuel.
- **Concurrence sur tier payant** : réactiver un petit parallélisme (avec gestion 429) si le
  tier le permet — inutile/contre-productif sur le tier gratuit (§7.3).

## 15. Definition of Done

- [x] `core/mistral/` **pur Python** (aucun import Qt ni OS-specific).
- [x] Fonctionnalité **invisible** sans clé API ; confirmation confidentialité au 1ᵉʳ envoi
  (implémentée dans `reunion_view.py::_generer_cr_mistral`, mémorisée via
  `mistral_confidentialite_acceptee`).
- [x] **Section Préférences « Remote IA »** (avant Journalisation), extensible, bloc Mistral
  en v1 ; **assistant guidé** de création de clé (§9.4) accessible via le bouton
  « Obtenir une clé… ». *Écart mineur vs plan initial* : l'ouverture **automatique** de
  l'assistant quand le bloc est ouvert sans clé configurée n'a **pas** été implémentée (le
  bloc Mistral est toujours visible dans la section, contrairement au badge/bouton
  d'activation de la diarization qui a un déclencheur naturel) — nice-to-have futur, pas
  bloquant : le bouton reste directement visible à côté du champ clé.
- [x] **Défaut adaptatif** (décision 1) : CR depuis le transcript local quand il existe ;
  repli Voxtral si absent ; forçage Voxtral via `mistral_source_transcription="voxtral"`.
- [ ] Bouton « Générer le CR » produit un `<stem>_CR.md` correct sur une vraie réunion, avec
  clé réelle (**validation manuelle Sylvain restante**) — testé sur les deux branches
  (local et Voxtral) en unitaire (mocké, `test_mistral_pipeline.py`) ; reste le test avec
  clé API réelle.
- [x] Séparation Moi/Participants préservée dans le CR (via les 2 pistes, sans `diarize`).
- [x] **Aucune notion de coût/prix (€, $) nulle part dans l'app** — UI, didacticiel, logs
  (§11) : vérifié par relecture de tout le code produit, aucune occurrence.
- [x] `make test` **vert sans réseau** (existant + nouveaux tests) — 1032 passed, +75 tests
  Mistral, zéro régression (2 échecs pré-existants documentés dans `CLAUDE.md`, sans
  rapport). Tests d'intégration gated (`MISTRAL_TEST_API_KEY`) **non ajoutés** en v1 (§12
  les prévoyait ; jugés redondants avec le spike `spike/mistral-cr/` déjà validé en réel —
  à ajouter si Sylvain le souhaite).
- [x] `CLAUDE.md` : ligne ajoutée au tableau des docs + à l'état des phases.
- [x] Doc utilisateur : `docs/01-specifications-fonctionnelles.md` §1/§2 amendées (mention
  « 100 % local **par défaut** » + exception opt-in Mistral, docs/42).
