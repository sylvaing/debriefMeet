# Continuité micro & taux d'échantillonnage — bug AirPods `-10851`

> **Statut :** ✅ implémenté (2026-07-01, étapes A/B/C, 530 tests passent — voir §9).
> Reste : validation manuelle en conditions réelles (AirPods + switch en cours de réunion, §9).
> Références : `06-integration-aec.md`, `05-spike-aec-webrtc.md`, `04-plan-detection-peripherique-audio.md`.

---

## 1. Symptôme observé

En réunion via AirPods, les enregistrements ne captent pas le micro. Transcriptions marquées :

```
> ⚠️ Microphone non disponible — transcription audio système uniquement.
```

Terminal (`make run`), un bloc par enregistrement raté :

```
||PaMacCore (AUHAL)|| Warning on line 521: err=''!obj'', msg=Unknown Error
||PaMacCore (AUHAL)|| Warning on line 441: err=''!obj'', msg=Unknown Error
||PaMacCore (AUHAL)|| Error on line 1322: err='-10851', msg=Audio Unit: Invalid Property Value
```

`-10851` = `kAudioUnitErr_InvalidPropertyValue`.

## 2. Cause racine

`platform/commun/micro_sounddevice.py` code en dur `self._sr = 44_100` (ligne ~30) et ouvre
`sd.InputStream(samplerate=44100, ...)`. Or les AirPods, utilisés **comme micro** (et déjà tenus
par Teams/Meet), passent en mode Bluetooth mains-libres verrouillé à **24 000 Hz** — ils
n'exposent pas 44 100 Hz en entrée. Core Audio refuse → `-10851`.

Chaîne complète de l'échec :
1. Config `micro_index: null` → `reunion.py` `demarrer(None)` → `_ouvrir_flux(sd, None)`.
2. Périphérique d'entrée par défaut = AirPods à 24 kHz (`sd.query_devices` : `defSR=24000`).
3. `InputStream(samplerate=44100)` sur les AirPods → AUHAL `-10851` (warnings 521/441 = sondages).
4. `_ouvrir_flux` : `device=None` échoue → la branche `except` **relance** (pas de repli).
5. `reunion.py:151` capte l'exception → `_avec_micro = False` → « Micro indisponible ».
6. La réunion continue en audio-système-seul → tag ⚠️, un seul locuteur « Participants ».

Deux blocs AUHAL dans le terminal = deux réunions ratées.

**Fait central :** toute la chaîne finit de toute façon en **16 kHz** (Whisper = 16 kHz ;
`aec.py` `SR_AEC = 16_000` ; WAV retenu `fichiers.py` `_SR_AUDIO = 16_000`). Le 16 kHz est le
point de convergence obligatoire, pas une option.

## 3. Décision d'architecture retenue — Proposition 1

**Normaliser le micro à 16 kHz dès la couche de capture.** La couche micro rééchantillonne
chaque bloc vers 16 kHz mono ; `taux_echantillonnage` devient **constant (16000)**. Les
changements de périphérique (48k ↔ 24k) sont absorbés à l'intérieur de la capture et deviennent
invisibles pour `reunion.py`, l'AEC et l'enregistreur.

Pourquoi 16k et pas 24k : le pivot 24k obligerait à reconvertir 24k→16k pour Whisper (double
rééchantillonnage) sans aucun gain de qualité (le WAV final est déjà 16k). 16k = le seul taux
universel de la chaîne.

Alternative écartée (proposition 2 : garder le taux natif, homogénéiser seulement au switch) :
laisse le reste du code gérer des taux variables entre tranches et impose de reconstruire l'AEC
à chaque switch. Plus de pièces mobiles pour le même résultat.

## 4. Le problème de continuité que ça résout

Si on change de micro **pendant** une tranche de 30 s, le buffer de cette tranche contient un
bout à 48k (avant) et un bout à 24k (après). Le code applique **un seul** taux à tout le buffer
→ la moitié de l'audio est lue à la mauvaise vitesse → Whisper hallucine.

Avec la proposition 1, le buffer contient **toujours** du 16k → **tranche à taux homogène par
construction**, le mélange de taux devient impossible partout.

## 5. Ce qui rend l'implémentation simple (déjà en place)

- `core/audio.py` `reechantillonner(audio, sr_source, sr_cible=16_000)` **court-circuite quand
  `sr_source == sr_cible`** → une fois le micro en 16k, tous les rééchantillonnages en aval
  deviennent des no-op gratuits.
- L'AEC sait déjà se recaler : `ProcesseurAEC._reset_etat()` (appelé par `demarrer()`,
  `aec.py:167/183`) remet `_calibre=False` et vide les buffers. Pas besoin de reconstruire
  l'objet au switch — juste rappeler ce reset.
