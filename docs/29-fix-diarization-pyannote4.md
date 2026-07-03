# Fix Diarization — `TypeError: local_files_only` (pyannote 4.x) + erreurs lisibles

> **Statut : ✅ implémenté et validé (2026-07-02, 576 tests passent — 573 + 3 nouveaux).**
> Validation manuelle (§7) faite par l'utilisateur le 2026-07-02 — diarization fonctionne correctement en réel.
> Plan rédigé le 2026-07-02 (session de diagnostic, cause prouvée par les logs).
> Ce document est conçu pour être donné tel quel à une session IA d'implémentation (Sonnet).
> **Périmètre : 1 fix racine + 3 correctifs d'accompagnement + tests. Rien d'autre.**
> **Option A validée par l'utilisateur** (offline via `HF_HUB_OFFLINE`, pas via `local_files_only`).
> Avant livraison : `make test` (attendu : les 573 tests actuels + les nouveaux/modifiés, tous verts).

---

## 1. Contexte — le diagnostic du 2026-07-02

### 1.1 Symptôme

Depuis l'Historique, « Générer les locuteurs » (diarization) sur une réunion échoue
**systématiquement** avec la boîte de dialogue :

> La génération des locuteurs a échoué : Diarization : aucune piste exploitable (toutes en échec).

Reproduit sur plusieurs réunions, avec les deux pistes audio (`_moi.opus` + `_systeme.opus`)
bien présentes. Ce n'est **pas** un problème d'audio.

### 1.2 Cause racine (prouvée par le log)

`~/Library/Logs/debriefMeet/debriefMeet.log` :

```
Diarization piste systeme : ÉCHEC (Pipeline.from_pretrained() got an unexpected keyword argument 'local_files_only')
...
  File ".../core/diarization.py", line 163, in _charger
    pipeline = Pipeline.from_pretrained(PYANNOTE_PIPELINE, local_files_only=True)
TypeError: Pipeline.from_pretrained() got an unexpected keyword argument 'local_files_only'
```

- Version installée : **pyannote.audio 4.0.4** (`pyproject.toml` épingle `pyannote.audio>=4`).
- Signature réelle en 4.x :
  `from_pretrained(checkpoint, revision=None, hparams_file=None, token=None, cache_dir=None)`
  → **pas de `local_files_only`** (paramètre qui existait en pyannote **3.x**, supprimé en 4.x).
- Le code (`core/diarization.py:163`) l'appelle quand même → `TypeError` à **chaque**
  chargement du pipeline. Comme `_charger()` est invoqué dans la boucle par piste
  (`_traiter_piste`, ligne 275-277) dont chaque exception est avalée par le `try/except`
  par piste (lignes 300-304), les **deux** pistes tombent et le message final générique
  « toutes en échec » masque la vraie cause.

Portage 3.x→4.x incomplet : le code utilise déjà le **nom v4** du pipeline
(`pyannote/speaker-diarization-community-1`, ligne 26) mais l'**appel v3**. L'appel de
*téléchargement* (`_peupler_cache`, ligne 133 : `from_pretrained(..., token=token)`) est
correct — c'est pourquoi l'onboarding a pu peupler le cache (modèle bien présent, vérifié)
alors que le *chargement offline* plante.

### 1.3 Pourquoi les 573 tests passaient

`tests/test_diarization.py:358` (`test_charger_lit_le_cache_local_sans_token`) utilise un
faux pipeline `from_pretrained(repo, **kw)` qui **accepte n'importe quel kwargs** et
**assert que `local_files_only=True` est bien passé** (ligne 386). Le mock est plus
permissif que l'API réelle → le test **verrouillait le comportement bogué** au lieu de le
détecter. Correctif 3 ci-dessous.

### 1.4 ⚠️ Piège central de l'option A — `HF_HUB_OFFLINE` est figé à l'import

Le mode hors-ligne moderne de `huggingface_hub` (1.20.1 installé) passe par
`is_offline_mode()`, qui retourne la **constante** `huggingface_hub.constants.HF_HUB_OFFLINE`.
Cette constante est **évaluée une seule fois, à l'import** du module `constants`. Vérifié
le 2026-07-02 :

```python
os.environ["HF_HUB_OFFLINE"] = "1"        # APRÈS l'import de huggingface_hub
huggingface_hub.is_offline_mode()          # → False  (la constante reste figée !)

huggingface_hub.constants.HF_HUB_OFFLINE = True
huggingface_hub.is_offline_mode()          # → True   (c'est ÇA qu'il faut patcher)
```

`huggingface_hub` est déjà importé bien avant la diarization (moteur MLX, etc.) → poser la
**variable d'environnement** en cours d'exécution **ne fait rien**. Il faut **patcher la
constante** `huggingface_hub.constants.HF_HUB_OFFLINE` (et la restaurer). C'est le cœur du
Correctif 1.

---

