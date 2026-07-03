# Cadrage — Diarization (qui a parlé) en passe finale

> **Statut :** ✅ **implémentée et validée (macOS, 2026-06-26)** — décisions actées, POC moteur fait
> (pyannote retenu, cf. §6), passe finale codée, testée et validée en GUI (cf. §8). Reste seulement la
> **décision de distribution du modèle gated**, renvoyée au packaging (Phase 4, cf. §7). Dépend de :
> [`06-integration-aec.md`](06-integration-aec.md) (AEC, qui rend le micro diarizable) et de la
> **rétention audio**.

---

## 1. Objectif

Produire, dans le débrief, **qui a dit quoi** — pas seulement « Moi / Participants ».
Contexte d'usage : **réunions hybrides** (présents dans la pièce + distants).

---

## 2. Décisions actées (issues de la discussion)

| Sujet | Décision | Pourquoi |
|---|---|---|
| **Quand diarizer** | **Passe finale, en fin de réunion** (option B, *offline*) — **pas** de labels en direct | Le live n'a besoin que d'un aperçu ; le débrief se lit *après*. Clustering sur toute la conversation → labels stables, meilleure qualité, outils batch sans contrainte temps réel. |
| **Sur quelles pistes** | **Les deux** : micro **et** système, puis **fusion** des timelines | Hybride : présents sur le micro, distants sur le système. La séparation par source est un atout (pas de démêlage acoustique d'un flux unique). |
| **Identité « Moi »** | **Pas d'enrôlement de voix.** Si le micro ne contient **qu'une seule voix** → label **« Moi »** ; sinon **« Présent 1/2/3… »** | Enrôlement trop lourd à l'usage et le logiciel sert à d'autres personnes. Règle automatique, zéro friction, dégrade gracieusement. |
| **Couplage AEC** | La diarization du micro **dépend** d'un micro bien nettoyé (AEC) | Sans AEC, l'écho des distants créerait de faux présents. |
| **Moteur** | **pyannote** (community-1) ; sherpa-onnx en repli sans-GPU | POC §6 : plus rapide (MPS) + plus propre. |
| **Déclenchement** | **À la demande**, bouton dans l'Historique, en **arrière-plan** | Le débrief se lit après ; ne pas imposer le calcul à chaque réunion. |
| **Sortie** | **Fichier séparé** `…_locuteurs.md` (le `.md` live reste le brouillon) | Ne pas écraser l'aperçu live. |
| **Rétention audio** | **Conservée** (WAV des 2 pistes à côté du `.md`) + **suppression manuelle** | Permet de re-générer ; l'utilisateur garde la main (vie privée). |
| **Texte de la passe finale** | **Re-transcrire l'audio complet** (POC fait) | Transcript propre/cohérent, **sans coupures 30 s ni hallucinations de bord** ; coût modeste (~0,19× RT, GPU, CPU libre, ~2,5 Go). Ré-étiqueter les tranches live serait gratuit mais hériterait des coupures + hallucinations. |
| **Renommage locuteurs** | **Post-v1** | D'abord un bon étiquetage auto ; le renommage manuel est une couche UI à part. |

---

## 3. Architecture cible — deux couches

```
┌─ COUCHE LIVE (pendant la réunion) ─────────────────────────────────────────┐
│ captures → AEC (nettoie micro) → tranches 30 s → Whisper → APERÇU           │
│ (« Micro / Présents » vs « Distants », sans locuteurs individuels)          │
│                          │                                                  │
│                          └──► RÉTENTION : on écrit l'audio des 2 pistes      │
│                               (micro nettoyé + système) sur le disque        │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │  (à l'arrêt de la réunion)
┌─ COUCHE FINALE (post-réunion) ───▼──────────────────────────────────────────┐
│ diarize(micro nettoyé) → {1 voix ⇒ Moi | N voix ⇒ Présent 1/2…}             │
│ diarize(système)       → {Distant 1/2…}                                      │
│ fusion des deux timelines par horodatage                                     │
│ (+ option : re-transcription Whisper avec contexte complet)                  │
│ → DÉBRIEF FINAL : transcript unifié, locuteurs étiquetés                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Le live ne change pas pour la diarization** : les tranches restent un aperçu. Tout le
travail « qui parle » se fait en fin de réunion sur l'audio retenu.

---

## 4. Rétention audio (prérequis) — ✅ FAIT

Implémenté : `EnregistreurAudioReunion` ([`core/fichiers.py`](../src/debrief_meet/core/fichiers.py))
écrit **en streaming live** (faible mémoire) 2 pistes **16 kHz mono** à côté du `.md` :
`<stem>_moi` (micro **nettoyé** par l'AEC) et `<stem>_systeme`.
- **Format Opus 24 kbps via ffmpeg** (`<stem>_moi.opus`) → **~19 Mo/h/piste (÷6 vs WAV)**,
  qualité sans impact pour l'ASR/diarization. **Repli WAV** automatique si ffmpeg absent.
- Encodage streaming : PCM float32 → `ffmpeg` (un process/piste) → fichier qui grossit au fil
  de l'eau. Ogg/Opus robuste à la troncature (crash-safe).
- Câblé dans `OrchestrateurReunion` (écriture par tranche, finalisation à l'arrêt). Clé config
  **`retention_audio`** (défaut True). Pistes optionnelles. 6 tests ; suite **187 passed**.

> **Dépendance** : ffmpeg devient requis pour l'Opus (à bundler en Phase 4 packaging ;
> pyannote tire déjà les libs ffmpeg via torchcodec). La passe finale décode l'Opus →
> PCM (ffmpeg/torchcodec) — Whisper/pyannote n'ont pas besoin de WAV.

Reste : bouton de **suppression** dans l'Historique (avec le reste de l'UI Phase D).

---

## 5. La passe finale (post-réunion)

1. **Re-transcription Whisper** de l'audio complet (micro nettoyé + système), contexte
   global → segments propres (décidé : bien meilleur que recoller les tranches 30 s).
2. **Diarization (pyannote)** micro nettoyé → segments (début, fin, locuteur local) :
   - 1 cluster détecté ⇒ étiquette **« Moi »** ;
   - N clusters ⇒ **« Présent 1 … N »**.
3. **Diarization (pyannote)** système → segments (Distant 1 … M).
4. **Attribution** : chaque segment Whisper reçoit le locuteur au plus grand chevauchement
   (attention : l'attribution dépend des bornes des segments — cf. POC).
5. **Fusion** des deux pistes **par horodatage** → timeline unique (chevauchements
   salle↔distants gérés gratuitement, pistes séparées).
6. **Rendu** dans le `…_locuteurs.md` final : chaque tour de parole préfixé du locuteur.

---

## 6. Outillage — **moteur retenu : pyannote** (POC fait)

POC isolé dans [`spike/diarization/`](../spike/diarization/) : comparaison **pyannote 4.0
(community-1)** vs **sherpa-onnx** sur de vraies réunions MP3 (BlueMind).

| Critère | sherpa-onnx (CPU) | **pyannote (MPS)** |
|---|---|---|
| Vitesse, extrait 5 min | ~0,33× RT | **~0,18× RT** |
| Vitesse, réunion 38 min | 0,30× RT (11,5 min) | **0,16× RT (5,9 min)** |
| Locuteurs sur 38 min | **15** (dont ~5 fantômes à 1 prise) | **3, propre** |
| Empreinte | légère (ONNX) | lourde (PyTorch) — **mais torch déjà présent** |

**→ pyannote retenu** : sur Apple Silicon il exploite le **GPU (MPS)** → ~2× plus rapide que
sherpa (CPU-only), **et** sortie bien plus propre (sherpa sur-segmente, invente des
locuteurs). Modèle : `pyannote/speaker-diarization-community-1` (gated HF, token requis).

- **Repli sherpa-onnx : DIFFÉRÉ** (décision actée). On code **pyannote uniquement** pour
  l'instant ; le repli sera réévalué **à l'usage et après le packaging** (sans-GPU / gating).
  Pour garder la porte ouverte sans surcoût, l'engine passe par une **interface
  `MoteurDiarization`** (1 seule implémentation, `DiarizationPyannote`) — comme `MoteurAEC`.
- `diarize` (FoxNoseTech) écarté : trop jeune (v0.1, 1 dev).
- **Empreinte** à acter à l'intégration : pyannote tire PyTorch + lightning… (torch est déjà
  une dépendance transitive ; le surcoût net est modéré).

---

## 7. Points de vigilance

- **Qualité AEC → qualité diarization micro** (faux présents si écho résiduel). Couplage fort.
- **Comptage de locuteurs** imparfait : un utilisateur seul parfois vu comme « Présent 1 »,
  ou deux voix proches fusionnées. Dégrade sans gravité ; ajustable.
- **Chevauchements intra-salle** (plusieurs présents qui parlent ensemble) : difficiles,
  limite classique de la diarization mono-micro.
- **Coût/temps** : passe finale ≈ 0,5× temps réel (≈6-8 min pour 80 min), en arrière-plan.
- **⚠️ API pyannote 3.x→4.x cassée sur le chargement offline.** `Pipeline.from_pretrained()`
  n'a plus de paramètre `local_files_only` en 4.x (supprimé). Le chargement hors-ligne du
  cache local se force désormais via la constante `huggingface_hub.constants.HF_HUB_OFFLINE`
  (la variable d'environnement ne suffit pas : elle est figée à l'import du module). Fixé et
  détaillé dans [`docs/29`](29-fix-diarization-pyannote4.md). Épinglage resserré à
  `pyannote.audio>=4,<5` dans `pyproject.toml`.
- **⚠️ Distribution (modèle pyannote *gated*) — décision DIFFÉRÉE au packaging (Phase 4).**
  `pyannote/speaker-diarization-community-1` exige un **token HF + acceptation de licence par
  utilisateur** : OK en dev (token perso), **bloquant pour distribuer l'app**. À trancher au
  packaging : (a) **bundler les poids** si la licence l'autorise, ou (b) **repli sherpa-onnx**
  (modèles non-gated). L'interface `MoteurDiarization` rend ce swap indolore. En attendant :
  token utilisateur.

> **Pourquoi ne pas mélanger les 2 pistes en une (1 seul passage Whisper+diar) ?** Ça
> diviserait le temps par ~2, mais détruirait les atouts du deux-pistes : (1) les
> **chevauchements salle↔distant** (mélangés → l'une des voix est perdue ; séparé → les deux
> transcrites), (2) l'**étiquette de source fiable à 100%** (salle vs distant), (3) un
> clustering avec moins de locuteurs (plus propre). Le temps n'étant pas critique (job de
> fond), on **garde les pistes séparées**.

---

## 8. Découpage (après l'AEC, doc 06)

1. ✅ **POC moteur** (sherpa vs pyannote) → **pyannote retenu** (§6).
2. ✅ **POC transcription** (full vs tranches) → **re-transcription full retenue** (§2).
3. ✅ **Rétention audio** des 2 pistes (16k mono, streaming) + tests (§4).
4. ✅ **Passe finale** (le gros morceau) — codée et testée :
   a. ✅ `decoder_audio_16k` (opus/wav→array) + interface `MoteurDiarization` + `DiarizationPyannote` + tests.
   b. ✅ `core/diarization.py` : orchestration (re-transcription ×2 → diarize ×2 → étiquetage
      Moi/Présent/Distant → attribution → fusion → rendu `rendre_locuteurs_md`) + tests des fonctions pures + CLI.
   c. ✅ `_WorkerDiarization` (QThread, arrière-plan) + **bouton « Générer les locuteurs »** dans l'Historique.
   d. ✅ `pyannote.audio>=4` dans `pyproject.toml` + bouton **suppression audio** + toggle rétention en Préférences.

> **Tests :** `test_diarization.py` (fonctions pures + orchestration) + `test_historique_diarization.py`.
> Suite complète : **309 passed** (`pytest -m "not integration"`).
> **Reste :** validation d'intégration manuelle (vraie réunion retenue, token HF) + décision modèle gated au packaging (§7).
