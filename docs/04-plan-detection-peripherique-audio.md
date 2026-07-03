# Plan d'action — Détection du changement de périphérique audio

> **Statut :** ✅ TERMINÉ (Phase 3.5) — implémenté et testé (163 tests verts). Validation manuelle (vraie visio + retrait AirPods) restant à jouer par l'utilisateur.
> **Objet :** détecter **instantanément** un changement de périphérique micro pendant un enregistrement (ex. retrait des AirPods) et **reprendre la capture à chaud** sans perdre la réunion.
> Références : `02-specifications-techniques.md` (§4.x plomberie audio), `03-phases-implementation.md`.

---

## 1. Problème

Pendant une réunion, le périphérique d'entrée par défaut peut changer :

- L'utilisateur **retire ses AirPods** → macOS bascule la sortie ET l'entrée sur le micro intégré.
- Le flux `sounddevice` ouvert sur l'ancien périphérique ne suit pas : soit il plante (`PortAudioError -9986`), soit il devient muet jusqu'à la fin de la réunion.

**Symptôme observé** (réunion `2026-06-19_14-03`) : après retrait des AirPods, seuls les participants (audio système, capté par SCK qui est device-agnostic) ont été transcrits ; le micro est resté muet.

**Déjà corrigé** (commit précédent) :
- Repli sur le périphérique par défaut si l'index configuré échoue à l'**ouverture**.
- Repli « réunion sans micro » si même le défaut échoue.

**Ce qui reste à faire** : détecter le changement **en cours** d'enregistrement et reconnecter à chaud.

---

## 2. Décision technique & alternatives (à reporter dans les specs)

### Décision retenue : **Qt Multimedia** — `QMediaDevices.audioInputsChanged`

Signal Qt événementiel (instantané, pas de polling) émis dès qu'un périphérique d'entrée
apparaît/disparaît. Intégré à la boucle d'événements Qt, **cross-platform** (macOS/Windows/Linux),
**aucune dépendance ajoutée** (inclus dans PySide6, déjà présent).

- Couvre le cas réel (AirPods retirés → la liste des entrées change → signal émis).
- **Angle mort** (assumé, marginal) : changement de périphérique par défaut *sans* changement de
  liste — ex. deux micros restent branchés et l'utilisateur change le défaut dans les Réglages.
  Non couvert par `audioInputsChanged` (la liste ne change pas).
- Vit dans la couche **commune** (`platform/commun/`) → une seule implémentation, fidèle à la
  philosophie « cœur partagé, plomberie isolée ».

### Alternatives écartées (conservées pour traçabilité — réévaluables si besoin)

| Option | Pourquoi écartée | Quand la reconsidérer |
|---|---|---|
| **CoreAudio natif (ctypes)** — listener sur `kAudioHardwarePropertyDefaultInputDevice` | macOS-only (réimpl. Phases 5/6) ; ~100 lignes de ctypes fragiles (structs `AudioObjectPropertyAddress`, callbacks `CFUNCTYPE`, intégration `CFRunLoop`) | Si l'angle mort de Qt devient bloquant (besoin de détecter un changement de défaut sans débranchement). Aucune dépendance à ajouter. |
| **PyObjC** — même cible CoreAudio mais bindings typés | macOS-only **+** grosse dépendance (`pyobjc-core` + framework, plusieurs Mo, hooks PyInstaller) que **rien d'autre** dans le projet n'utilise | Si on adopte PyObjC ailleurs (autostart, presse-papiers…) et que la mutualisation justifie le poids. |

> Il n'existe **pas** de notification macOS haut niveau « le micro par défaut a changé » hors
> CoreAudio ; PyObjC et ctypes visent donc la même API native, au coût/robustesse près.

---

## 3. Comportement de reprise : **redémarrage à chaud immédiat** ✅ (tranché)

Dès la détection :
1. Fermer l'ancien flux `sounddevice`.
2. Rouvrir un flux sur le **nouveau** périphérique (préférence `micro_index` si elle redevient
   disponible, sinon défaut système).
