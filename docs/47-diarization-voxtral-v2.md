# 47 — Diarization Voxtral V2 en mode distant (piste à creuser)

> Statut : **PISTE, mesurée** — notée le 2026-08-05 à la demande de Sylvain,
> suite à la question « Voxtral est capable de faire de la diarization non ? ».
> **Spike de mesure le 2026-10-23 (§6)** : format de réponse, modèles servis et
> qualité sur 2 réunions réelles. Questions 1 et 2 du §4 tranchées. Rien n'est
> engagé dans l'app.

## 1. Le déclencheur

Au lancement de Voxtral (juillet 2025, intégré par docs/42) la diarization était
« à venir » : l'endpoint `v1/audio/transcriptions` renvoie du texte et des segments
horodatés, sans étiquette de locuteur. L'app n'en demande donc pas — la séparation
des voix vient de l'architecture à deux pistes (`moi.opus` = micro, `systeme.opus`
= audio système), entrelacées par `fusion.py` en « **Moi :** / **Participants :** ».

**Limite actuelle du mode distant** : tous les interlocuteurs côté visio sont fondus
dans « Participants ». La diarization multi-locuteurs n'existe qu'en mode local
(pyannote → `locuteurs.md`, prédicat `avec_diarization()`).

## 2. Ce qui a changé (annonces de février 2026, non vérifiées en API)

**Voxtral Transcribe 2** (annoncé le 2026-02-04) apporte, sur le modèle **batch**
« Voxtral Mini Transcribe V2 » (~0,003 $/min) :

- **diarization native** : identification et étiquetage automatique des locuteurs ;
- **jusqu'à 3 h d'audio par requête** — la saga des 74 min du 2026-08-05
  (429 de fenêtre tokens/minute, cf. §4) n'existerait peut-être pas sur ce modèle ;
- timestamps au **mot** (aujourd'hui : au segment) ;
- context biasing jusqu'à 100 termes — déjà utilisé par l'app (invités BlueMind,
  lexique docs/46).

⚠️ La variante **Realtime** (`voxtral-mini-transcribe-realtime-2602`, open weights
Apache 2.0) ne fait **pas** de diarization — seul le batch nous concerne.

Sources (consultées le 2026-08-05) :
- https://mistral.ai/news/voxtral-transcribe-2/
- https://docs.mistral.ai/studio-api/audio/speech_to_text
- https://www.marktechpost.com/2026/02/04/mistral-ai-launches-voxtral-transcribe-2-pairing-batch-diarization-and-open-realtime-asr-for-multilingual-production-workloads-at-scale/

## 3. Ce que ça pourrait apporter à debriefMeet

Diarizer **la seule piste `systeme.opus`** ferait passer le transcript distant de :

```
**Participants :** (tout le monde fondu)
```

à :

```
**Participant 1 :** / **Participant 2 :** / …
```

et, combiné aux noms des invités BlueMind déjà injectés dans le prompt du CR,
mistral-large aurait de bonnes chances d'**attribuer les propos nominativement** —
comblant la principale limite du mode distant face au mode local (pyannote), sans
aucune dépendance locale.

### 3.1 Réunion PHYSIQUE : c'est `moi.opus` qu'il faut diariser (2026-08-18)

L'affirmation « `moi.opus` n'a pas besoin de diarization, un seul locuteur par
construction » était **fausse** et vaut d'être corrigée ici, car elle inverse la
priorité. En réunion physique (tout le monde dans la même salle, aucune visio), il
n'y a **pas** de son système à capter : le micro enregistre la pièce, donc *tous* les
participants, et la piste système ne contient que quelques bips de notification —
mesuré chez une utilisatrice : 19 s sonores sur 98 min (cf. `silences.py`).

Le transcript est alors un **bloc unique étiqueté « Moi »** contenant la parole de
trois personnes. C'est exactement le cas où la séparation des locuteurs apporte le
plus, et aujourd'hui **rien ne le couvre en mode distant** (en mode local, pyannote
le ferait). Diariser la piste micro est donc au moins aussi utile que diariser la
piste système, et sans doute plus fréquent en pratique.

