# Interco Mistral — transcription cloud + génération de compte-rendu (CR)

> **Statut : ✅ TERMINÉ (2026-07-21, Sonnet) — code + tests (1042 passed sans réseau) +
> VALIDATION MANUELLE avec clé API Mistral réelle OK (Sylvain). Reste (hors périmètre
> livraison) : fusion de la branche dans `main`.**
> Correctifs annexes livrés au passage : log d'indisponibilité de la capture système,
> exclusion + suppression des dérivés `_CR.md`/`.bluemind.json`, récupération de la
> transcription Voxtral dans le `.md` local, injection des invités d'événement au CR.
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
  ⚠️ **Règle inversée en édition lite (docs/44)** : là, Mistral n'est plus un
  complément mais **le seul** moyen de transcrire. La clé API y est donc
  **obligatoire** et doit être mise en avant (assistant proposé au premier lancement,
  WARNING au démarrage si la clé est vide, notice utilisateur), pas masquée. La case
  « Toujours transcrire via Voxtral » y est en revanche retirée : sans transcription
  locale, `mistral_source_transcription="auto"` est déjà équivalent à `"voxtral"`.
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
1bis. **Proposition d'association BlueMind** (ajouté 2026-08-04, cf. §4.1) — avant tout
   envoi, si la réunion n'est pas encore associée et qu'un événement correspond.
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

### 4.1 Proposition d'association BlueMind avant l'envoi (2026-08-04)

Le CR n'est **pas régénéré** : le clic sur « Générer le CR (Mistral) » est le dernier
moment où l'utilisateur peut encore enrichir le contexte. Or tout ce que l'association
BlueMind apporte est consommé par ce flux — sujet, date et participants injectés dans le
prompt (§7.5), noms d'invités en `context_bias` Voxtral. L'association étant une action
**séparée** (item « Associer à la réunion », icône de la colonne calendrier), rien ne
poussait à la faire avant : les CR partaient couramment « à froid ».

`ReunionView._proposer_association_avant_cr` s'exécute donc en tête de
`_generer_cr_mistral` :

1. no-op transparent si BlueMind n'est pas configuré (`store_bluemind is None`) ou si
   `bluemind.json` existe déjà — aucune attente, aucun dialogue ;
2. **resync forcée et attendue** (`ui/attente_sync_bluemind.attendre_sync`, `QProgressDialog`
   indéterminé + `QEventLoop`, garde de temps 15 s) : contrairement aux autres déclencheurs
   de sync (ouverture de fenêtre, timer, passage en mode Réunion) qui sont tous « au fil de
   l'eau », la détection ne doit pas manquer un événement créé depuis la dernière synchro.
   Sync en échec ou dépassement du délai → on enchaîne sur la réplique telle quelle, sans
   message d'erreur (docs/40 §1.1) ;
3. détection via `_evenements_correspondants_pour` (même code que la colonne calendrier et
   le menu ⋯, docs/40 §6.1) ; aucune correspondance → on continue directement ;
4. sinon `DialogAssociationBluemind(..., contexte_cr=True)` — variante à **trois sorties** :
   « Associer » (écrit le sidecar, applique éventuellement le titre), « Sans association »
   (`association_ignoree`, le CR part quand même) et « Annuler » (ni association ni CR).

Deux points qui se cassent facilement en modifiant ce flux :

- **Ordre association → confidentialité.** L'association change *ce qui part* chez Mistral,
  donc elle précède la confirmation d'envoi du premier usage. Un envoi finalement refusé
  laisse l'association en place — c'est un acquis utile, pas un effet de bord.
- **Chemin après renommage.** « Associer » avec application du titre **renomme le dossier**
  (docs/43 §6.1) : `lancer()` doit recevoir `dlg.chemin_md`, sinon le job travaillerait sur
  un dossier disparu. Un drapeau `_proposition_en_cours` bloque la réentrance, l'attente de
  sync et le dialogue laissant tourner l'event loop.

### 4.2 Transcription distante SEULE, sans CR (⌘T / Ctrl+T, 2026-09-03)

