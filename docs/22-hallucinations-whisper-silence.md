# 22 — Hallucinations Whisper sur tranches quasi silencieuses

> **Statut :** observé une fois en usage réel (2026-07-01, réunion `2026-07-01_16-14`),
> **à surveiller**. Pas de correctif appliqué, pas encore de conclusion "ça arrive
> souvent" (un seul cas constaté pour l'instant). Revenir sur ce doc si le problème
> se reproduit en usage pratique.

## 1. Symptôme observé

Dans le `.md` généré pour la réunion `2026-07-01_16-14` :

```
**Participants :** CO CO CO CO CO CO CO CO CO CO CO CO CO CO CO CO ... (répété ~150 fois)
```

et plus loin :

```
**Moi :** 3 3 3 3 감사합니다.
```

Le deuxième cas (« 감사합니다 » = « merci » en coréen) est une hallucination bien connue
de Whisper : le modèle a été entraîné sur des sous-titres YouTube, et produit parfois des
crédits de fin multilingues quand on lui donne du bruit/silence plutôt que de la vraie
parole.

## 2. Vérification faite

Décodage des pistes retenues (`_moi.opus` / `_systeme.opus`, `core/audio.decoder_audio_16k`)
et calcul du RMS par fenêtre de 5 s sur les deux passages fautifs :

- Passage « CO CO CO... » (piste Participants, tranche 0–31 s) : 68 % d'échantillons à
  zéro numérique exact sur cette fenêtre — audio système majoritairement silencieux
  (rien ne jouait encore au tout début de l'enregistrement).
- Passage « 감사합니다 » (piste Moi, fin d'enregistrement ~85–98 s) : RMS ≈ 0.001–0.002,
  très en dessous du seuil anti-silence — bruit de fond/souffle micro, pas de parole.

Dans les deux cas : **pas de NaN, pas de clipping, pas de mélange de taux
d'échantillonnage détecté** — la capture 16 kHz (`docs/20`) et le hot-switch micro ne
sont pas en cause. L'audio est numériquement propre ; le problème est que Whisper reçoit
un signal quasi silencieux et hallucine dessus.

## 3. Cause probable

Deux mécanismes se combinent :

1. **Gate anti-silence par tranche entière**, pas par sous-fenêtre.
   `MoteurMLX._SEUIL_RMS = 0.008` (`src/debrief_meet/platform/macos/moteur_mlx.py:160`)
   n'ignore une tranche que si son RMS **moyen** est sous le seuil. Une tranche de 30 s
   qui contient un peu de vraie parole ET une portion silencieuse passe le gate en entier
   — Whisper reçoit alors la portion silencieuse mélangée au reste et peut halluciner
   dessus localement (répétition de token, credits de fin).

2. **`normaliser_asr()` amplifie le bruit de fond**, pas seulement la parole faible.
   `src/debrief_meet/core/audio.py:47` remonte tout audio dont le RMS est **≥ `1e-5`**
   (plancher très permissif) jusqu'à `cible_rms=0.03`, avec un gain plafonné à `×20`.
   Objectif initial (cf. docstring de la fonction) : ne pas perdre de la parole faible
   après l'AEC. Effet de bord : une tranche quasi silencieuse mais pas totalement à zéro
   (bruit de fond, souffle micro, RMS ~0.001) peut être amplifiée jusqu'à repasser le
   seuil anti-silence du moteur — avec du **bruit amplifié**, pas de la parole. Whisper
   reçoit alors un signal ambigu et invente du texte.

## 4. Pistes de correctif (non appliquées — à évaluer si le problème se confirme)

- Relever le RMS plancher de `normaliser_asr` avant amplification (actuellement `1e-5`,
  quasiment "tout sauf le silence pur") et/ou plafonner davantage `gain_max`.
- Remplacer le gate anti-silence "par tranche entière" par un gate "par sous-fenêtre"
  (ex. découper la tranche de 30 s en blocs de quelques secondes, ne transcrire/garder
  que les blocs qui dépassent individuellement le seuil).
- Filtre de post-traitement anti-répétition sur le texte produit (détecter un
  token/motif répété N fois d'affilée et le supprimer) — traite le symptôme observé le
  plus visible (`CO CO CO...`), pas la cause (n'empêcherait pas une hallucination "propre"
  comme `감사합니다`).

## 5. Localisation

- `src/debrief_meet/core/audio.py:47` — `normaliser_asr()`
- `src/debrief_meet/platform/macos/moteur_mlx.py:160` — seuil anti-silence `_SEUIL_RMS`
- `src/debrief_meet/core/reunion.py` — `_WorkerTranche._transcrire_micro` /
  `_transcrire_systeme` (point d'appel de `normaliser_asr` avant `moteur.transcrire`)