## 2. Correctif 1 (fix racine) — chargement offline sans `local_files_only`

### Fichier
`src/debrief_meet/core/diarization.py`

### 2.1 Context manager de mode offline

Ajouter, au niveau module :

```python
import contextlib

@contextlib.contextmanager
def _mode_offline_hf():
    """Force huggingface_hub en mode hors-ligne le temps du bloc, puis restaure.

    Patche la CONSTANTE `huggingface_hub.constants.HF_HUB_OFFLINE` (lue par
    `is_offline_mode()`), pas la variable d'environnement : celle-ci est figée à
    l'import de huggingface_hub — déjà chargé ici — donc sans effet (cf. docs/29 §1.4).
    """
    from huggingface_hub import constants
    ancien = constants.HF_HUB_OFFLINE
    constants.HF_HUB_OFFLINE = True
    try:
        yield
    finally:
        constants.HF_HUB_OFFLINE = ancien
```

### 2.2 `_charger()` (lignes 157-174) — retirer `local_files_only`, envelopper

```python
def _charger(self):
    from pyannote.audio import Pipeline
    import torch

    # Modèle déjà téléchargé pendant l'onboarding → lecture du cache local, sans
    # token ni réseau. En pyannote 4.x, `local_files_only` n'existe plus (cf. docs/29) :
    # on force le hors-ligne via la constante HF_HUB_OFFLINE (patchée le temps de l'appel).
    with _mode_offline_hf():
        pipeline = Pipeline.from_pretrained(PYANNOTE_PIPELINE)
    if pipeline is None:
        raise ErreurDiarization(
            "pyannote indisponible : modèle non téléchargé "
            "(Préférences › Audio › Configurer la diarization…).")
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
    else:
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            pipeline.to(torch.device("mps"))
    return pipeline
```

Changements :
- Suppression de `local_files_only=True`.
- Ajout du `with _mode_offline_hf():` autour du seul `from_pretrained`.
- Le `raise RuntimeError(...)` d'origine devient `raise ErreurDiarization(...)` (déjà
  définie ligne 63, message destiné à l'utilisateur) — pour le Correctif 2.

Note : ne PAS toucher `_peupler_cache` (ligne 133) — le téléchargement doit rester en
ligne, avec token ; il est correct.

---

## 3. Correctif 2 — charger le pipeline une fois, erreur lisible

**But** : une incompatibilité de chargement (systématique, actionnable) ne doit plus être
déguisée en « toutes les pistes en échec ». On la fait remonter **avant** la boucle par
piste ; le `try/except` par piste reste réservé aux vraies erreurs propres à une piste
(audio corrompu, etc.).

### 3.1 `MoteurDiarization` (interface, ligne 31) — méthode `precharger`

```python
class MoteurDiarization:
    def diariser(self, audio_16k: np.ndarray) -> list[tuple[float, float, str]]:
        raise NotImplementedError

    def precharger(self) -> None:
        """Charge le modèle maintenant (échoue tôt et clairement). No-op par défaut."""
```

### 3.2 `DiarizationPyannote` — implémenter `precharger`

```python
def precharger(self) -> None:
    if self._pipeline is None:
        self._pipeline = self._charger()
```

(et `diariser` peut appeler `self.precharger()` au lieu de dupliquer le `if self._pipeline
is None`.)

### 3.3 `generer_locuteurs` (ligne 281) — précharger avant la boucle

Juste après le calcul de `pistes` et le garde `if all(p is None ...)`, avant la boucle :

```python
try:
    moteur_diarization.precharger()
except ErreurDiarization:
    raise                                  # message déjà destiné à l'utilisateur
except Exception as exc:
    raise ErreurDiarization(
        f"Chargement du modèle de diarization impossible : {exc}") from exc
```

Ainsi : modèle absent / pyannote incompatible → message clair et unique. Le
`RuntimeError("Diarization : aucune piste exploitable (toutes en échec).")` (ligne 307)
reste, mais n'est plus atteint que si le pipeline a chargé et que **chaque piste** échoue
pour une raison qui lui est propre — ce qui est alors un vrai diagnostic « piste » et non
« modèle ».

### 3.4 UI — vérifier que le message remonte tel quel

`ui/gestionnaire_diarization.py` affiche « La génération des locuteurs a échoué : {message} ».
`ErreurDiarization` étant une `Exception` standard, `str(exc)` donne le message voulu —
rien à changer, mais **vérifier** que le worker ne réécrit pas le message (il propage
`str(exc)` via le signal `erreur`).

---

## 4. Correctif 3 — corriger le test qui verrouillait le bug

### Fichier
`tests/test_diarization.py` (`test_charger_lit_le_cache_local_sans_token`, ligne 358)

Le faux pipeline doit refléter l'API pyannote 4.x (**pas** de `local_files_only`), et le
test doit vérifier le **nouveau** contrat : offline actif pendant l'appel, plus de token,
plus de `local_files_only`.

