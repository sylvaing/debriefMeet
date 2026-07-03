# POC diarization — sherpa-onnx vs pyannote (isolé, hors app)

Compare les deux moteurs de diarization sur de **vraies réunions MP3**, pour la
**Phase D** (cf. [`docs/07-diarization.md`](../../docs/07-diarization.md)).
But : trancher **vitesse** + **qualité** avant d'intégrer.

> Spike isolé : rien n'est ajouté à l'app ni à `pyproject.toml`.

## Ce qui est mesuré
- **Vitesse** : facteur temps réel de chaque moteur (objectif).
- **Qualité** : transcription MLX Whisper + attribution des locuteurs → deux comptes-rendus
  « Locuteur N : … » côte à côte, à **juger à l'œil** (pas de vérité terrain).

## Prêt à l'emploi
- **sherpa-onnx** : installé, modèles téléchargés dans `models/` (segmentation pyannote-3.0
  ONNX + embedding wespeaker). **Aucune licence requise.**
- **pyannote** : `pyannote.audio` installé, mais ses modèles sont **sous licence HuggingFace**
  → il faut un **token HF** (voir ci-dessous).

## Utilisation

```bash
# 1) Dépose tes MP3 ici :
#    spike/diarization/audio/*.mp3   (ou passe --audio chemin.mp3)

# 2) sherpa-onnx seul (immédiat) :
.venv/bin/python spike/diarization/comparer.py --audio reunion.mp3

# 3) avec pyannote (comparaison complète) :
HF_TOKEN=hf_xxxxx .venv/bin/python spike/diarization/comparer.py --audio reunion.mp3

# vitesse seule (rapide, sans transcription) :
.venv/bin/python spike/diarization/comparer.py --audio reunion.mp3 --no-transcrire
```

Sorties dans `sorties/` : `<nom>_sherpa.md` et `<nom>_pyannote.md` (qui-parle-quand +
texte), plus une **synthèse vitesse** en console.

## Activer pyannote (token HF)
1. Compte sur huggingface.co → créer un **token** (Settings → Access Tokens, rôle *read*).
2. **Accepter les conditions** des 2 modèles (sinon téléchargement refusé) :
   - https://hf.co/pyannote/segmentation-3.0
   - https://hf.co/pyannote/speaker-diarization-3.1
3. Lancer avec `HF_TOKEN=hf_xxx …` (le 1er run télécharge les modèles).

## Note d'empreinte (pour la décision d'intégration)
`pyannote.audio` tire **PyTorch + lightning + matplotlib + pandas…** (lourd) ; sherpa-onnx
n'est que de l'**ONNX Runtime** (léger, cross-platform). À peser dans le choix final.