Deuxième point d'entrée du pipeline : `pipeline.transcrire_reunion()` exécute la
**même** étape Voxtral que le repli du CR (mêmes limites de durée, mêmes replis
réseau, même `context_bias`), puis **s'arrête après l'écriture du transcript**. Motif :
récupérer le texte d'une réunion sans dépenser un appel de rédaction, et sans devoir
générer un CR qu'on ne veut pas.

Jusqu'ici la transcription distante n'existait que **dans** le flux CR. L'action
`_transcrire` de l'Historique, elle, ne pouvait pas servir : elle est gatée sur
`mode_transcription.avec_transcription_locale()`, c'est-à-dire sur Whisper embarqué.

**Un seul gestionnaire pour les deux tâches — c'est le point d'architecture.**
`GestionnaireCRMistral` gagne `lancer_transcription()` et un discriminant `tache`
(`TACHE_CR` / `TACHE_TRANSCRIPTION`). Un second gestionnaire aurait été plus propre en
apparence, mais les deux tâches **réécrivent toutes les deux `transcription.md`** : il
les aurait laissées tourner en parallèle sur la même réunion, avec deux uploads et deux
écritures concurrentes. Partager `_job_en_cours` rend l'exclusion **structurelle**,
plutôt qu'une vérification à ne pas oublier à chaque point d'appel — la famille de bug
que ce dépôt collectionne (cf. `NB_BOUTONS_REUNION`, docs/43).

**Paire de signaux dédiée** (`transcription_terminee` / `transcription_echouee`) plutôt
qu'un 3ᵉ argument sur `termine` : les deux tâches n'annoncent pas le même résultat
(« CR généré » vs « Transcription terminée ») et n'ouvrent pas le même fichier, et les
connexions existantes restent intactes.

**`locuteurs.md` est supprimé** quand la transcription est remplacée. Ce n'est pas un
nettoyage cosmétique : `_lire_transcript_local` donne la **priorité** au débrief
locuteurs sur `transcription.md`, donc le garder ferait rédiger le prochain CR sur le
texte qu'on vient de remplacer, **sans que rien ne le signale**. L'UI l'annonce dans sa
confirmation de remplacement.

**UI et raccourci** (`ui/reunion_view.py`) :

- Item « Transcrire via Mistral (⌘T) » dans le menu ⋯, placé **avant** le CR (ordre du
  pipeline et ordre d'usage). Grisé avec sa raison, jamais masqué — convention du menu
  exhaustif : « Mistral non configuré », « Aucun audio à transcrire », « Une tâche est
  déjà en cours ».
- **Un seul `QKeySequence("Ctrl+T")` couvre les deux OS** : Qt traduit le `Ctrl`
  portable en ⌘ sur macOS, donc ⌘T sur Mac et Ctrl+T sur Windows/Linux, sans une ligne
  de code par plateforme. `NativeText` sert l'affichage de l'infobulle, comme le fait
  déjà `ui/dictee_view.py` pour les raccourcis globaux.
- Contexte **`WidgetShortcut`**, comme le raccourci Suppr voisin. L'app n'a qu'**une**
  fenêtre dont Préférences et Journal sont des *pages* : un contexte applicatif
  capterait le raccourci depuis ces pages aussi.
- **Sélection multiple refusée explicitement.** Un seul job Mistral tourne à la fois et
  il n'y a **pas de file** : deviner laquelle des lignes part en traitement serait pire
  que ne rien faire. 0 ligne → invite à sélectionner ; n > 1 → refus motivé. La ligne
  « en cours » d'enregistrement compte pour 0 (son chemin est la sentinelle `Path()`,
  docs/43) — `chemin_a_la_ligne` rend `None` pour elle, donc la sélection ressort vide.
- **Remplacer** une transcription existante demande confirmation ; une réunion « en
  attente » n'en demande aucune (le placeholder audio-seul n'est pas une transcription).
- **Consentement de confidentialité partagé** avec le CR (§2) : c'est le même audio vers
  les mêmes serveurs, donc la même clé `mistral_confidentialite_acceptee`.
