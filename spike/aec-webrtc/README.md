# Spike AEC WebRTC — dossier de travail (isolé, hors app)

Spike décisionnel go/no-go sur l'**option D** (AEC logicielle WebRTC cross-platform)
pour annuler l'écho des haut-parleurs dans le micro sans casque.
Cadre complet : [`docs/05-spike-aec-webrtc.md`](../../docs/05-spike-aec-webrtc.md).

> ⚠️ **Aucune intégration dans l'app** tant que le verdict n'est pas GO (spike §8).
> Rien ici n'est ajouté à `pyproject.toml` ni au code de `debrief_meet`.

> **Verdict : ✅ option D RETENUE (Étapes 1 & 2 GO).** Moteur **LiveKit AEC3, NS désactivé,
> référence avec marge de lead ~40 ms** (`MARGE_LEAD_AEC_MS`). Écho sous le seuil en continu
> (−13 à −34 dB sur 4 min), dérive négligeable (13 ms), voix non abîmée (WER micro propre 0.108
> inchangé après AEC). Découverte clé : le filtre causal d'AEC3 exige que la référence **précède**
> l'écho — sans cette marge, on plafonnait à −5 dB. Détail : [`docs/05-spike-aec-webrtc.md`](../../docs/05-spike-aec-webrtc.md).

---

## Tâche 0 — binding Python : ✅ **GO** (AEC3, moteur maintenu)

Le verrou le plus probable (§4) est levé, et **mieux que prévu : on a l'AEC3**, via un
moteur porté par une société et qui s'installe sans compilation.

### Moteur retenu (unique) : SDK **LiveKit** (`livekit.rtc.AudioProcessingModule`, AEC3)