```python
def test_charger_force_offline_sans_token(monkeypatch):
    """_charger() lit le cache local en forçant HF_HUB_OFFLINE, sans token ni
    `local_files_only` (supprimé en pyannote 4.x — cf. docs/29)."""
    import sys, types
    from huggingface_hub import constants

    appels = {}

    class _FakePipeline:
        @staticmethod
        def from_pretrained(repo, **kw):
            appels["repo"], appels["kw"] = repo, kw
            # Capture l'état offline AU MOMENT de l'appel (doit être True).
            appels["offline_pendant_appel"] = constants.HF_HUB_OFFLINE
            return object()

    faux_audio = types.ModuleType("pyannote.audio"); faux_audio.Pipeline = _FakePipeline
    faux_pyannote = types.ModuleType("pyannote"); faux_pyannote.audio = faux_audio
    faux_torch = types.ModuleType("torch")
    faux_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    faux_torch.backends = types.SimpleNamespace(mps=None)
    faux_torch.device = lambda x: x
    monkeypatch.setitem(sys.modules, "pyannote", faux_pyannote)
    monkeypatch.setitem(sys.modules, "pyannote.audio", faux_audio)
    monkeypatch.setitem(sys.modules, "torch", faux_torch)
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", False)   # état de départ réaliste

    pipe = diar.DiarizationPyannote()._charger()

    assert pipe is not None
    assert "local_files_only" not in appels["kw"]            # supprimé en v4
    assert "token" not in appels["kw"]                        # plus de token au chargement
    assert appels["offline_pendant_appel"] is True            # offline forcé pendant l'appel
    assert constants.HF_HUB_OFFLINE is False                  # restauré après le bloc
```

Ajouter deux tests ciblés :

- **`precharger` propage une `ErreurDiarization` claire** : un `DiarizationPyannote` dont
  `_charger` lève `ErreurDiarization(...)` → `precharger()` propage ; via
  `generer_locuteurs`, le message remonté est celui de l'erreur (pas « toutes en échec »).
  (Utiliser un moteur fake ou monkeypatcher `_charger`.)
- **`_mode_offline_hf` restaure** même si le bloc lève : entrer avec la constante à False,
  lever dans le `with`, vérifier qu'elle est revenue à False.

Ces tests n'ont **pas** besoin de pyannote réel (tout est mocké) → restent dans la suite
`not integration`.

---

## 5. Correctif 4 — resserrer l'épinglage pyannote

### Fichier
`pyproject.toml` (ligne 22)

`pyannote.audio>=4` a laissé passer une rupture d'API mineure. Resserrer sur la série
testée, ex. `pyannote.audio>=4,<5` (au minimum), et **documenter** dans le doc de
diarization que l'API `from_pretrained` a changé entre 3.x et 4.x. Vérifier au passage que
le bundle portable Windows (`assembler_bundle.py`, mentionné ligne 36 du pyproject) embarque
bien une version cohérente — hors périmètre code, simple note pour la Phase 5.

---

## 6. Hors périmètre (assumé)

- Ne pas retoucher l'onboarding (`telecharger`, `_verifier_acces`, `_peupler_cache`) : le
  chemin en ligne avec token fonctionne.
- Ne pas changer le nom du pipeline ni la logique d'attribution/fusion des tours.
- La lenteur éventuelle du premier chargement (torch + modèle) n'est pas traitée ici.

---

## 7. Validation manuelle (après `make test`)

Le modèle `community-1` est **déjà dans le cache** de la machine de dev (vérifié) — la
diarization doit fonctionner immédiatement après le fix, sans re-téléchargement.

1. `make run` → Historique → une réunion avec les 2 pistes audio → « Générer les
   locuteurs » → un fichier `<stem>_locuteurs.md` est produit, sans erreur. Vérifier les
   étiquettes (Moi / Présent / Distant).
2. Couper le réseau (Wi-Fi off) et refaire (1) → doit **toujours** marcher (offline réel).
3. Cas d'erreur lisible : renommer temporairement le dossier cache
   `~/.cache/huggingface/hub/models--pyannote--speaker-diarization-community-1` → « Générer
   les locuteurs » → message clair « modèle non téléchargé (Préférences › … Configurer la
   diarization) », **pas** « aucune piste exploitable ». Restaurer le dossier ensuite.
4. Log : plus aucun `TypeError: ... local_files_only`.

---

## 8. Clôture

- `CLAUDE.md` : tableau « Docs de référence » (+ docs/29), « Suite attendue » (nouveau
  compte de tests).
- `docs/07-diarization.md` : noter le changement d'API pyannote 3.x→4.x (plus de
  `local_files_only`, offline via `HF_HUB_OFFLINE`) et le renvoi vers docs/29.
- Mettre à jour l'état de la Phase D dans `docs/03` si un statut « diarization
  fonctionnelle en réel » y est suivi.