- **L'association BlueMind n'est PAS proposée** ici, contrairement à §4.1 : le raccourci
  doit rester un geste court. Une association déjà faite continue d'alimenter le
  `context_bias` (§7.5). C'est un arbitrage assumé, à revoir si les transcriptions
  lancées au raccourci s'avèrent moins bonnes faute de biais.
- L'icône de la ligne montre `file-text` / « Transcription en cours… » et non le
  `notebook` du CR : du point de vue de l'utilisateur c'est la même opération, seul le
  calcul se fait ailleurs.

⚠️ **Défaut évité de justesse, à retenir.** `ArbitreEtatVisuel.suivre_gestionnaire` ne
câblait que `termine`/`echoue`. Avec la nouvelle paire, une transcription distante
aurait allumé l'icône de tray en orange et ne l'aurait **jamais éteinte** (clé jamais
retirée de `_jobs`), jusqu'à la fin de la session et **sans aucune erreur**. Les paires
de fin sont désormais déclarées dans `arbitre_etat_visuel.PAIRES_FIN` et toutes câblées
en boucle ; un test refuse tout signal de fin d'un vrai gestionnaire qui n'y figure pas.
**Ajouter une tâche à un gestionnaire, c'est ajouter une paire — et l'oublier ne casse
rien de visible.**

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

⚠️ **Découpage en jetons obligatoire (fix 2026-07-28)** : Voxtral
(`context_bias_input_method=comma_separated`) refuse tout item contenant une **virgule ou
une espace** (400, code 3051). Un nom complet « Sylvain Garcia » est donc invalide tel
quel. `transcription._construire_donnees` découpe chaque nom en jetons (« Sylvain »,
« Garcia »), dédoublonnés — le biais reste efficace (Voxtral favorise ces mots). Sans ce
découpage, associer la réunion à un événement **avant** de demander le CR faisait échouer
toute la transcription Voxtral.

**Date injectée dans le CR (2026-07-28)** : le prompt CR demande un titre
« CR — [Sujet] — [Date] », mais le modèle n'a pas la date de façon fiable. On la lui
passe donc **en clair** (`generer_cr(..., date=…)`), comme `sujet`/`participants` :
`pipeline._date_lisible` prend la date de l'événement BlueMind associé si présente
(== cartouche), sinon la date d'enregistrement (`date_heure_reunion`, nom du dossier).

**Ré-insertion du cartouche après réécriture Voxtral (2026-07-28)** : en repli Voxtral,
`_ecrire_transcript_local` réécrit le `.md` de zéro et efface donc le cartouche
`<!-- bluemind:invites v1 -->` qu'une association aurait inséré. `_reinserer_bloc_invites`
le ré-insère depuis le sidecar. Le contexte du CR, lui, vient **du sidecar** (pas du texte)
— cette ré-insertion sert la **cohérence** (comme les autres réunions associées) et la
**portabilité** du `.md` (contexte lisible hors sidecar).

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

**État « CR disponible » + action « Ouvrir le CR » (ajout 2026-07-27)** : dès que
`<stem>_CR.md` existe, la réunion porte le badge **« CR disponible » en vert**
(`HistoryState.CR_DISPONIBLE`, priorité la plus haute — le CR est le livrable final,
`capture_model.py`), et le menu ⋯ expose **« Ouvrir le CR »** (icône « ouvrir », comme
« Ouvrir la transcription ») qui ouvre le `_CR.md` dans l'éditeur système.

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

### 10.1 Le 5xx ne déclenchait aucun repli (terrain 2026-08-31, corrigé)

Un COMEX de **139 min** parti d'un bloc depuis le poste Linux a pris un **503** sur
`v1/audio/transcriptions`. Deux tentatives manuelles à 26 min d'écart, deux fois le même
503, **aucun repli tenté** — CR perdu, alors que la piste micro était parfaitement
exploitable (elle contenait toute la réunion, captée par un speakerphone de salle).

**Le trou était double**, et aucune des deux moitiés ne se voyait seule :