- Le basculement à chaud existe déjà : `SurveillantPeripheriques` (écoute `audioInputsChanged`,
  anti-rebond 300 ms) → `reunion._sur_changement_peripherique` → `micro.redemarrer(micro_index)`
  qui **préserve le buffer** (`preserve = list(self._buffer)`), rouvre, jette le warm-up 200 ms,
  restaure le buffer. L'enregistrement ne repart pas de zéro.

## 6. Plan d'implémentation (ordre conseillé)

### Étape A — `platform/commun/micro_sounddevice.py` (corrige aussi le bug AirPods d'origine)
- `__init__` : `taux_echantillonnage` retourne **16000 en dur** (taux canonique). Conserver à
  part le taux natif réellement utilisé pour ouvrir chaque flux.
- `_ouvrir_flux` : ouvrir au **taux natif du périphérique** (`sd.query_devices(idx)['default_samplerate']`,
  ou `samplerate=None`) — **plus jamais 44100 imposé** → débloque les AirPods (fini `-10851`).
  Mémoriser le taux effectif du flux (dispo via l'objet stream `.samplerate`).
  Conserver le repli sur le périphérique par défaut, lui aussi ouvert au taux natif.
- Buffer + `_callback` : **étiqueter chaque bloc avec son taux natif** en entrant dans le buffer.
- `recuperer_echantillons` : parcourir le buffer, **rééchantillonner chaque suite de blocs de
  même taux vers 16k en un seul appel**, puis concaténer. Sortie **toujours 16k**.
  - Pourquoi par-suite et pas bloc-par-bloc : `resample_poly` a des transitoires en bord de bloc ;
    rééchantillonner toute une suite d'un coup évite les clics. Un switch en cours de tranche
    produit deux suites (48k puis 24k) recollées en 16k → tranche homogène.
  - `redemarrer()` doit préserver les blocs **avec leur étiquette de taux** (le snapshot
    `preserve` doit garder les tags).

### Étape B — `core/reunion.py` (recalage AEC + trou de warm-up)
- `_sur_changement_peripherique` : ne déclencher `redemarrer()` **que si le périphérique d'entrée
  a réellement changé** (comparer l'id résolu avant/après) → évite un trou de 200 ms sur un
  événement en double ou un simple changement de **sortie**.
- Après un `redemarrer()` réussi : **réinitialiser la calibration AEC** (nouveau chemin d'écho
  micro/HP) → ~1 s de transitoire au lieu d'une annulation d'écho fausse pendant plusieurs sec.
- `_capturer_tranche` : `sr_micro = taux_echantillonnage` vaut désormais 16000 constant →
  `reechantillonner(…, 16000)` devient no-op. **Aucune autre modif nécessaire.**

### Étape C — cosmétique
- `__main__.py:168` : `ProcesseurAEC(sr_micro=adaptateurs.micro.taux_echantillonnage, ...)` lit
  désormais 16000 (constant, stable). Rien à changer, devient juste correct.
- `platform/interfaces.py` : docstring `CaptureMicro.taux_echantillonnage` (« Défaut : 44 100 »)
  → mettre à jour (16 kHz canonique).

## 7. Périmètre — hors scope

- **Côté audio système : rien à toucher.** Le helper `helpers/macos/sck-audio/SCKAudioCapture.swift`
  est en **format fixe** (`config.sampleRate = 48_000`, `FORMAT` émis une seule fois). ScreenCaptureKit
  capte le **mix système**, pas un périphérique → il ne s'interrompt pas et ne change ni de taux ni
  de canaux quand on passe HP Mac ↔ AirPods. `SurveillantPeripheriques` a donc raison de n'écouter
  que `audioInputsChanged`.

## 8. Joint résiduel (limite assumée)

Au moment précis d'un changement de micro, il reste ~200 ms jetés (warm-up du nouveau flux)
+ ~1 s de recalage AEC. L'enregistrement **ne s'arrête pas** et le buffer est préservé, mais ce
court instant est dégradé. Inhérent au changement physique de périphérique — non supprimable sans
double-flux permanent (bien plus lourd, hors périmètre).

## 9. Vérifications avant de clôturer

- [ ] Test manuel : réunion via AirPods → micro capté (plus de `-10851`, plus de tag ⚠️).
- [ ] Test manuel : basculer Mac ↔ AirPods **en cours de réunion** → l'enregistrement continue, la
  transcription reste cohérente de part et d'autre du switch (pas de portion à mauvaise vitesse).
- [x] Suite de tests verte : `pytest -m "not integration"` → 526 passed ; `pytest` (avec
  intégration) → 530 passed (2026-07-01). Nouveaux tests : taux natif à l'ouverture, étiquetage +
  rééchantillonnage par suite homogène, `resoudre_peripherique` (macOS `platform/commun`), anti-
  doublon du redémarrage à chaud + recalage AEC (`core/reunion.py`), `ProcesseurAEC.recalibrer()`.

Il reste les deux tests manuels ci-dessus (matériel AirPods requis) avant de clore la doc.
