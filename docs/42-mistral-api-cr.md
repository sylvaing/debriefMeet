# Interco Mistral — transcription cloud + génération de compte-rendu (CR)

> **Statut : 🔬 spike de faisabilité VALIDÉ (2026-07-20) — chaîne complète exécutée sur une
> vraie réunion (voir « Résultats du spike » ci-dessous). Implémentation produit non commencée.**
> Ce document est conçu pour être donné **tel quel** à une session d'implémentation (Sonnet).
> Branche de travail : `claude/mistral-api-transcription-cr-f15d4a` (déjà créée, worktree dédié).
> Code du spike : `spike/mistral-cr/` (`spike_mistral_cr.py` + `README.md`).
> **Décisions de cadrage validées avec Sylvain (2026-07-20) :**
> 1. **Transcription d'abord** (2 étapes) — l'audio Opus passe par l'endpoint transcription
>    Voxtral (facturé à la minute), puis le texte part vers un modèle *texte* pour le CR.
>    Pas de tout-en-un audio→CR (plus cher en tokens audio, limité à ~20 min, perd la
>    séparation Moi/Participants).
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
| **Format `.opus` accepté directement ?** | **OUI** — upload direct du `.opus` court **et** des segments Ogg Opus. **Aucun transcodage WAV nécessaire** (renverse l'ancienne §7.1/§10). |
| **Longues réunions (> ~15 min) ?** | Découpage en segments Opus ≤ 14 min OK, recollage par offset correct (37,6 min → 3 segments → 683 segments de transcription). |
| **Séparation Moi/Participants sans `diarize` ?** | OK, mais valable surtout en **visio** (voir « présentiel vs visio »). |
| **Qualité FR + noms ?** | **Excellente** avec `mistral-small-latest` : CR structuré (titre, participants, contexte, points numérotés, **Actions par responsable**), noms bien orthographiés. |
| **Coût ?** | **~0,125 $ pour 41,3 min d'audio** — dont ~99 % transcription, **CR ≈ 0,001 $**. |

### Chiffres de coût réels (base de §11)
- Facturation transcription **à la minute d'audio** (~0,003 $/min) ; CR = 8902 tokens in +
  1255 out ≈ **0,001 $**. **Le CR (LLM) est quasi gratuit ; tout le coût = minutes d'audio.**
- Extrapolation **1 h** : **~0,18 $** en présentiel (1 piste utile) ; **~0,36 $** en visio
  (micro + système, 2 pistes pleines). Le coût suit les *minutes audio envoyées*, pas la
  durée de la réunion → sauter les pistes silencieuses (§7.4) divise le coût en présentiel.
- ⚠️ Tarif 0,003 $/min issu de la recherche, **à reconfirmer** sur mistral.ai/pricing.

### Format & découpage (tranche §7.1 + §10)
- L'endpoint **accepte l'Ogg Opus directement** → on **abandonne le décodage WAV
  systématique**. On envoie l'Opus tel quel (fichier court) ou des **segments Opus copiés**.
- Découpage **sans ré-encodage** (compact + rapide) :
  ```
  ffmpeg -y -i src.opus -f segment -segment_time 840 -reset_timestamps 1 -c copy seg_%03d.ogg
  ```
  → chunks **~2,4 Mo / 14 min** contre **~27 Mo / 14 min** en WAV 16 kHz. Offset externe =
  `index × 840 s` (les timestamps de segment sont remis à 0 par `-reset_timestamps 1`).
- Le WAV 16 kHz ne sert plus qu'en **repli** si un format était refusé (HTTP 400/415/422).

### Robustesse réseau (tranche §7.3)
- Premier essai en **WAV 27 Mo** → `Broken pipe` (upload lent + mise en veille probable du
  Mac). Corrigé par chunks Opus compacts **+ reprises sur `httpx.TransportError`**
  (broken pipe, `ReadError`, `ConnectError`) avec backoff. **Validé en réel** : une coupure
  a été récupérée automatiquement (`reprise 1/2`).
- Conseiller **`caffeinate -i`** pendant un long run (éviter la veille).

### Concurrence / rate-limit — NE PAS paralléliser sur le tier gratuit
- 4 requêtes de transcription **en parallèle** = **488 s** (vs **177 s** en séquentiel) +
  une connexion lâchée. Le tier gratuit **throttle la concurrence** (mise en file
  silencieuse, sans 429 franc) → paralléliser est **contre-productif**.
- **Défaut produit = séquentiel.** La concurrence n'a de sens que sur un tier payant à
  limite élevée. Le produit **doit** gérer le **429** (respect de `Retry-After` + backoff)
  et **plafonner la concurrence** — indispensable quel que soit le tier.

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
~177 s (séquentiel) pour transcrire 41 min d'audio + générer le CR. Le temps serveur par
appel Voxtral est le plancher (~35-45 s pour 14 min, RTF ~0,05). Sur le tier gratuit, pas
de gain à attendre du parallélisme (voir ci-dessus).

---

## 1. Contexte et objectif

Aujourd'hui debriefMeet **ne génère aucun CR** : il transcrit en local (mlx-whisper /
faster-whisper) et, à la copie, préfixe un **prompt** (`core/prompts.py`,
`CR_SIMPLE_CONTENU`) à la transcription pour que l'utilisateur le colle dans un LLM
externe. Chaque réunion conserve par ailleurs **deux pistes audio Opus** retenues
(`<stem>_moi.opus`, `<stem>_systeme.opus`, mono 16 kHz, 24 kbps — cf. `core/fichiers.py`).