* `ClientMistral._gerer_reponse` retentait sur les erreurs **réseau** et sur **429**,
  mais tout `>= 400` non spécifiquement classé tombait directement en
  `ErreurServeurMistral`, sans une seule reprise ;
* `_transcrire_avec_replis` rattrapait `ErreurFormatMistral`, `ErreurReseauMistral` et
  `ErreurQuotaMistral` — **jamais `ErreurServeurMistral`**. L'exception traversait la
  cascade intacte et remontait au pipeline.

Le découpage existait pourtant, éprouvé, et il était le bon remède : `LIMITE_SEGMENT_S`
vaut 14 min, donc les 139 min seraient parties en 10 segments — l'ordre de grandeur de
**tout** ce qui passait sur ce poste (envois réussis : 3 s, 6 min, 12 min, 19 min,
26 min, 36 min). Que le 503 vienne d'un hoquet serveur ou de la taille de l'envoi,
découper répond aux deux.

**Correctif.** Reprise sur 5xx dans le client (`_TENTATIVES_5XX`, `Retry-After` honoré),
placée **avant** les autres classifications pour qu'une reprise retombant sur un 429 ou
un 4xx reçoive son traitement normal ; puis branche `except ErreurServeurMistral` dans
la cascade, qui découpe comme le cas réseau.

⚠️ **Le budget de reprises est volontairement plus court** que celui du réseau (2 contre
3). Quand le 5xx vient de la taille de l'envoi, chaque reprise re-téléverse la piste
entière pour rien — ici 23 Mo, ~70 s avant chaque 503. Deux tentatives absorbent le
hoquet ; au-delà, la main revient à la cascade, qui découpe. Augmenter ce budget
retarderait le seul repli qui marche.

⚠️ **`mistral_duree_max_min` (180) n'a pas protégé** : la réunion faisait 139 min, sous
le plafond. Ce garde-fou vise les réunions absurdement longues, pas le point de rupture
réel de l'endpoint, qui est manifestement plus bas. Le seuil de sécurité évoqué en fin
de §10 (« découper au-delà de ~90 min sans même tenter ») reste une option ouverte —
non retenue pour l'instant : le repli sur 5xx couvre le cas sans jamais dégrader la
qualité des réunions qui passent entières.

### 10.2 Compaction des silences avant envoi (`silences.py`, 2026-08-18)

Distinct du découpage : on ne coupe pas en morceaux, on **retire les silences** d'une
piste avant de l'envoyer, et on remet ensuite les horodatages dans la timeline
d'origine (`PlanCompaction.vers_original`) pour que la fusion Moi/Participants reste
juste.

**Déclencheur terrain.** En réunion **physique**, la piste système ne contient que des
bips de notification : mesuré chez une utilisatrice, **19 s sonores sur 98 min**, en
12 événements de 1 à 2 s. Ces 98 min partaient intégralement chez Voxtral — du quota
pour rien, et 98 min de quasi-silence offertes à l'hallucination (docs/22), dont le
texte inventé aurait été étiqueté « Participants » dans une réunion où personne
n'était à distance. Après compaction : **43 s / 64 Ko** au lieu de 98 min / 1,7 Mo.

**On ne jette jamais une piste.** Un critère de proportion (« moins de 1 % de temps
sonore ⇒ piste ignorée ») a été étudié puis **rejeté** : une intervention visio d'une
minute dans une réunion de 98 min ne pèse que 0,61 à 0,97 % du temps (duty cycle de
parole mesuré : 78 à 97 %), elle aurait donc été jetée **avec ses propos**. Une durée
absolue ne discrimine pas mieux (19 s de bips ≈ 20 s de parole). Perdre de la parole
réelle est bien pire que gaspiller du quota, d'où le choix de compacter au lieu de
trancher — et le critère de silence de `analyser_piste` (docs/27 : normaliser PUIS
porter) reste inchangé.

**Trois pièges, tous vérifiés en mesurant :**
1. **Sortie Opus, pas WAV** — garder 60 % d'une piste de 98 min ferait un WAV > 100 Mo,
   soit un envoi pire que l'original compressé.
