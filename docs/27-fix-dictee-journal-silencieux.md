# Fix Dictée/Journal muets — normalisation centralisée dans le moteur + observabilité

> **Statut :** ✅ implémenté (2026-07-02) — 556 passed.
> Plan rédigé le 2026-07-02 (session de diagnostic, preuves à l'appui).
> Ce document est conçu pour être donné tel quel à une session IA d'implémentation (Sonnet).
> **Périmètre : 4 correctifs + tests de non-régression. Rien d'autre.**
> Avant livraison : `make test` (attendu : les 542 tests actuels — moins ceux réécrits ici — + les nouveaux, tous verts).

---

## 1. Contexte — le diagnostic du 2026-07-02 (soir)

### 1.1 Symptômes rapportés

1. **Dictée** : rien dans le presse-papier après une dictée, aucune erreur visible (icône verte « terminé »).
2. **Journal** : aucune entrée dans l'Historique ni dans `~/Documents/debriefMeet/journal/`
   (dossier vide depuis le 29 juin — le journal est probablement cassé depuis l'ajout de la
   porte anti-silence).
3. **Logs** : activer les logs dans les Préférences ne prend effet qu'au redémarrage.

### 1.2 La preuve (données réelles de la session utilisateur du 2026-07-02, 22h15)

Le log `~/Library/Logs/debriefMeet/debriefMeet.log` montre la séquence 22h15-22h16 :
dictée ×2, journal ×2, réunion ×1 — **zéro erreur, zéro écriture journal loggée**.

La réunion de 22h15, elle, a produit un `.md` correctement transcrit
(« Ben là je démarre une réunion, savoir si ça fonctionne correctement »). Le RMS mesuré
sur son `_moi.opus` (ffmpeg → float32 → RMS) : **0.0027, pic 0.035** — c'est-à-dire **sous
la porte anti-silence du moteur** (`MoteurMLX._SEUIL_RMS = 0.008`,
`platform/macos/moteur_mlx.py:160`). Le micro de l'utilisateur capte très faible ;
`micro_index` est `null` en config → **tous les modes utilisent le même micro par défaut**.

### 1.3 Chaîne causale

La réunion transcrit quand même parce qu'elle passe l'audio par `normaliser_asr()`
(`core/audio.py:47` — remonte le RMS à 0.03, gain plafonné ×20, laisse le silence pur
< 1e-5 intact) **avant** `moteur.transcrire()`. Cette normalisation existe précisément
pour compenser la porte (« le moteur le rejetterait à tort comme du silence », dit sa
docstring). Elle est appliquée à **3 endroits** :

- `core/reunion.py:68` et `:74` (tranches micro + système)
- `core/transcription_differee.py:50`
- `core/diarization.py:274`

…mais **ni en dictée** (`core/dictee.py:30` — audio brut → moteur) **ni en journal**
(`core/journal.py:33`). Avec un micro faible : RMS brut < 0.008 → la porte rend un texte
vide → la dictée ne copie rien (`dictee.py:104` : `if texte.strip():`), le journal
n'écrit rien (`journal.py:107`) — **et l'icône affiche quand même TERMINÉ (vert)**.

### 1.4 Chemins d'échec tous silencieux (aggravant)

- Texte vide → TERMINÉ vert, aucun log, aucune notification (dictée et journal).
- `audio.size == 0` → retour direct à REPOS, aucun log, aucune notification
  (`dictee.py:78-80`, `journal.py:81-83`).
- Le seul log qui aurait tout révélé (« Audio silencieux (RMS=…) — transcription
  ignorée », `moteur_mlx.py:168`) est en niveau **debug**, or `configurer_logs(debug=False)`
  est câblé en dur (`__main__.py:109`) — le mode debug est inaccessible.

### 1.5 Décision d'architecture (validée par l'utilisateur)

**Déplacer la paire normalisation + porte anti-silence dans le moteur** (couche
`MoteurTranscription`), au lieu d'ajouter `normaliser_asr` aux 2 appelants manquants :
le traitement devient central, impossible à désynchroniser entre appelants, et tout
futur backend (Phase 5 Windows, Phase 6 Linux) en hérite gratuitement.

### 1.6 ⚠️ Ordre imposé : normaliser PUIS porter (pas l'inverse)

La réunion d'aujourd'hui fait déjà « normalisation en amont → porte dans le moteur » :
la porte voit un RMS de 0.03 et laisse passer. Si on portait l'audio **brut** à 0.008
dans le moteur central, la tranche réunion de 22h15 (RMS brut 0.0027) serait rejetée →
**régression**. L'ordre central est donc : `normaliser_asr` puis porte à 0.008 sur
l'audio normalisé. Conséquences assumées :

- **Réunion / transcription différée / diarization : comportement strictement identique**
  (elles normalisaient déjà avant la porte).
- **Dictée / journal : c'est le fix** — la parole faible est remontée et transcrite.
- Le seuil *effectif* sur l'audio brut devient ~0.0004 (0.008 ÷ gain max 20) : seul le
  silence quasi pur est ignoré. Le risque d'hallucination sur bruit de fond (docs/22)
  reste ce qu'il est aujourd'hui pour la réunion, et s'étend à dictée/journal — assumé,
  c'est le comportement aligné ; la piste docs/22 « relever le plancher 1e-5 de
  `normaliser_asr` » reste ouverte, hors périmètre ici.

---

## 2. Correctif 1 — centraliser normalisation + porte dans `MoteurTranscription`

**C'est le fix racine des bugs dictée et journal.**

### 2.1 `core/audio.py` — constante unique + `preparer_asr()`

```python
# Porte anti-silence centrale (anti-hallucination Whisper, cf. docs/22 et docs/27).
# Source unique : core/aec.py et les moteurs importent d'ici, plus de copies locales.
SEUIL_RMS_SILENCE = 0.008


def preparer_asr(audio: np.ndarray) -> np.ndarray | None:
    """Prépare un audio 16 kHz pour la transcription : normalise puis applique la
    porte anti-silence. Retourne None si l'audio ne doit pas être transcrit
    (vide, ou silence même après normalisation — le silence pur n'est pas amplifié).

    L'ordre normaliser→porter est contractuel (docs/27 §1.6) : porter l'audio brut
    rejetterait la parole faible (micro discret, piste post-AEC atténuée)."""
    if not len(audio):
        return None
    audio = normaliser_asr(audio)
    rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
    if rms < SEUIL_RMS_SILENCE:
        logger.debug("Audio silencieux (RMS=%.4f < %.4f) — transcription ignorée",
                     rms, SEUIL_RMS_SILENCE)
        return None
    return audio
```

(Ajouter `logger = logging.getLogger(__name__)` si absent du module.)

### 2.2 `core/aec.py` — supprimer la copie locale du seuil

`core/aec.py:42` définit `SEUIL_RMS = 0.008  # aligné sur MoteurMLX._SEUIL_RMS` —
l'alignement est manuel, donc fragile. Remplacer par :

```python
from debrief_meet.core.audio import SEUIL_RMS_SILENCE as SEUIL_RMS
```

(Garder le nom local `SEUIL_RMS` : il est utilisé ligne ~297 et importé par
`tests/test_aec.py:15` — ne pas casser ces usages.)

### 2.3 `platform/interfaces.py` — méthode template

`MoteurTranscription.transcrire` devient **concrète** (préparation centrale + délégation),
et une nouvelle méthode abstraite reçoit l'audio prêt :

```python
class MoteurTranscription(ABC):
    ...
    def transcrire(self, audio: "np.ndarray", langue: str | None) -> ResultatTranscription:
        """Transcrit `audio` (float32 mono 16 kHz). Applique la préparation centrale
        (normalisation + porte anti-silence, docs/27) puis délègue au backend.
        Les appelants n'ont PLUS à normaliser eux-mêmes."""
        from debrief_meet.core.audio import preparer_asr  # paresseux : numpy/scipy
        pret = preparer_asr(audio)
        if pret is None:
            return ResultatTranscription(texte="", langue_detectee=langue, segments=[])
        return self._transcrire_pret(pret, langue)

    @abstractmethod
    def _transcrire_pret(self, audio: "np.ndarray", langue: str | None) -> ResultatTranscription:
        """Transcription effective d'un audio déjà normalisé et non silencieux."""
```

Import paresseux **obligatoire** dans la méthode (pas en tête de module) :
`interfaces.py` est importé très tôt et par toutes les couches — ne pas y tirer
numpy/scipy au chargement. Pas de cycle d'import : `core.audio` n'importe rien de
`platform`.

### 2.4 Implémentations — renommer `transcrire` → `_transcrire_pret`

| Fichier | Changements |
|---|---|
| `platform/macos/moteur_mlx.py` | Renommer la méthode ; **supprimer** le check tranche vide (lignes 164-165), le calcul RMS + `_SEUIL_RMS` (lignes 159-169) et l'`import numpy` devenu inutile dans la méthode. Garder tel quel : résolution du repo, création paresseuse de worker, pool, gestion d'erreurs. |
| `platform/stubs.py:22` (`MoteurStub`) | Renommer la méthode. |
| `tests/fakes/adapters.py:19` (`MoteurFake`) | Renommer la méthode (les tests qui appellent `moteur.transcrire(...)` continuent de passer par le template hérité — c'est voulu, ça teste le vrai chemin). |

Note Phase 5/6 : les futurs backends Windows/Linux implémenteront `_transcrire_pret`
et hériteront de la préparation — aucun doc à modifier maintenant, le spike (docs/18)
n'implémente pas cette interface.

### 2.5 Appelants — retirer les normalisations devenues redondantes

| Fichier | Action |
|---|---|
| `core/reunion.py:68` et `:74` | Retirer `normaliser_asr(...)` (garder `reechantillonner`). Nettoyer l'import ligne 10 si plus utilisé. |
| `core/transcription_differee.py:50` | Retirer `normaliser_asr(...)` (garder `decoder_audio_16k`). Nettoyer l'import. |
| `core/diarization.py:274` | **GARDER** l'appel : l'audio normalisé sert aussi à **pyannote** (`moteur_diarization.diariser(audio)`, ligne 276), qui ne passe pas par `MoteurTranscription`. Ajouter un commentaire : `# normalisation conservée pour pyannote ; le moteur re-normalise en no-op (audio déjà à la cible)`. La double normalisation est effectivement un no-op : `normaliser_asr` n'amplifie pas un audio déjà ≥ cible (`audio.py:62`). |

---

## 3. Correctif 2 — feedback quand rien n'est produit (dictée + journal)

**Le vert menteur disparaît : si rien n'est copié/écrit, l'utilisateur le voit.**

### 3.1 `core/dictee.py` et `core/journal.py` — signal + états + logs

Ajouter aux deux orchestrateurs un signal :

```python
rien_entendu = Signal(str)   # message à notifier — rien n'a été copié/écrit
```

**Chemin « audio vide »** (`dictee.py:78-80`, `journal.py:81-83`) — remplacer le retour
muet par :

```python
if audio.size == 0:
    logger.info("Dictée : aucun échantillon capté — rien à transcrire")
    self.rien_entendu.emit("Aucun son capté — vérifiez le micro.")
    self.etat_visuel_change.emit(EtatVisuel.ERREUR)
    QTimer.singleShot(self._delai_erreur_ms,
                      lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS))
    return
```

**Chemin « texte vide »** (`_sur_ok`, `dictee.py:102-110`, `journal.py:105-117`) —
distinguer succès et vide :

```python
@Slot(str)
def _sur_ok(self, texte: str) -> None:
    if not texte.strip():
        logger.info("Dictée : transcription vide (silence ou parole inaudible) — rien copié")
        self.rien_entendu.emit("Aucune parole détectée — rien n'a été copié.")
        self.etat_visuel_change.emit(EtatVisuel.ERREUR)
        QTimer.singleShot(self._delai_erreur_ms,
                          lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS))
        return
    self._presse_papiers.copier(texte.strip())
    self.etat_visuel_change.emit(EtatVisuel.TERMINE)
    ...  # inchangé
```

Journal : messages « rien n'a été écrit dans le journal » ; le reste est symétrique.
Journal : logger aussi en INFO l'écriture réussie — déjà fait (`journal.py:110`).

### 3.2 `ui/tray.py` — notification

Ajouter, sur le modèle exact de `notifier_micro_perdu` (`tray.py:167-170`, respecte la
config `notifications`) :

```python
def notifier_rien_entendu(self, message: str) -> None:
    if not self._config.get("notifications"):
        return
    self.showMessage("Rien entendu", message, icone_pour_etat(EtatVisuel.ERREUR), 8000)
```

### 3.3 `__main__.py` — câblage

Après les connexions existantes (lignes ~203-207) :

```python
orch_dictee.rien_entendu.connect(tray.notifier_rien_entendu)
orch_journal.rien_entendu.connect(tray.notifier_rien_entendu)
```

---

## 4. Correctif 3 — logs pris en compte à chaud + mode debug accessible

### 4.1 `core/config.py` — nouvelle clé

```python
"logs_debug": False,
```

### 4.2 `ui/preferences.py` — reconfigurer à la sauvegarde

Dans le handler d'enregistrement (autour de la ligne 458, où `logs_actifs` est déjà
sauvé) : ajouter une case « Logs détaillés (debug) » à côté de la case logs existante
(ligne ~397), la sauver dans `logs_debug`, puis **appliquer immédiatement** :

```python
from debrief_meet.core.logs import configurer_logs
configurer_logs(actifs=self._check_logs.isChecked(),
                debug=self._check_debug.isChecked())
```

`configurer_logs` est déjà idempotente (`root.handlers.clear()`, `logs.py:22`) — aucun
autre changement nécessaire côté `core/logs.py`.

### 4.3 `__main__.py:107-110` — brancher la clé debug au démarrage

```python
configurer_logs(
    actifs=config.get("logs_actifs"),
    debug=config.get("logs_debug"),
)
```

(C'est ce `debug=False` câblé en dur qui a rendu le diagnostic de ce soir impossible
sans analyse de code : le log « Audio silencieux (RMS=…) » était invisible.)

---

## 5. Correctif 4 — dictée/journal : micro configuré + échec de démarrage géré

### 5.1 Passer la config aux orchestrateurs

`OrchestrateurDictee.__init__` et `OrchestrateurJournal.__init__` reçoivent
`config: Config` (comme `OrchestrateurReunion`) ; mettre à jour les deux constructions
dans `__main__.py` (lignes ~134 et ~187) et les tests qui instancient ces classes
(`tests/test_dictee.py`, `tests/test_journal.py` — leur passer une `Config()` neuve ou
un fake existant).

### 5.2 `_demarrer()` — index configuré + try/except

Aujourd'hui (`dictee.py:68-71`, `journal.py:71-74`) : `self._micro.demarrer()` sans index
ni gestion d'erreur — la dictée enregistre le micro *par défaut* même si l'utilisateur en
a choisi un dans les Préférences (la réunion, elle, honore `micro_index`), et un échec
d'ouverture lève dans le slot sans aucun feedback. Remplacer par :

```python
def _demarrer(self) -> None:
    try:
        self._micro.demarrer(self._config.get("micro_index"))
    except Exception as exc:
        logger.error("Dictée : démarrage micro impossible (%s)", exc)
        self.rien_entendu.emit("Micro indisponible — dictée annulée.")
        self.etat_visuel_change.emit(EtatVisuel.ERREUR)
        QTimer.singleShot(self._delai_erreur_ms,
                          lambda: self.etat_visuel_change.emit(EtatVisuel.REPOS))
        # Revenir à IDLE — en différé : on est DANS le handler de mode_change,
        # re-toggler synchronement ré-entrerait dans l'émission du signal en cours.
        QTimer.singleShot(0, self._machine.toggle_dictee)
        return
    self._enregistrement_actif = True
    self.etat_visuel_change.emit(EtatVisuel.ENREGISTREMENT)
```

Détails qui comptent :

- **`_enregistrement_actif = True` passe APRÈS le try** (aujourd'hui il est posé avant) :
  ainsi le retour à IDLE déclenché par le `toggle` différé ne lance pas
  `_arreter_et_transcrire()` (garde `self._enregistrement_actif` dans
  `_sur_mode_change`).
- Journal : identique avec `toggle_journal` et le message « journal annulé ».
- Le repli « périphérique indisponible → défaut » existe déjà plus bas dans
  `CaptureMicroSounddevice._ouvrir_flux` (`micro_sounddevice.py:78-92`) — ce try/except
  n'attrape que l'échec *franc* (aucun micro du tout).

---

## 6. Hors périmètre (pour mémoire)

- **Warning terminal `kAudioDevicePropertyPreferredChannelLayout … 12 VS 32 bytes`** :
  message interne de Qt Multimedia (backend ffmpeg) émis pendant l'énumération CoreAudio
  de `QMediaDevices` (notre `SurveillantPeripheriques`) quand un périphérique — AirPods,
  iPhone en continuité, périphérique virtuel — renvoie un layout plus petit qu'attendu.
  **Bénin, aucun impact** : notre capture passe par PortAudio, pas Qt Multimedia. Ne rien
  faire ; si le bruit gêne un jour, `QT_LOGGING_RULES="qt.multimedia.*=false"` dans
  l'environnement de `make run`.
- Relever le plancher 1e-5 de `normaliser_asr` (anti-hallucination, docs/22) : à
  surveiller, pas dans ce lot.
- Stocker le **nom** du micro plutôt que l'index (les index PortAudio bougent après un
  refresh, cf. `micro_sounddevice.py:110-113`) : amélioration connue, hors lot.

---

## 7. Tests

### `tests/test_audio.py` — `preparer_asr` (nouveau bloc)

1. Audio vide → `None`.
2. Silence pur (zéros) → `None` (non amplifié puis sous la porte).
3. Souffle quasi nul (amplitude 5e-6) → `None`.
4. **Parole faible (RMS ≈ 0.003, le cas réel du 2026-07-02)** → tableau non-None,
   RMS ≈ 0.03 (normalisé au-dessus de la porte). *C'est LE test de non-régression du bug.*
5. Audio déjà fort → rendu tel quel (pas d'atténuation).

### `tests/test_moteur_mlx.py` — adapter les tests de la porte (lignes 33-75)

- `test_gate_rms_silence_retourne_vide_sans_worker` (zéros) et
  `test_audio_vide_retourne_vide_sans_warning` : passent toujours par le `transcrire`
  hérité — adapter seulement les références à `moteur._SEUIL_RMS` (supprimé).
- `test_gate_rms_bruit_faible_court_circuite` : **le comportement change volontairement**
  — un souffle constant à 0.004 est désormais normalisé puis transcrit (aligné sur le
  pipeline réunion, §1.6). Réécrire : souffle à 5e-6 → court-circuit (pool jamais
  sollicité) ; et ajouter le test inverse : audio à 0.004 → le pool EST sollicité
  (mocker/fake le worker, motifs existants dans ce fichier).

### `tests/test_dictee.py` / `tests/test_journal.py`

6. Transcription vide → rien copié / rien écrit, signal `rien_entendu` émis,
   `EtatVisuel.ERREUR` émis (et pas TERMINE).
7. `recuperer_echantillons()` vide → signal `rien_entendu` émis, aucune transcription
   lancée.
8. `_demarrer` : `micro.demarrer` reçoit bien `config.get("micro_index")`.
9. `micro.demarrer` lève → signal émis, `_enregistrement_actif` reste False, la machine
   revient à IDLE (traiter le `QTimer.singleShot(0, …)` : `qtbot.wait` ou processEvents).

### `tests/test_preferences.py`

10. Sauvegarde des préférences avec logs cochés → `configurer_logs` appelé avec les
    bonnes valeurs (monkeypatcher **le nom importé dans `ui.preferences`**, pas
    `core.logs.configurer_logs`).

### Non-régression existants

- `tests/test_reunion.py`, `test_transcription_differee.py`, `test_diarization.py` :
  doivent rester verts sans modification de leurs assertions (le pipeline effectif est
  inchangé pour ces trois flux — §1.6). Si un test échoue là, c'est un bug du correctif,
  pas du test.
- `tests/test_aec.py` : l'import `SEUIL_RMS` continue de fonctionner (réexport §2.2).

---

## 8. Validation manuelle (après `make test`)

1. **Le cas réel** : parler à voix normale à distance normale du Mac (micro par défaut,
   volume d'entrée système inchangé), dictée de ~5 s → le texte est dans le presse-papier.
2. Journal de ~5 s → l'entrée apparaît dans `~/Documents/debriefMeet/journal/AAAA-MM-JJ.md`
   et dans l'Historique.
3. Dictée bouche fermée (vrai silence) → notification « Aucune parole détectée », icône
   erreur brève, presse-papier inchangé — plus de faux vert.
4. Préférences → activer logs + debug → **sans redémarrer**, faire une dictée silencieuse
   → `~/Library/Logs/debriefMeet/debriefMeet.log` contient la ligne debug
   « Audio silencieux (RMS=…) ».
5. Une réunion courte avec parole → le `.md` contient la transcription (non-régression
   du flux réunion).

---

## 9. Clôture

- Mettre à jour `CLAUDE.md` : tableau « Docs de référence » (marquer docs/27 fait) et
  « Suite attendue » (nouveau compte de tests).
- Si docs/22 est touché par la discussion du seuil : y ajouter un renvoi vers §1.6
  (la porte est désormais centrale, dans `core/audio.py`).