[`livekit`](https://github.com/livekit/python-sdks) expose l'**APM WebRTC de
production** (AEC3 + NS + AGC + HP filter), utilisable **en standalone** (sans serveur).
API : `process_stream` / `process_reverse_stream` / `set_stream_delay_ms`, trames int16
10 ms.

- **Maintenu par une société**, commits quotidiens.
- Wheel **`py3-none`** (binaire Rust/FFI, pas une extension CPython) → `pip install livekit`
  marche **directement sur Python 3.14 / Apple Silicon, sans build**.
- Coût AEC négligeable (~0,008× temps réel).
- Compromis : empreinte ~19 Mo + deps (`protobuf`, `aiofiles`).

### Alternatives évaluées puis écartées (rationale de la décision)

Comparées pendant le spike, **non retenues** (un seul moteur en prod = moins de
maintenance) :

| Moteur | Algo | Install Py 3.14 | Atténuation démo | Pourquoi écarté |
|---|---|---|---|---|
| **`livekit`** *(retenu)* | AEC3 (APM prod) | wheel, **sans build** | **−44 dB** | — |
| [pywebrtc-audio](https://github.com/strands-labs/pywebrtc-audio) | AEC3 | build sdist (cmake/ninja) | −17 dB | léger (796 Ko) mais **1 dev / 3★** |
| webrtc-audio-processing 0.1.3 | AEC1 | build patché (swig) | −6 dB | **mort depuis 2018**, pire qualité |

> **Plan B léger.** Si l'empreinte de LiveKit (~19 Mo) devenait un problème à
> l'embarquement de l'app, **pywebrtc-audio** est l'échappatoire AEC3 légère
> (wheels cp310→cp313 ; sur 3.14, build sdist via `cmake`/`ninja`). Le legacy AEC1
> n'a aucun intérêt à être ressuscité.

---

## Prérequis & build

```bash
./construire_livekit.sh    # installe le SDK LiveKit (AEC3), sans compilation
```

Fichiers :
- `construire_livekit.sh` — installe le SDK LiveKit (AEC3).
- `enregistrer.py` — **capture guidée** des 2 pistes (micro + système) → `moi.wav`, `participants.wav`, `phases.txt`. `--cycles N` pour la session longue de l'Étape 2.
- `traiter_offline.py` — pipeline offline (2 WAV → micro nettoyé + mesures), `--ns` (débruitage, off par défaut).
- `analyser_drift.py` — **Étape 2** : dérive d'horloge + suppression d'écho début→fin de session.
- `test_traiter_offline.py` — tests des fonctions pures (alignement, WER, similarité, dérive).

---

## Étape 1 — enregistrement (script guidé)

Objectif : 2 WAV **sans casque**, reproductibles et avec vérité terrain. Le script
`enregistrer.py` capte les deux pistes **en parallèle** (`CaptureMicroSounddevice` +
`CaptureAudioSCK`), guide le déroulé minuté à l'écran et produit `moi.wav`,
`participants.wav` et `phases.txt`.

**Avant de lancer (sans casque !) :**
1. Préparer un **podcast/extrait connu** prêt à jouer sur les haut-parleurs.
2. Avoir un **texte à lire** sous les yeux → le coller dans `texte_lu.txt` (vérité terrain WER).

```bash
# Lancer le podcast sur les HP, puis :
.venv/bin/python spike/aec-webrtc/enregistrer.py --sortie spike/aec-webrtc/captures
```

Déroulé piloté par le script : pré-roll → **CLAP** (ancre d'alignement) →
**« participants seuls »** (~12 s, silencieux) → **« moi parle »** (~15 s, lecture) →
post-roll. Les bornes sont écrites automatiquement dans `phases.txt`. Durées
ajustables (`--participants`, `--moi`, …). Le clap unique au début sert d'ancre.

## Lancer le traitement

```bash
# Validation de la chaîne sans enregistrement (synthétique) :
.venv/bin/python spike/aec-webrtc/traiter_offline.py --demo

# Sur les enregistrements (mesure signal seule, rapide ; LiveKit AEC3 par défaut) :
C=spike/aec-webrtc/captures
.venv/bin/python spike/aec-webrtc/traiter_offline.py \
    --micro $C/moi.wav --systeme $C/participants.wav --phases $C/phases.txt

# Avec transcription Whisper (critère métier — plus lent) :
.venv/bin/python spike/aec-webrtc/traiter_offline.py \
    --micro $C/moi.wav --systeme $C/participants.wav --phases $C/phases.txt \
    --texte-lu texte_lu.txt --transcrire --langue fr
```

Le rapport affiche : délai estimé + dérive, coût CPU, RMS écho brut/nettoyé vs
seuil `0.008`, et (si `--transcrire`) similarité Moi↔Participants + WER.

## Étape 2 — validation temps réel / dérive (banc YouTube)

Teste l'inconnue décisive du §7 : la **dérive d'horloge** micro↔système sur une
session longue fait-elle réapparaître l'écho en fin de parcours ?

**Protocole** : YouTube sur les HP (= far-end, équivalent visio), session ~4 min en
cycles alternés silencieux/lecture, **sans casque**.

```bash
# 1. Session longue alternée (~4 min ≈ 7 cycles). Lance YouTube AVANT, laisse tourner.
.venv/bin/python spike/aec-webrtc/enregistrer.py \
    --sortie spike/aec-webrtc/live --cycles 7

# 2. Analyse dérive + suppression d'écho début → fin
.venv/bin/python spike/aec-webrtc/analyser_drift.py \
    --micro spike/aec-webrtc/live/moi.wav --systeme spike/aec-webrtc/live/participants.wav \
    --phases spike/aec-webrtc/live/phases.txt
```

Le rapport donne le **taux de dérive (ms/min)** et le **RMS écho résiduel par phase
« participants seuls », du début à la fin**. **GO si l'écho reste sous le seuil sur
toutes les phases** (dérive absorbée par l'estimateur interne d'AEC3).

## Critères de décision (rappel §6)

GO **si les deux** : écho résiduel nettoyé **sous** `_SEUIL_RMS = 0.008` **ET**
similarité Moi↔Participants en forte chute **sans** dégrader le WER de la voix.
La préservation de la voix prime sur la suppression de l'écho.