2. **Deux passes ffmpeg obligatoires** (`aselect` → WAV, puis WAV → Opus). Sélectionner
   et encoder en Opus d'un seul coup produit un Ogg dont l'en-tête annonce **0,08 s
   pour 38 s d'audio** : un serveur qui s'y fie ne transcrirait que le début. Sans
   `asetpts`, à l'inverse, les silences reviennent (63 s au lieu de 8 s mesurés).
3. **Le ffmpeg EMBARQUÉ doit avoir les filtres** — et il ne les avait pas. Le build
   macOS est un `--disable-everything` avec activation sélective, arrêté à
   `--enable-filter=aresample,aformat,anull` (docs/16 §5.5) ; `aselect` et `asetpts` n'en
   faisaient pas partie. La compaction a donc **échoué à tous les coups dans l'app
   livrée** dès sa mise en service (exit 234, « envoi intégral » dans le log du
   2026-08-18 à 15:30), et **jamais en dev**, où c'est le ffmpeg Homebrew complet qui
   répond — les chiffres de cette section ont été mesurés avec lui. Corrigé côté build
   (docs/48 §8.3 : filtres ajoutés, exigés par la validation du binaire, et les 2 passes
   rejouées à chaque build) ; le binaire déjà installé n'a pas les filtres, il faut un
   nouveau `.app`. Windows (build BtbN complet) et Linux (ffmpeg système) n'étaient pas
   concernés. **Règle à retenir : toute nouvelle invocation de ffmpeg dans le code oblige
   à revisiter la liste des composants compilés** — le build ne connaît que les usages
   qui existaient le jour où il a été écrit.

La compaction est un **confort** : tout échec (ffmpeg absent, filtre invalide) retombe
sur l'envoi intégral plutôt que de faire perdre le CR. C'est ce qui a rendu le piège 3
indolore — et invisible : personne ne lit un WARNING quand le CR arrive quand même. Elle ne s'applique que si elle
retire au moins 20 % de la piste (`FRACTION_UTILE`) — une piste normalement parlée part
donc inchangée, sans ré-encodage.

### 10.3 Garde-fou de durée : la réunion, pas la somme des pistes (2026-08-18)

`mistral_duree_max_min` comparait la limite à la **somme** des durées des deux pistes.
Or elles sont enregistrées **simultanément** : les additionner double le compte et
divise par deux la limite réelle. Une réunion de 98 min a ainsi été refusée comme
« 197 min », un chiffre que l'utilisatrice ne pouvait rapprocher de rien. On compare
désormais au **maximum** des pistes, c'est-à-dire à la durée de la réunion.

Le message renvoyait de plus vers « les préférences » alors que le réglage **n'existait
pas dans l'interface** : il est désormais dans Préférences › IA en ligne (15 à 600 min),
et le message nomme cette section.

> À noter : c'est ce bug qui a **empêché** l'envoi des 98 min de quasi-silence décrit
> en §10.2 — il a rendu service par accident. Les deux correctifs vont donc ensemble.

### 10.4 Le repli existait mais ne pouvait pas s'exécuter — muxer `segment` absent du ffmpeg embarqué macOS (2026-09-02, corrigé)

Réunion de **1 h 52** (`moi.opus`, 18,8 Mo). Envoi entier → **503**, une reprise, 503 à
nouveau → la cascade fait exactement ce que §10.1 a câblé la semaine précédente :
`Erreur serveur persistante pour moi.opus — repli découpage`. Et le repli meurt
aussitôt :

```
CR Mistral échoué : Command '[…/vendor/ffmpeg, -y, -loglevel, error, -i, …/moi.opus,
  -f, segment, -segment_time, 840, -reset_timestamps, 1, -c, copy, …/seg_%03d.opus]'
  returned non-zero exit status 8.
```

**Cause : le muxer `segment` n'était pas compilé** dans le ffmpeg embarqué. Le build est
`--disable-everything` avec activation sélective (docs/16 §5.5), et `segment` n'a jamais
figuré dans `--enable-muxer`. Reproduit sur le binaire livré :

