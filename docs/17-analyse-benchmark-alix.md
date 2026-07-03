# Analyse benchmark — Alix_home (Windows, i5-1235U, Intel UHD)

**Date benchmark** : 2026-06-30  
**Rapport source** : `benchmark/rapports/bench_Alix_home_windows_20260630-141649.zip`  
**Machine** : Windows 10, i5-1235U (10c/12t), 16.8 Go RAM, Intel UHD Graphics (iGPU)

---

## Résultats transcription

### CPU — faster-whisper int8

| Modèle   | RTF moyen | WER  | RAM pic |
|----------|-----------|------|---------|
| small    | 0.43      | 54%  | 1.4 Go  |
| medium   | 1.30      | 45%  | 3.3 Go  |
| large-v3 | 2.01      | 0% (ref) | 4.5 Go |

Verdict benchmark : **LIMITE** — seul `small` passe sous RTF 1.0, mais qualité médiocre (WER 54%).

### OpenVINO GPU — Intel UHD Graphics

| Modèle   | RTF moyen | WER   | RAM pic |
|----------|-----------|-------|---------|
| small    | 0.28      | **99%** ⚠ | 2.1 Go |
| medium   | 0.39      | **73%** ⚠ | 4.6 Go |
| large-v3 | **0.546** | **0%** ✓  | 6.2 Go |

**Enseignement clé** : OpenVINO + `large-v3` sur Intel UHD = RTF 0.546, qualité identique à large-v3 CPU.  
Cette machine peut faire du `large-v3` **temps réel via GPU OpenVINO** — le verdict "LIMITE small" est trop pessimiste.

**Action future** : quand OpenVINO GPU est disponible et que large-v3 passe sous RTF 1.0, proposer ce mode plutôt que small CPU.

---

## Problèmes identifiés

### BUG 1 — `CO_E_NOTINITIALIZED` (0x800401F0) en thread secondaire

**Symptôme** (console, lors de l'étape AEC) :
```
Exception in thread Thread-5 (_rec_sys):
  File "sondes_capture.py", line 181, in _capturer_loopback_windows
    hp = sc.default_speaker()
  File "soundcard/mediafoundation.py", line 225, in __init__
    _com.check_error(hr)
RuntimeError: Error 0x800401f0
```

**Cause** : COM/MediaFoundation doit être initialisé dans chaque thread qui l'utilise.  
Le test YouTube (thread principal) passe. L'étape AEC lance `_rec_sys` dans `Thread-5` sans initialiser COM.

**Conséquences** :
- Capture système échoue → AEC pas évalué → `attenuation_echo_db: null`
- `wer_avant_aec: 1.0` (micro capturé mais sans référence système, WER inutilisable)

**Fichier** : `benchmark/sondes_capture.py`, fonction `_capturer_loopback_windows` (ligne ~181)

**Fix à appliquer** :
```python
def _capturer_loopback_windows(duree: float, sr: int = SR_SONDE) -> dict:
    import soundcard as sc
    import ctypes
    ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_APARTMENTTHREADED
    try:
        hp = sc.default_speaker()
        ...
    finally:
        ctypes.windll.ole32.CoUninitialize()
```

---

### BUG 2 — Pyannote ÉCHEC `[WinError 127]` + timeout 48 min

**Symptôme** :
```
OSError: [WinError 127] La procédure spécifiée est introuvable
  → torchaudio._extension._torchaudio.pyd  (DLL système manquante)
```

**Durée anormale** : pyannote tourne de 13:12 à 14:00 (48 minutes) avant d'échouer — probablement le téléchargement du modèle HuggingFace qui timeout.

**Cause** : DLL système manquante pour charger `_torchaudio.pyd` (Visual C++ Redistributable incompatible avec torch 2.8.0, ou dépendance absente du bundle).

**Actions à prévoir** :
1. Ajouter un test d'import rapide `torchaudio` **avant** de lancer la diarisation pyannote, avec échec immédiat si indisponible (évite les 48 min de timeout).
2. Investiguer quelle DLL manque (procmon ou `dumpbin /dependents _torchaudio.pyd`) et l'inclure dans le bundle.

---

### BUG 3 — `observations: ""` dans le JSON

**Symptôme** : le JSON final contient `"observations": ""` (caractère de contrôle ASCII 1) au lieu de `""`.

**Cause probable** : saisie vide sur Windows interprétée comme `\x01` lors de la lecture `input()` dans `rapport.py`.

**Fix à prévoir** : filtrer les caractères de contrôle dans la collecte des observations.

---

### ANOMALIE — Hallucinations OpenVINO small/medium

Les transcriptions OpenVINO small et medium contiennent des répétitions infinies ("d'acier d'acier d'acier…", "les créations de l'utilisation et les créations de l'utilisation…").

C'est un bug connu de Whisper qui hallucine en boucle sur GPU intégré quand la précision/quantification change.  
OpenVINO large-v3 n'est pas affecté.

**Action future** : détecter les hallucinations par ratio de répétition (ex. si un n-gramme couvre > 30% du texte → marquer la transcription comme invalide, ne pas retenir ce mode).

---

### OBSERVATION — Sherpa détecte 15 locuteurs

Sur 30 min de réunion, sherpa-onnx détecte 15 locuteurs (RTF 0.379, 682s de traitement).  
Le seuil de clustering est trop sensible. À calibrer en Phase 5 (paramètre `min_duration_on` ou seuil de similarité).

---

## Résumé accélérateurs détectés

| Accélérateur   | Disponible |
|----------------|-----------|
| CUDA           | non       |
| OpenVINO       | **oui** (CPU + GPU) — v2026.2.1 |
| DirectML       | non (module absent) |
| AMD ROCm       | non       |
| Vulkan         | oui (Intel UHD) |

---

## Capture audio

- YouTube loopback : **son capté** (RMS 0.015, wasapi-loopback via soundcard) ✓
- AEC livekit : **disponible** (v1.1.12, win-amd64) ✓
- Capture AEC simultanée : **ÉCHEC** (bug COM thread — voir BUG 1)
- Périphérique entrée par défaut : Microphone Array (Realtek, 4 canaux)
- Périphérique sortie par défaut : écouteurs casque Bluetooth (Bluetooth)