## 4. Questions à instruire avant tout chantier

1. **Résolution d'alias** : la config pointe `mistral_modele_transcription:
   voxtral-mini-latest` — cet alias résout-il déjà vers la V2, ou faut-il cibler
   explicitement un id V2 ? (Piège : un changement d'alias silencieux côté Mistral
   pourrait déjà avoir changé le comportement en prod.)
2. **Paramètre d'activation** : quel champ multipart active la diarization
   (`diarize` ? `timestamp_granularities` ? autre) et quelle forme prend la réponse
   (étiquette de locuteur par segment ? par mot ?).
3. **Impact code** : `fusion.py` (entrelacement Moi/Participants par timestamp),
   format du transcript étiqueté, et le prompt CR (attribution nominative).
   Décider si les étiquettes `Participant N` sont exposées telles quelles ou
   mappées via les invités BlueMind.
4. **Tier gratuit** : dispo et limites de la V2 en tier Experiment (le compte de
   Alix reste gratuit — décision du 2026-08-05). Vérifier au passage si la limite
   « 3 h par requête » change la donne des 429 de fenêtre tokens/minute
   (fixes du 2026-08-05 : découpage sur 429, backoff 20/40/60 s, machine à états
   `precedente_entiere` — cf. docs/42 et commits `aa4b28c`/`7747c71`/`4b64f0b`).
5. **Coût** : ~0,003 $/min annoncé — à confirmer, et à comparer au modèle actuel.
6. **Qualité** : WER et qualité de la diarization en français, sur de vraies
   réunions (le benchmark RTF/WER de `benchmark/` ne couvre pas la diarization
   cloud — voir si un spike `spike/` dédié est justifié, comme pour docs/42).

## 5. Non-objectifs (à ce stade)

- Remplacer pyannote en mode local — le mode local reste inchangé.
- La transcription live distante (Voxtral Realtime) — hors sujet ici.

## 6. Mesures du spike (2026-10-23)

Six appels réels à `v1/audio/transcriptions` (clé de Sylvain), hors app :
script jetable, réponses brutes gardées hors dépôt. Aucun extrait de transcription
n'est reproduit ici (confidentialité du dépôt).

### 6.1 Format — questions 1 et 2 du §4 tranchées

- **Q1 — alias** : `voxtral-mini-latest` (réglage actuel de l'app) **résout déjà vers
  `voxtral-mini-2602`**, le modèle batch de Transcribe 2, celui qui diarise (vu dans
  `v1/models`). Une génération plus récente est servie, `voxtral-mini-transcribe-3` et
  `voxtral-small-transcribe-3`, mais l'alias `latest` ne la désigne pas.
- **Q2 — activation** : le champ multipart **`diarize=true`**, sur l'endpoint et la
  requête déjà utilisés par l'app. Chaque segment de la réponse gagne un champ
  **`speaker_id`** :

  ```json
  {"type": "transcription_segment", "text": "…", "start": 0.7, "end": 2.9, "speaker_id": "speaker_1"}
  ```

  - L'étiquette est **par segment** (médiane ~2 s avec `timestamp_granularities=segment`),
    anonyme (`speaker_N`), et sa numérotation est propre à chaque requête.
  - **Aucun paramètre** documenté pour le nombre de locuteurs ni pour leurs noms.
  - **Compatible avec `context_bias`**, envoyé exactement comme le fait l'app (dict
    httpx, valeur-liste = champs répétés) : HTTP 200, étiquettes présentes.

### 6.2 Qualité sur deux cas réels

| Cas | Piste | Modèle | Temps (30 min d'audio) | Étiquettes |
|---|---|---|---|---|
| Réunion **physique** à 2, 27 min (piste système à 7 % du micro en taille) | `moi.opus` | `mini-2602` | 14,8 s | 2 voix (16,9 / 4,2 min de parole, 96 tours) + 1 fragment de 3 segments |
| idem | `moi.opus` | `small-transcribe-3` | 54,3 s | 2 voix (16,4 / 4,2 min, 94 tours) |
| **Visio** avec un partenaire, 30 min, 5 invités | `systeme.opus` | `mini-2602` | 15,6 s | 10 : une voix à 92 % de la parole, une 2ᵉ à 0,7 min, la voix robot du pont de visio, et **7 fragments** de 1 à 4 segments (interjections courtes) |
| idem | `systeme.opus` | `small-transcribe-3` | 27,4 s | 3 : la même voix dominante, la même 2ᵉ voix, le robot isolé — **aucun fragment** |

- **Réunion physique — net.** Les deux modèles sont d'accord sur **99,2 %** des
  secondes où tous deux ont un segment. Les tours alternent de façon cohérente
  (questions d'un côté, réponses de l'autre). C'est le cas du §3.1 : aujourd'hui l'app
  sort un bloc unique « Moi ».
- **Visio — à confirmer.** Les deux modèles voient la même structure : une voix
  dominante, une voix secondaire stable sur toute la réunion, et le robot à part.
  Deux lectures restent possibles. (a) Il n'y avait réellement qu'un intervenant
  distant principal : ses questions s'adressent à l'utilisateur, dont les réponses sont
  sur `moi.opus`. (b) La voix dominante en fusionne deux. **Vérité terrain à
  recueillir** auprès de Sylvain. `small-transcribe-3` est nettement plus propre sur
  ce cas (pas de fragmentation des interjections).
- **Cohérence malgré le découpage interne.** `mini-2602` découpe lui-même l'audio
  (`request_count: 34` dans `usage` pour 30 min), et pourtant les étiquettes restent
  stables d'un bout à l'autre : le raccord entre ses morceaux est fait côté Mistral.

### 6.3 Conséquences pour une éventuelle intégration

1. **Repli découpage de l'app** (429 → segments de 14 min, docs/42 §10) : la
   numérotation recommence à chaque requête, donc `speaker_1` d'un segment n'est pas
   `speaker_1` du suivant. Il faut soit **ne pas diariser** sur ce chemin, soit
   raccorder les étiquettes, ce qui est un problème en soi. ⚠️ **Ce chemin n'est pas
   l'exception** : sur le Mac de Sylvain, **47 des 66 transcriptions** abouties depuis
   le 2026-09-01 (71 %) sont passées par le découpage (log du poste, compté le
   2026-10-27). Le déclencheur est presque toujours un **429 sur la première piste**,
   qui la fait découper sans réessai, puis la seconde est découpée d'office. Avant toute
   intégration de la diarization, il faut donc comprendre pourquoi l'envoi entier prend
   si souvent un 429, alors que les 6 envois entiers du spike (jusqu'à 30 min) sont tous
   passés du premier coup.
2. **Noms** : rien n'identifie « Moi » parmi les voix d'une réunion physique, ni les
   invités en visio. Mapping à faire, soit par le CR (liste des invités BlueMind déjà
   dans le prompt, risque d'attribution inventée, docs/46), soit par l'UI de mapping
   du mode local (`locuteurs.md`), soit les deux.
3. **Choix du modèle** : `small-transcribe-3` est plus propre en visio mais 2 à 4 fois
   plus lent, et il facture en `audio_tokens`. Son `usage` est de la forme imbriquée
   (`prompt_tokens_details`, `service_tier`, docs/42 §10.5), que `_cumuler_usage` sait
   déjà cumuler. Changer de modèle de transcription est indépendant de la diarization
   et mérite sa propre mesure de WER.

### 6.4 Reste à instruire

- Vérité terrain sur la visio mesurée (§6.2).
- Une réunion physique à **3 personnes ou plus**.
- Q4 (tier gratuit d'Alix), Q5 (coût réel), Q6 (WER comparé des deux modèles).