Objectif : ajouter un chemin **cloud Mistral** qui, à la demande, transforme une réunion
enregistrée en **compte-rendu Markdown fini**, en **deux étapes** :

1. **Transcription** des pistes Opus via l'endpoint transcription Voxtral de Mistral
   (facturé à la minute, pas au token → le plus économique pour la partie audio) ;
2. **Rédaction du CR** en envoyant la transcription fusionnée + le **prompt CR actif**
   (`prompts.contenu_actif`) à un modèle *texte* Mistral.

Résultat écrit dans un fichier `<stem>_CR.md` à côté de la réunion.

> **Note sur « minimum de token ».** Un fichier Opus compact ne réduit pas les tokens :
> l'audio est facturé à la **durée**, pas au poids du fichier. Le coût minimal pour la
> partie audio = l'**endpoint transcription** (facturation à la minute, ~0,003 $/min),
> pas le chat multimodal (qui facture des *tokens audio*, plus cher). D'où l'architecture
> en deux étapes retenue.

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
- **Coût maîtrisé.** Chaque génération logge minutes audio transcrites, tokens CR in/out
  et coût estimé (cf. §11). Un garde-fou de durée max (réglable) évite les envois géants
  accidentels.

## 3. Architecture

```
core/mistral/                 ← pur Python : aucun import OS-specific ni Qt (règle d'or)
├── __init__.py
├── client.py                 # ClientMistral : httpx sync, auth Bearer, erreurs typées, timeouts, reprises TransportError + 429/Retry-After
├── transcription.py          # transcrire_fichier(chemin, langue, context_bias) → TranscriptionMistral (Opus direct ; repli WAV si format refusé)
├── cr.py                     # generer_cr(transcription, prompt, modele) → markdown (source-agnostique)
├── decoupage.py              # découpe Opus > limite en segments ≤ 14 min par COPIE ffmpeg (pas de ré-encodage)
├── fusion.py                 # entrelace les segments Moi + Participants par timestamp → transcript étiqueté
├── pipeline.py               # orchestration bout-en-bout (2 pistes → CR → <stem>_CR.md)
└── couts.py                  # estimation coût (minutes audio, tokens) pour le log

ui/
├── preferences_view.py       # + section « Mistral » (clé API, modèles, test connexion) — §9.1
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

1. **Pré-conditions.** Clé API configurée (sinon bouton absent). Retrouver les 2 pistes de
   la réunion via `core.fichiers.chemins_audio_reunion(stem)` → `_moi.opus`/`_systeme.opus`
   (repli `.wav` s'il n'y a pas d'Opus). Si aucune piste retenue → message « pas d'audio
   conservé pour cette réunion » (cas `retention_audio` off).
2. **Confirmation confidentialité** (§2) au premier envoi.
3. **Worker de fond démarré** (`generateur_cr_mistral.py`, QThread) avec `QProgressDialog`
   (étapes : découpage → transcription Moi → transcription Participants → rédaction CR).
4. **Découpage** (`decoupage.py`) : pour chaque piste, si durée > ~14 min, découper en
   segments (§10). Sinon un seul segment.
5. **Transcription** (`transcription.py`) : chaque segment → `client.audio.transcriptions`
   (`voxtral-mini-latest`), `language` = config `langue`, `context_bias` = noms d'invités
   BlueMind si le sidecar `<stem>.bluemind.json` existe (§7.5 — synergie docs/40),
   `timestamp_granularities=["segment"]`. On récupère `text` + `segments` (avec offset de
   temps réappliqué par segment découpé).
   → **En visio, on n'active PAS `diarize`** : la séparation locuteurs vient déjà des deux
   pistes (Moi = micro, Participants = système). **En présentiel** (piste système
   silencieuse, cf. spike), tout est sur le micro → activer `diarize` ou la diarisation
   pyannote si on veut des étiquettes de locuteur (§14). Détecter/sauter les pistes vides (§7.4).
6. **Fusion** (`fusion.py`) : entrelacer les segments des deux pistes par timestamp en un
   transcript étiqueté `**Moi :**` / `**Participants :**` (réutiliser la logique de
   `core/fichiers.py::_entrelaces`, l.455 — factoriser si pertinent).
7. **Rédaction CR** (`cr.py`) : `client.chat.completions` avec un modèle **texte**
   (`mistral_modele_cr`), message construit à partir de `prompts.contenu_actif(...)` +
   transcript fusionné. `cr.py` prend **du texte en entrée** (source-agnostique) → réutilisable
   plus tard pour le transcript local (extension §14).
8. **Écriture** : `<stem>_CR.md` à côté du `.md` de la réunion. Rafraîchir la liste
   Historique, proposer « Ouvrir » / « Copier ». Logger le coût (§11).
9. **Erreurs** : toute exception `client.py` → message clair au clic (clé invalide, quota,
   réseau, format refusé, durée dépassée), rien n'est écrit sur disque à moitié.

## 5. Détails API Mistral (vérifiés 2026-07-20)

> ⚠️ Les **IDs de modèles** et **tarifs** évoluent. Sonnet doit **reconfirmer** les IDs
> exacts sur https://docs.mistral.ai au moment de l'implémentation (les `*-latest`
> ci-dessous sont stables mais un modèle daté peut être préféré).

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
- **Limite de durée par requête** : ~15 min → d'où le découpage §10 (confirmé : la piste de
  37,6 min a dû être découpée).
- **Tarif** : facturé à la **minute d'audio** (~0,003 $/min), **pas au token** (confirmé :
  ~0,125 $ pour 41,3 min).

### 5.2 Endpoint chat texte (étape 2 — rédaction du CR)
- **Route** : `POST /v1/chat/completions` — SDK : `client.chat.complete(...)`.
- **Modèle** (config `mistral_modele_cr`, défaut proposé `mistral-small-latest`) :
  `mistral-small-latest` (économique) ; exposer aussi `mistral-medium-latest` /
  `mistral-large-latest` (meilleure qualité de synthèse) dans le combo Préférences.
  **Ne pas** utiliser un modèle Voxtral ici : c'est du texte pur.
- **Messages** : soit `system` = prompt CR + `user` = transcript, soit `user` unique
  reprenant `prompts.prefixer(transcript, contenu)`. Tester les deux ; garder le plus propre.
- **Tarif** (ordre de grandeur mistral-small) : ~0,10 $/M tokens in, ~0,30 $/M out.

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
| Worker de fond + progress | `ui/gestionnaire_diarization.py`, `ui/chargeur_modele.py` (QThread + QProgressDialog) |
| Persistance réglages | `core/config.py` (`_DEFAUTS` + get/set validés) |
| Mock HTTP en test | `respx` (déjà en dépendance `dev`) |

## 7. Points techniques à trancher pendant l'implémentation

### 7.1 Format d'upload — Opus direct (tranché par le spike)
**L'Ogg Opus est accepté directement par l'endpoint** (upload direct du fichier court ET
des segments Opus copiés — cf. Résultats du spike). **On envoie donc l'Opus tel quel**,
sans transcodage :
- fichier ≤ limite → upload direct de la piste `.opus` (mime `audio/ogg`) ;
- fichier > limite → segments Opus par **copie** (§10), pas de ré-encodage.

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
- **Reprises sur `httpx.TransportError`** (broken pipe, `ReadError`, `ConnectError`) : ~3
  essais, backoff. **Validé en réel** (une coupure récupérée automatiquement). Chunks Opus
  compacts (§10) réduisent fortement le risque de coupure à l'upload.
- **HTTP 429 (rate-limit)** : à gérer explicitement — respecter l'en-tête `Retry-After`,
  backoff exponentiel. Le tier gratuit **throttle silencieusement la concurrence** (spike :
  4 requêtes parallèles = 488 s vs 177 s séquentiel). → **transcrire en séquentiel par
  défaut** et **plafonner la concurrence** ; ne paralléliser que sur un tier payant.
- **Pas de retry** sur les 4xx de format (400/415/422) → déclenche le repli WAV (§7.1) ; ni
  sur 401/403 (clé invalide) → erreur claire remontée à l'utilisateur.

### 7.4 Piste vide / silencieuse — CAS RÉEL confirmé
Confirmé par le spike : la piste système était à **−91 dB (silence numérique total)** →
Voxtral a renvoyé **0 caractère**. Détecter en amont (durée nulle, RMS ≈ silence, ou `text`
vide) et **ne pas envoyer** / étiqueter la piste comme absente — **économise la moitié du
coût en présentiel** et évite d'ajouter du vide au CR. Ne pas planter la fusion.

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
"mistral_modele_transcription": "voxtral-mini-latest",
"mistral_modele_cr": "mistral-small-latest",
"mistral_duree_max_min": 180,                 # garde-fou (minutes) contre envoi accidentel géant
"mistral_confidentialite_acceptee": False,    # posé à True après confirmation §2
```