```
Unrecognized option 'segment_time'.     → exit 8
```

⚠️ **Le message ne ressemble en rien à « composant absent ».** Sans le muxer, ffmpeg ne
connaît pas ses **options privées**, donc il rejette `-segment_time` comme une option
inconnue — un exit 8 qu'on lirait volontiers comme une erreur d'invocation. C'est ce qui
rend ce défaut coûteux à diagnostiquer sans le rejouer sur le binaire réel.

**Pourquoi ça n'était jamais sorti.** Le découpage est un repli (§10), et sur macOS il
n'avait **jamais** tiré : la branche 5xx qui le déclenche ici venait d'être câblée
(§10.1, 2026-08-31). Les occurrences antérieures du repli étaient sur Windows, dont le
ffmpeg est un build **BtbN complet** — le muxer y est présent. Linux dépend du ffmpeg
**système**, complet lui aussi. **macOS était le seul touché**, et c'est le seul dont le
ffmpeg est compilé sur mesure.

**Correctif** (`packaging/build_ffmpeg.sh`) : `segment` ajouté à `--enable-muxer` ;
`valider_binaire` l'exige (avec `return 1` → reconstruction, comme pour les filtres,
ce qui rattrape un binaire d'avant cette date) ; et le build rejoue la **commande exacte
du repli**, parce que `-f segment` délègue à un muxer enfant déduit de l'extension
(`opus`) qui doit être présent aussi. Côté tests, `tests/test_build.py` interroge
désormais le **binaire réellement livré** sur les muxers et filtres utilisés par le
code, et exécute `decouper_piste` dessus — les deux régressions passées
(`aselect`/`asetpts` puis `segment`) étaient invisibles à `make test`.

Vérifié sur le fichier réel : 9 segments, le premier à **840,0 s** décodées.

⚠️ **Deux régressions de la même famille en trois semaines.** La liste `--enable-*` du
build minimal se périme à chaque nouvelle invocation de ffmpeg dans le code, et le
symptôme n'apparaît que dans l'app livrée. C'est maintenant couvert par des tests, mais
la règle de docs/16 §5.5 reste la première chose à rouvrir.

### 10.5 Le repli s'est exécuté, et c'est le cumul de `usage` qui a perdu la transcription (2026-09-07, corrigé)

Terrain, poste Windows (build `4d967e7`, mode distant). Réunion de **2 h**
(`2026-09-07_14-36-08`), transcription distante seule au raccourci (§4.2) — le premier
usage réel de cette action. Séquence, à la seconde :

```
16:24:14  Quota Mistral (429) pour moi.opus — repli découpage sans retry
16:24:59  429 Mistral — attente 20.0s (tentative 1/3)      ← retry d'un SEGMENT, normal
16:25:28  Transcription Mistral échouée : unsupported operand type(s) for +: 'int' and 'dict'
```

Le repli a fonctionné : les segments ont été découpés, envoyés, transcrits — **et
facturés**. Puis `_transcrire_decoupe` a additionné leurs compteurs d'usage :

```python
usage_total[cle] = usage_total.get(cle, 0) + (valeur or 0)   # ← 0 + {...}
```