3. **Préserver le buffer** déjà capté depuis la dernière tranche (pas de perte de l'audio en cours).
4. Coupure micro de ~200 ms (warm-up Core Audio) — l'audio système (SCK) n'est pas affecté.

---

## 4. Architecture proposée (à valider ensemble)

### 4.1 Nouveau composant `SurveillantPeripheriques(QObject)`

- **Emplacement :** `platform/commun/surveillant_peripheriques.py`.
- **Rôle :** encapsule `QMediaDevices`, émet un signal Qt cœur-friendly
  `entree_par_defaut_change = Signal()` après **anti-rebond** (voir 4.3).
- **Pourquoi un composant dédié** plutôt que dans l'orchestrateur : isole la dépendance
  QtMultimedia, testable en injectant un faux émetteur, réutilisable par les 3 modes.

### 4.2 Extension de l'interface `CaptureMicro`

Ajouter une méthode :

```python
def redemarrer(self, index_peripherique: int | None = None) -> None:
    """Reconnecte le flux sur un nouveau périphérique SANS vider le buffer.
    No-op par défaut (convention maison, cf. terminer())."""
```

- **Concrète no-op par défaut** dans l'ABC ✅ — cohérent avec `terminer()` déjà ainsi.
  Les stubs Windows/Linux n'ont rien à écrire tant qu'ils ne sont pas développés.
- Implémentée dans `CaptureMicroSounddevice` (ferme + rouvre, buffer conservé).
- Implémentée dans `MicroFake` (compteur d'appels pour les tests).

### 4.3 Câblage dans `OrchestrateurReunion`

- À `_demarrer()` : s'abonner à `surveillant.entree_par_defaut_change`.
- Au signal : si `_avec_micro`, appeler `self._micro.redemarrer(self._config.get("micro_index"))`
  sur le **thread principal Qt** (le signal arrive déjà sur la boucle Qt).
- À `_arreter()` : se désabonner.
- **Anti-rebond** : un retrait peut émettre plusieurs `audioInputsChanged` en rafale. Le
  surveillant temporise via un `QTimer` single-shot (~300 ms) avant d'émettre une fois. **Durée à valider.**

---

## 5. Décisions (actées) et points restants

| # | Sujet | Décision |
|---|---|---|
| 1 | **Périmètre des modes** | ✅ **Réunion uniquement** en v1 (Dictée/Journal trop courts). |
| 2 | **Préférence micro au retour** | ✅ **Rebasculer** sur la préférence si elle redevient disponible. |
| 3 | **Interface `redemarrer`** | ✅ **Concrète no-op par défaut** (convention maison, cf. `terminer()`). |
| 4 | **Phasage** | ✅ **Sous-phase 3.5 dédiée** « Robustesse audio macOS ». |
| 5 | **Anti-rebond** | 🟢 *Proposé : 300 ms.* À confirmer à l'implémentation. |
| 6 | **Warm-up à chaud** | 🟢 *Proposé : garder 200 ms* (simple, glitch jeté). |
| 7 | **Capture système (SCK)** | ✅ **Non concernée** (device-agnostic) — acté, aucune action. |

---

## 6. Tests prévus

- *Unitaire* — `OrchestrateurReunion` : émettre le signal du faux surveillant pendant une réunion
  active → vérifier que `micro.redemarrer()` est appelé avec le bon index.
- *Unitaire* — `CaptureMicroSounddevice.redemarrer()` : le buffer accumulé est **préservé**
  (pas remis à zéro comme dans `demarrer()`).
- *Unitaire* — anti-rebond : N signaux rapprochés → 1 seul `entree_par_defaut_change` émis.
- *Unitaire* — hors réunion (mode IDLE), le signal n'a aucun effet.
- *Intégration manuelle* — démarrer une réunion avec AirPods, les retirer, vérifier que le micro
  reprend sur le micro intégré et que les tranches suivantes contiennent bien « Moi ».

---

## 7. Étapes d'implémentation (séquencées)

1. [x] Trancher les points du §5 (anti-rebond 300 ms et warm-up 200 ms confirmés).
2. [x] `SurveillantPeripheriques` (`platform/commun/`) + tests anti-rebond (`test_surveillant.py`).
3. [x] `CaptureMicro.redemarrer` (interface no-op + sounddevice buffer-préservé + fake).
4. [x] Câblage `OrchestrateurReunion` (abonnement, rebascule préférence) + tests.
5. [x] Reporter §2 (décision + alternatives) dans `02-specifications-techniques.md` (§4.5bis).
6. [x] Ajouter la **Phase 3.5 « Robustesse audio macOS »** dans `03-phases-implementation.md`.
7. [x] `pytest -m "not integration"` vert (**163 passed**) + notice « Comment tester ». Validation manuelle : à jouer par l'utilisateur.