`set`/`get` valident déjà contre `_DEFAUTS` et la migration JSON est générique
(cf. `config.py` l.111). Rien d'autre à câbler côté persistance.

## 9. UI

### 9.1 Préférences — nouvelle section « Mistral »
Ajouter une 9ᵉ entrée à `_SECTIONS` (`preferences_view.py` l.68). Contenu (auto-save,
comme le reste) :
- Champ **clé API** (echo masqué / `QLineEdit.Password`), lié à `mistral_cle_api`.
- Champ **base URL** (avancé, repliable), validé.
- **Combo modèle transcription** (`voxtral-mini-latest`) et **combo modèle CR**
  (`mistral-small/medium/large-latest`).
- **Bouton « Tester la connexion »** → `testeur_connexion_mistral.py` (miroir de
  `testeur_connexion_bluemind.py`) : ping léger (ex. `GET /v1/models`) en worker, message
  vert/rouge.
- Ligne d'aide : rappel confidentialité + ordre de grandeur du coût.

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

## 10. Découpage des longues réunions (`decoupage.py`) — méthode validée au spike

- Ne découper **que si** la durée dépasse la limite (~15 min). Sinon 1 seule unité = la
  piste d'origine envoyée telle quelle.
- Découper l'**Opus par copie** (aucun ré-encodage, chunks compacts ~2,4 Mo/14 min) :
  ```
  ffmpeg -y -loglevel error -i src.opus \
     -f segment -segment_time 840 -reset_timestamps 1 -c copy seg_%03d.ogg
  ```
  (`840 s = 14 min`, marge sous les ~15 min). `-reset_timestamps 1` remet chaque segment à
  t=0 → l'offset externe suffit.