**Cause : `usage` n'est pas un plat de nombres.** Mesuré le jour même sur l'API réelle
(`/v1/audio/transcriptions`, `voxtral-mini-latest`, 2 s d'audio) :

```json
"usage": {
  "prompt_audio_seconds": 2, "prompt_tokens": 4,
  "total_tokens": 380, "completion_tokens": 1,
  "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 375},
  "service_tier": "standard"
}
```

`prompt_tokens_details` est un **sous-dictionnaire**, `service_tier` une **chaîne** :
`0 + {...}` lève le `TypeError` vu par l'utilisatrice, et `0 + "standard"` l'aurait levé
juste après.

#### La forme de `usage` dépend de la DURÉE de l'audio envoyé — bascule à 30 s

C'est ce qui explique que le même commit `4d967e7` ait échoué chez Alix et réussi chez
Sylvain le même jour, à 13 min d'écart, puis **encore** à 17:14. Mesuré sur la même clé,
le même modèle et la requête exacte de `_construire_donnees`, en faisant seulement varier
la durée d'un sinus synthétique :

| durée envoyée | clés de `usage` | verdict |
|---|---|---|
| 2 / 5 / 10 / 20 / 25 / **29** s | + `prompt_tokens_details` (**dict**), `service_tier` (**str**) | **plante** |
| **30** / 31 / 35 / 40 / 60 s | + `request_count` (int), rien d'imbriqué | passe |

La bascule est **franche et reproductible à 30 s**. Le `request_count` de la seconde
forme dit ce qui se passe : au-delà de 30 s, Mistral **découpe lui-même** en interne et
renvoie un usage *agrégé*, donc aplati ; en dessous, c'est une inférence unique et l'usage
brut sort tel quel, avec ses sous-structures.

#### Donc le déclencheur, c'est le DERNIER segment du découpage

`decouper_piste` coupe à `LIMITE_SEGMENT_S = 840` s. Une piste de durée `L` produit un
dernier segment de `L mod 840` — et si ce reste est **< 30 s**, ce segment-là revient sous
la forme DICT et fait tomber tout le découpage, au tout dernier tour de boucle, après que
les 6 ou 8 autres ont été uploadés et facturés.

Les deux postes du 2026-09-07, calculés depuis les « Durées livrées » de leurs logs :

| poste | piste | durée | découpage | reste | résultat |
|---|---|---|---|---|---|
| Alix | `moi.opus` | 5061,98 s (84,4 min) | 6 × 840 s | **21,98 s** | ❌ `int + dict` |
| Alix | `systeme.opus` | 5060,18 s | 6 × 840 s | 20,18 s | (jamais atteint) |
| Sylvain | `systeme.opus` | ~5563 s | 6 × 840 s | ~523 s | ✅ |

**La fenêtre fait 30 s sur 840, soit ~3,6 % des pistes.** Ce n'est donc ni un déploiement
serveur, ni une différence de compte, ni un hasard réseau : c'est une **loterie sur la
durée de la réunion**, et Alix est tombée dedans. Le chronométrage le confirme —
7 segments à ~6 s chacun plus une attente de 20 s font bien les 74 s entre le début du
découpage (16:24:14) et le `TypeError` (16:25:28).

⚠️ **Une hypothèse fausse, écartée par les données.** Une première lecture avait conclu à
un déploiement Mistral entre 16:11 et 16:25 — cohérente avec les trois points connus à ce
moment-là (Sylvain OK à 16:11, Alix KO à 16:25, mesure DICT à 16:50), et **réfutée** par
le découpage réussi de Sylvain à 17:14. C'est le passage à une mesure *paramétrique*
(faire varier la durée) plutôt qu'à une mesure ponctuelle qui a sorti la vraie règle.

⚠️ **Ce champ n'est lu par personne.** `TranscriptionMistral.usage` n'a aucun
consommateur dans l'app (§11 interdit toute notion de coût) : une transcription de 2 h a
été perdue, après que tous les appels ont réussi, pour agréger une valeur que rien
n'affiche. Le correctif privilégie donc la **robustesse** sur l'exactitude —
`_cumuler_usage` ne somme que les nombres, descend récursivement dans les
sous-dictionnaires, et recopie tout autre type tel quel : un champ d'un type inattendu
ne peut plus faire échouer un découpage réussi.

⚠️ **Pourquoi la suite ne pouvait pas le voir.** Les 6 tests du repli découpage mockent
leurs payloads **sans clé `usage`** — `payload.get("usage") or {}` vaut `{}` et la boucle
de cumul ne tournait jamais. Le test de régression rejoue le relevé ci-dessus tel quel ;
sans le correctif il échoue avec le message **exact** du terrain (vérifié par régression
simulée). Même famille que les pièges du 2026-08-24 et du 2026-08-28 : un chemin de repli
que rien n'exerce vraiment reste vert jusqu'au jour où il tire.

⚠️ **Le log ne disait pas d'où venait l'exception.** `_WorkerCRMistral` n'émettait que
`str(exc)`, donc le diagnostic n'a livré qu'une ligne sans provenance ; localiser le
défaut a demandé de relire le code. Le worker journalise maintenant la **trace** pour
tout ce qui n'est pas une `ErreurMistral` (les échecs diagnostiqués, eux, sont des
messages destinés à l'utilisateur : une trace n'y ajouterait que du bruit).

