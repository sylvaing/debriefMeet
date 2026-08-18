# 47 — Diarization Voxtral V2 en mode distant (piste à creuser)

> Statut : **PISTE, non instruite** — notée le 2026-08-05 à la demande de Sylvain,
> suite à la question « Voxtral est capable de faire de la diarization non ? ».
> Aucune vérification API n'a été faite au-delà des annonces publiques ci-dessous.
> Rien n'est engagé : ce document fige ce qu'on sait pour pouvoir instruire plus tard.

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