- Après transcription, **réappliquer l'offset temporel** (`index × 840 s`) aux `start`/`end`
  des `segments` avant la fusion, pour garder l'ordre chronologique.
- Repli **WAV 16 kHz** uniquement si un format était refusé (§7.1) — pas le chemin normal.
- (Optionnel, non requis en v1) découper sur un creux d'énergie proche de la frontière pour
  éviter de couper un mot ; un découpage à durée fixe est acceptable (validé au spike).

## 11. Coût & observabilité (`couts.py`, cf. docs/31)

**Données réelles du spike** : 41,3 min d'audio → **~0,125 $** (transcription ~0,124 $ à
~0,003 $/min ; CR 8902+1255 tokens ≈ **0,001 $**). **Le coût est piloté par les minutes
d'audio ; le CR (LLM) est négligeable.**

Estimation pour **1 h de réunion** :

| Cas | Minutes audio | Transcription | CR | **Total** |
|-----|---------------|---------------|-----|-----------|
| Présentiel (1 piste utile, l'autre silencieuse → sautée §7.4) | ~60 | ~0,18 $ | ~0,002 $ | **~0,18 $** (~0,17 €) |
| Visio (micro + système, 2 pistes pleines) | ~120 | ~0,36 $ | ~0,002 $ | **~0,36 $** (~0,33 €) |

⚠️ Tarif 0,003 $/min **à reconfirmer** sur mistral.ai/pricing avant d'annoncer un chiffre à
l'utilisateur.

À chaque génération, logger (niveau INFO) : minutes d'audio transcrites (par piste), tokens
CR `usage` (in/out), **coût estimé** (constantes de tarif documentées, révisées à la main —
pas d'appel de pricing). Récap discret en fin de génération
(« CR généré · ~41 min audio · ~0,12 $ »).

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
- **Ne pas paralléliser sur tier gratuit** : throttling silencieux → plus lent + coupures.
  Séquentiel par défaut, gestion 429/`Retry-After` obligatoire (§7.3).
- **Opus accepté directement** (§7.1) : envoyer l'Opus tel quel / segments copiés ; le WAV
  n'est qu'un repli. **Ne pas** ré-encoder en WAV 27 Mo par défaut (upload lourd → coupures).
- **Thread UI** : tout appel réseau et tout ffmpeg (découpage/décodage) en worker de fond
  — sinon l'UI gèle sur une longue réunion.
- **Crash QThread à l'arrêt** : réutiliser les helpers `arreter_thread`/`proteger_thread`
  (docs/26) ; ne pas créer de `QTimer`/`QObject` sans parent (crash natif en tests — cf.
  mémoire refonte UI).
- **Nettoyage temporaires** en `finally`, y compris sur annulation utilisateur.
- **IDs de modèles / tarifs** à reconfirmer sur les docs Mistral au moment du code (§5).
- **Coût accidentel** : garde-fou `mistral_duree_max_min` + confirmation avant envoi.

## 14. Extensions / arbitrages à reconsidérer (éclairés par le spike)

- **⭐ Réutiliser la transcription locale pour le CR (fortement recommandé).** Le spike
  montre que la transcription cloud est **la** partie lente (~3 min) et coûteuse (~99 % du
  coût). Or l'app a déjà un transcript local (fait en direct). Comme `cr.py` est
  source-agnostique, un mode « CR depuis le transcript local » donnerait le CR en **~15 s
  pour ~0,001 $**, sans upload ni rate-limit. → envisager d'en faire le **défaut**, la
  transcription Voxtral devenant l'option (enregistrement-seul, ou qualité Voxtral voulue).
  (Décision produit à valider avec Sylvain.)
- **Diarisation en présentiel** : quand la piste système est silencieuse (réunion physique),
  tout est sur le micro → activer `diarize` (Voxtral) ou la diarisation pyannote (docs/07)
  pour étiqueter les intervenants. Sinon le CR n'a pas de séparation de locuteurs fiable.
- **Génération auto en fin de réunion** (réglage), une fois la v1 manuelle validée.
- **Transcription batch/long-form** (Voxtral « Transcribe 2 », jusqu'à ~3 h via `/v1/files`)
  pour éviter le découpage manuel.
- **Concurrence sur tier payant** : réactiver un petit parallélisme (avec gestion 429) si le
  tier le permet — inutile/contre-productif sur le tier gratuit (§7.3).

## 15. Definition of Done

- `core/mistral/` **pur Python** (aucun import Qt ni OS-specific).
- Fonctionnalité **invisible** sans clé API ; confirmation confidentialité au 1ᵉʳ envoi.
- Bouton « Générer le CR » produit un `<stem>_CR.md` correct sur une vraie réunion, avec
  clé réelle (validation manuelle Sylvain).
- Séparation Moi/Participants préservée dans le CR (via les 2 pistes, sans `diarize`).
- Coût loggé à chaque génération.
- `make test` **vert sans réseau** (existant + nouveaux tests) ; intégration gated verte
  avec `MISTRAL_TEST_API_KEY`.
- Doc utilisateur mise à jour (mention transcription **cloud** UE + confidentialité) et
  `CLAUDE.md` : ajouter une ligne au tableau des docs + à l'état des phases.