**Non livré à Alix** : son poste tourne `4d967e7`, le correctif attend le prochain build
Windows. Contournement en attendant : relancer la transcription plus tard — le 429 vient
de la fenêtre de quota, et sans lui l'envoi entier passe sans jamais toucher ce code.

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

**Ajouts du 2026-09-03 (transcription distante seule, §4.2)** — +38 tests, **1677 passed** :
- `pipeline.transcrire_reunion` : `.md` réécrit avec la mention Voxtral et **aucun** appel
  de rédaction (`route_cr.call_count == 0`) ; `locuteurs.md` périmé supprimé ; limite de
  durée honorée ; renommage du dossier **pendant** l'upload (déclenché depuis le
  `side_effect` respx — posé avant l'appel, il testerait un cas plus facile, cf.
  docs/43 §16.6).
- Gestionnaire : `lancer_transcription` appelle le bon point d'entrée et **jamais** le CR ;
  chaque tâche émet **sa** paire de signaux ; `tache_en_cours()` revient à None **avec** le
  job ; exclusion mutuelle vérifiée **dans les deux sens** (CR refusé pendant une
  transcription et l'inverse).
- Arbitre : la seconde paire éteint bien le job, et un test parcourt les **vraies** classes
  de gestionnaires pour exiger que chacun de leurs signaux de fin figure dans `PAIRES_FIN`.
- Vue : le raccourci existe, est en `WidgetShortcut`, et **lance réellement** le job ;
  refus à 0 et à n > 1 ; ligne « en cours » ignorée ; confirmations de remplacement et de
  confidentialité ; item de menu grisé avec sa raison ; icône de ligne `file-text` vs
  `notebook`.
- `tests/test_build.py` : muxers/filtres exigés du binaire **livré** + `decouper_piste`
  exécuté dessus (§10.4).

⚠️ **Deux régressions ont été simulées pour vérifier que les tests les attrapent** —
amputer `PAIRES_FIN` fait échouer les 3 tests d'arbitre ; retirer `activated.connect` fait
échouer les 3 tests d'**effet** du raccourci tandis que les 2 tests de simple présence
restent verts. C'est précisément pourquoi les tests d'effet existent (cf. les items de menu
morts restés verts, CLAUDE.md 2026-08-24).

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
- **`locuteurs.md` prime sur `transcription.md`** dans `_lire_transcript_local`. Tout code
  qui **remplace** le transcript doit donc supprimer le débrief locuteurs, sinon le CR
  suivant est rédigé sur l'ancien texte, silencieusement (§4.2).
- **Une nouvelle tâche dans un gestionnaire = une nouvelle paire de signaux de fin**, à
  déclarer dans `arbitre_etat_visuel.PAIRES_FIN`. L'oublier n'échoue nulle part : le job
  s'allume et l'icône de tray reste orange jusqu'à la fin de la session (§4.2).
- **Toute nouvelle invocation de ffmpeg** oblige à rouvrir `--enable-*` dans
  `packaging/build_ffmpeg.sh` (docs/16 §5.5). Deux fois déjà, un composant manquant n'a
  cassé que l'**app livrée**, jamais le dev : `aselect`/`asetpts` (§10.2) puis le muxer
  `segment` (§10.4).
- **Les deux tâches Mistral partagent un gestionnaire** exprès (§4.2) : ne pas « clarifier »
  en le scindant, elles se disputent `transcription.md`.

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
- [x] Bouton « Générer le CR » produit un `<stem>_CR.md` correct sur une vraie réunion, avec
  clé réelle — **validation manuelle Sylvain OK (2026-07-21)**, en plus des tests unitaires
  mockés (`test_mistral_pipeline.py`).
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
