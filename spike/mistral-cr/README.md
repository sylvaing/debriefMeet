# Spike Mistral — transcription cloud + CR (faisabilité)

Exploration isolée qui valide, **sur de vraies pistes de réunion**, la chaîne retenue au
cadrage (cf. [`docs/42-mistral-api-cr.md`](../../docs/42-mistral-api-cr.md)) **avant**
toute implémentation dans l'app :

```
piste Moi + piste Participants  →  /v1/audio/transcriptions (Voxtral, à la minute)
                                →  fusion chronologique étiquetée (Moi / Participants)
                                →  /v1/chat/completions (modèle texte + prompt CR debriefMeet)
                                →  CR.md
```

C'est un **script autonome** (`spike_mistral_cr.py`, httpx + ffmpeg système), sans
dépendance au paquet `debrief_meet`, sans écriture dans l'app.

## Objectif : répondre à 5 questions de faisabilité

1. **Format** — l'endpoint transcription accepte-t-il notre `.opus` (Ogg Opus) **tel quel** ?
   Le script tente l'upload direct du fichier d'origine et, en cas de refus, **retombe
   automatiquement** sur un ré-encodage ffmpeg → WAV 16 kHz mono. Le verdict est écrit dans
   `rapport.json` (`upload_direct_ok`). → tranche le point ouvert §7.1 du plan.
2. **Longues réunions** — au-delà de ~15 min (limite de l'endpoint), le découpage
   automatique en segments ≤ `--limite-min` fonctionne-t-il et les timestamps restent-ils
   cohérents ?
3. **Séparation des locuteurs sans `diarize`** — transcrire les **deux pistes séparément**
   (Moi = micro, Participants = système) puis entrelacer par timestamp donne-t-il un
   transcript propre, sans payer la diarisation Mistral ?
4. **Qualité FR + noms propres** — la transcription est-elle bonne en français, et les noms
   passés en `context_bias` (`--noms`) sont-ils bien orthographiés ?
5. **Coût réel** — minutes audio facturées + tokens du CR, ordre de grandeur en $
   (`rapport.json`).

## Prérequis

- Python 3.11+ avec `httpx` (le `.venv` racine du projet convient).
- `ffmpeg` + `ffprobe` dans le PATH (`brew install ffmpeg`).
- Une clé API Mistral, **dans l'environnement uniquement** :

```bash
export MISTRAL_API_KEY=...        # jamais en dur dans le script, jamais commité
```

## Utilisation

```bash
# depuis la racine du dépôt, avec le venv du projet
../../.venv/bin/python spike/mistral-cr/spike_mistral_cr.py \
    --moi          /chemin/vers/2026-..._moi.opus \
    --participants /chemin/vers/2026-..._systeme.opus \
    --sujet        "Point produit hebdo" \
    --langue       fr \
    --noms         "Alice Martin,Bob Durand"
```

Options : `--modele-transcription` (défaut `voxtral-mini-latest`), `--modele-cr` (défaut
`mistral-small-latest` ; essayer `mistral-medium-latest`/`mistral-large-latest` pour
comparer la qualité de synthèse), `--limite-min` (défaut 14), `--sortie` (défaut
`spike/mistral-cr/sorties/`).

> **Les fichiers audio à fournir** = les 2 pistes conservées d'une réunion, présentes à
> côté du `.md` dans `~/Documents/debriefMeet/reunions/` : `<date>_moi.opus` et
> `<date>_systeme.opus`. Donne-les-moi (ou lance la commande) quand tu veux tester.

## Sorties (dossier `sorties/`, **gitignoré** — contenu confidentiel)

| Fichier | Contenu |
|---------|---------|
| `transcript_moi.md` | transcription brute de la piste Moi |
| `transcript_participants.md` | transcription brute de la piste Participants |
| `transcript_fusionne.md` | transcript entrelacé étiqueté `**Moi :**` / `**Participants :**` (= entrée du CR) |
| `CR.md` | compte-rendu généré |
| `rapport.json` | verdict format, minutes, tokens, coût estimé, durée du run |

## Confidentialité

Le spike envoie l'audio et la transcription aux serveurs Mistral (UE). Les pistes
(`*.opus`/`*.wav`) et le dossier `sorties/` sont **déjà exclus de git** (`.gitignore`).
Ne jamais committer de contenu de réunion réelle.

## Critères de succès (ce qui « valide » le spike)

- La chaîne tourne de bout en bout sur une vraie réunion et produit un `CR.md` lisible.
- `CR.md` respecte le format du prompt (titre, contexte, points discutés, actions) et **ne
  mélange pas** ce qu'a dit Moi vs les Participants de façon absurde.
- Le verdict `upload_direct_ok` est tranché (→ oriente §7.1 : garder le décodage WAV
  uniforme, ou tenter l'upload direct `.ogg`).
- Le coût estimé est cohérent avec l'hypothèse « minimum de token » (transcription à la
  minute + un appel texte compact).

Si tout est vert → on lance l'implémentation dans l'app selon `docs/42`.
