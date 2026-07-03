# Raccourcis clavier globaux — dictée / réunion / journal, paramétrables

> **Statut : ✅ implémenté et validé (2026-07-02, 573 tests passent — 556 + 17 nouveaux).**
> Validation manuelle (§7) faite par l'utilisateur le 2026-07-02 — raccourcis et paramétrage dans les Préférences OK.
> Plan initial rédigé le 2026-07-02.
> Ce document est conçu pour être donné tel quel à une session IA d'implémentation (Sonnet).
> **Périmètre : macOS uniquement (adaptateur natif) + stubs autres OS + UI préférences + tests.**
> Avant livraison : `make test` (attendu : les 556 tests actuels + les nouveaux, tous verts).

---

## 1. Contexte — l'architecture attend déjà cette évolution

- L'interface **`RaccourcisGlobaux` est déjà déclarée** (`platform/interfaces.py:150-157`)
  avec `enregistrer(combinaison, callback)` et `desactiver_tous()` — prévue « post-v1 »
  par les specs ([`01-specifications-fonctionnelles.md`](01-specifications-fonctionnelles.md)
  §10.4 et §11 « Plus tard — gestion intégrée »). Ce doc EST cette évolution.
- Les points d'entrée existent : `MachineEtats.toggle_dictee/toggle_reunion/toggle_journal`
  (`core/modes.py:57-63`) — même sémantique bascule (démarre/arrête) que le tray et l'IPC.
  Un toggle refusé (autre mode en cours) est déjà géré par la machine : rien à ajouter.
- La voie v1 (app Raccourcis macOS → CLI `--toggle` via IPC) reste fonctionnelle et
  n'est pas touchée.

## 2. Choix technique macOS : `RegisterEventHotKey` (Carbon), via ctypes

| Option | Verdict |
|---|---|
| **`RegisterEventHotKey` (Carbon/HIToolbox)** | ✅ retenu — **aucune permission TCC** (crucial : la Phase 4 packaging repose sur des permissions stables, ne pas en ajouter), consomme la touche (pas de double frappe dans l'app au premier plan), API stable utilisée par la plupart des apps menubar, accessible en pur ctypes sans dépendance |
| `CGEventTap` / `NSEvent.addGlobalMonitor` (PyObjC) | ❌ exigent la permission **Accessibilité** (TCC) — friction utilisateur + risque de perte de permission à chaque rebuild (cf. docs/16) |
| Libs tierces (`pynput`, `keyboard`) | ❌ mêmes permissions TCC + dépendance de plus |

La couche `core/` ne voit que l'interface `RaccourcisGlobaux` (règle d'or respectée) ;
tout le ctypes vit dans `platform/macos/`.

### 2.1 ⚠️ Piège n°1 — le mapping des modificateurs Qt ↔ macOS

Qt **échange** Ctrl et Cmd sur macOS : dans une `QKeySequence` portable,
`Ctrl` = touche **⌘ Commande**, et `Meta` = touche **⌃ Contrôle**. Table de conversion
Qt → Carbon à implémenter dans l'adaptateur :

| Qt (portable) | Touche macOS | Constante Carbon |
|---|---|---|
| `Ctrl` (`ControlModifier`) | ⌘ Commande | `cmdKey = 0x0100` |
| `Meta` (`MetaModifier`) | ⌃ Contrôle | `controlKey = 0x1000` |
| `Alt` (`AltModifier`) | ⌥ Option | `optionKey = 0x0800` |
| `Shift` (`ShiftModifier`) | ⇧ Majuscule | `shiftKey = 0x0200` |

La config stocke le format **portable** (`QKeySequence.toString()`), l'UI affiche le
format **natif** (`NativeText` → « ⌃⌥⌘D »). Ne jamais stocker le natif.

### 2.2 ⚠️ Piège n°2 — clavier AZERTY : caractère ≠ keycode

`RegisterEventHotKey` prend un **keycode physique** (kVK_ANSI_*, positions QWERTY),
mais l'utilisateur choisit un **caractère**. Le Mac de l'utilisateur est en
**AZERTY** (vérifié le 2026-07-02 : layout « ABC-AZERTY ») : les lettres A/Q, Z/W et M
n'ont pas le même keycode qu'en QWERTY. Conversion caractère → keycode **selon le
layout courant** :

1. `TISCopyCurrentKeyboardLayoutInputSource()` →
   `TISGetInputSourceProperty(source, kTISPropertyUnicodeKeyLayoutData)` (CFDataRef) ;
2. pour `keycode` de 0 à 127 : `UCKeyTranslate(layout, keycode, kUCKeyActionDisplay,
   0, LMGetKbdType(), kUCKeyTranslateNoDeadKeysBit, …)` → caractère de base ;
3. premier keycode dont le caractère (minuscule) correspond → gagné.

Frameworks : Carbon (HIToolbox) pour TIS*/UCKeyTranslate — tout en ctypes,
`ctypes.util.find_library("Carbon")`.

**Repli** : si cette résolution échoue (exception ctypes, caractère introuvable),
utiliser une table fixe `kVK_ANSI_*` (lettres/chiffres/F1-F12 — table standard de
`Events.h`, ex. D=0x02, R=0x0F, J=0x26) avec un `logger.warning`. Les défauts D/R/J
sont aux **mêmes positions** en AZERTY et QWERTY → les défauts marchent même en repli.
Limitation assumée : un changement de layout **pendant** que l'app tourne n'est pas
détecté (les raccourcis sont réenregistrés au prochain démarrage ou passage dans les
Préférences).

## 3. Raccourcis par défaut — vérifiés libres sur le Mac cible

La famille **⌃⌥⌘ (Contrôle+Option+Commande)** est le namespace conventionnellement
laissé libre par macOS. Vérifié sur le Mac de l'utilisateur le 2026-07-02 :

- 34 raccourcis système actifs (`com.apple.symbolichotkeys`) — **aucun** n'utilise ⌃⌥⌘ ;
- aucune surcharge par app (`NSUserKeyEquivalents` vide) ;
- aucun utilitaire de raccourcis installé (pas d'Alfred/Raycast/Rectangle/Karabiner…).

| Action | Raccourci | Mnémonique | Config (format portable Qt) |
|---|---|---|---|
| Dictée (démarrer/arrêter) | **⌃⌥⌘D** | **D**ictée | `"Meta+Alt+Ctrl+D"` |
| Réunion (démarrer/arrêter) | **⌃⌥⌘R** | **R**éunion | `"Meta+Alt+Ctrl+R"` |
| Journal (démarrer/arrêter) | **⌃⌥⌘J** | **J**ournal | `"Meta+Alt+Ctrl+J"` |

(D, R et J sont aux mêmes positions physiques en AZERTY et QWERTY — aucun piège layout
sur les défauts. Rappel §2.1 : dans le format portable Qt, `Meta`=⌃ et `Ctrl`=⌘.)

---

## 4. Implémentation

### 4.1 `platform/interfaces.py` — préciser le contrat

```python
class RaccourcisGlobaux(ABC):
    """Raccourcis clavier système (capturés même quand l'app n'a pas le focus)."""

    @abstractmethod
    def enregistrer(self, combinaison: str, callback: Callable[[], None]) -> bool:
        """Enregistre `combinaison` (format portable QKeySequence, ex. "Meta+Alt+Ctrl+D").
        False si l'enregistrement échoue (combinaison déjà prise par une autre app,
        conversion impossible). Le callback est invoqué sur le thread principal Qt."""

    @abstractmethod
    def desactiver_tous(self) -> None: ...
```

(Seul changement de contrat : le retour `bool` — la déclaration actuelle renvoie None.)

### 4.2 `platform/macos/raccourcis_carbon.py` (nouveau) — adaptateur natif

Classe `RaccourcisGlobauxMacOS(RaccourcisGlobaux)`, pur ctypes sur Carbon.framework :

- **Constantes** : `cmdKey/optionKey/controlKey/shiftKey` (§2.1) ;
  `kEventClassKeyboard = 0x6B657962` (`'keyb'`), `kEventHotKeyPressed = 5`,
  `kEventParamDirectObject = 0x2D2D2D2D` (`'----'`), `typeEventHotKeyID = 0x686B6964`
  (`'hkid'`), signature applicative libre ex. `0x64627266` (`'dbrf'`).
- **Structures** : `EventTypeSpec(eventClass: UInt32, eventKind: UInt32)`,
  `EventHotKeyID(signature: UInt32, id: UInt32)`.
- **`__init__`** : installe UNE fois le handler d'événements —
  `InstallEventHandler(GetApplicationEventTarget(), handler, 1, byref(spec), None, None)`
  où `handler` est un `CFUNCTYPE(OSStatus, c_void_p, c_void_p, c_void_p)` qui fait
  `GetEventParameter(event, kEventParamDirectObject, typeEventHotKeyID, None,
  sizeof(EventHotKeyID), None, byref(hkid))` puis appelle le callback associé à
  `hkid.id` et retourne 0 (`noErr`).
- **`enregistrer`** : parse la `QKeySequence` (modificateurs → Carbon §2.1, caractère →
  keycode §2.2), `RegisterEventHotKey(keycode, mods, hotkey_id,
  GetApplicationEventTarget(), 0, byref(ref))` ; statut ≠ 0 → `logger.warning` +
  `return False` (c'est le cas « déjà pris par une autre app »). Stocke
  `{id: (ref, callback)}`.
- **`desactiver_tous`** : `UnregisterEventHotKey(ref)` pour chaque, vide le dict.
- ⚠️ **Pièges ctypes** : garder des **références Python** sur le `CFUNCTYPE` du handler
  et sur les `EventHotKeyID` (sinon GC → crash) ; le handler Carbon est invoqué par la
  boucle d'événements principale (celle de Qt/Cocoa) → les callbacks touchent la
  `MachineEtats` **sans** précaution de thread ; ne jamais lever depuis le handler
  (try/except + `logger.exception`, retourner 0).
- Les fonctions de conversion (`_mods_qt_vers_carbon(seq) -> int`,
  `_keycode_pour_caractere(char) -> int | None`, table de repli) sont des **fonctions
  module pures** → testables sans Carbon.

### 4.3 `platform/stubs.py` + `platform/factory.py` — câblage

- `RaccourcisStub(RaccourcisGlobaux)` : `enregistrer` → mémorise et retourne True,
  `desactiver_tous` → vide (les tests s'appuient dessus).
- `Adaptateurs` : nouveau champ `raccourcis: RaccourcisGlobaux`.
- `_macos()` : `RaccourcisGlobauxMacOS()` avec try/except → `RaccourcisStub()` en repli
  (comme les autres adaptateurs) ; `_windows()`/`_linux()` : `RaccourcisStub()`.

### 4.4 `core/raccourcis.py` (nouveau) — application de la config

```python
ACTIONS = (          # (clé config, valeur par défaut, nom de l'action pour messages)
    ("raccourci_dictee",  "Meta+Alt+Ctrl+D", "Dictée"),
    ("raccourci_reunion", "Meta+Alt+Ctrl+R", "Réunion"),
    ("raccourci_journal", "Meta+Alt+Ctrl+J", "Journal"),
)

def appliquer_raccourcis(raccourcis: RaccourcisGlobaux, config: Config,
                         machine: MachineEtats) -> list[str]:
    """(Ré)enregistre les 3 raccourcis depuis la config. Retourne la liste des
    combinaisons en échec (déjà prises / invalides) — vide si tout est passé.
    Une combinaison vide en config ("") = raccourci désactivé, pas une erreur."""
```

Corps : `desactiver_tous()` puis, pour chaque action non vide,
`enregistrer(combo, machine.toggle_xxx)` ; collecter les échecs, les logger en WARNING.
Idempotente → sert au démarrage ET à la sauvegarde des Préférences.

- `core/config.py` : 3 nouvelles clés avec les défauts du §3.
- `__main__.py` : après la création du tray, `echecs = appliquer_raccourcis(…)` ;
  si échecs, `logger.warning` (pas de dialogue au démarrage). Ajouter
  `app.aboutToQuit.connect(adaptateurs.raccourcis.desactiver_tous)` (avant l'arrêt des
  orchestrateurs dans la liste des connexions existantes, lignes ~217-223).

### 4.5 `ui/preferences.py` — section « Raccourcis »

- 3 lignes de formulaire avec **`QKeySequenceEdit`** (widget Qt standard : capture la
  frappe, affiche le format natif ⌃⌥⌘D) + un bouton « Réinitialiser les défauts ».
  Charger depuis la config (`QKeySequence.fromString(config.get(cle))`).
- **Validation à la sauvegarde** (avant `config.set`) :
  1. limiter à **une seule combinaison** (`QKeySequenceEdit.setMaximumSequenceLength(1)`,
     Qt ≥ 6.5) ;
  2. exiger **au moins un modificateur** parmi ⌘/⌃/⌥ (une lettre nue ou Shift+lettre
     capturée globalement rendrait le clavier inutilisable) → message et refus ;
  3. refuser les **doublons** entre les 3 champs ;
  4. champ vide = raccourci désactivé (autorisé).
- **Application à chaud** : les Préférences reçoivent un callable
  `reappliquer_raccourcis: Callable[[], list[str]]` (construit dans `__main__` par
  `functools.partial(appliquer_raccourcis, adaptateurs.raccourcis, config, machine)`,
  transmis via `IconeTray` → `FenetrePreferences`, même chemin que `moteur`). Après la
  sauvegarde : l'appeler ; si échecs → `QMessageBox.warning` listant les combinaisons
  refusées (« déjà utilisée par une autre application ») — les autres restent actives.
- Cohérence avec docs/27 : cette section s'ajoute au même dialogue que la case
  « logs debug » ; pas d'interaction.

### 4.6 `ui/tray.py` — affichage des raccourcis dans le menu (finition)

Sur les 3 QAction existantes (`tray.py:65-75`) :
`action.setShortcut(QKeySequence.fromString(config.get(cle)))` — le menu tray affiche
alors le glyphe (⌃⌥⌘D) à côté de « Démarrer Dictée ». Purement décoratif (la capture
réelle est faite par Carbon). Rafraîchir ces hints dans le callable de réapplication ou
via un petit slot du tray appelé au même moment.

---

## 5. Hors périmètre (assumé)

- **Windows** (Phase 5) : `RegisterHotKey` (user32) + `QAbstractNativeEventFilter` pour
  capter `WM_HOTKEY` — l'interface et `core/raccourcis.py` sont déjà prêts, seul
  l'adaptateur manquera. À noter dans docs/18/spike produit.
- **Linux** : X11 possible (XGrabKey), **Wayland impossible proprement** → rester sur
  les outils de l'OS (voie v1, docs/01 §11).
- Détection de conflits **inter-applications** au-delà de l'échec d'enregistrement
  (macOS ne fournit pas d'inventaire des hotkeys tiers).
- Réenregistrement automatique au **changement de layout clavier à chaud** (§2.2).
- Raccourci pour d'autres actions (Historique, Préférences…) — extensible plus tard via
  `ACTIONS`.

---

## 6. Tests (pytest, sans matériel — `make test`)

### `tests/test_raccourcis.py` (nouveau)

1. `appliquer_raccourcis` avec un `RaccourcisStub` : les 3 combinaisons de la config
   sont enregistrées, les callbacks sont bien `machine.toggle_dictee/reunion/journal`
   (les invoquer → le mode de la machine change).
2. Réapplication : `desactiver_tous` appelé avant réenregistrement (pas de doublon).
3. Combinaison vide en config → non enregistrée, pas d'échec retourné.
4. Stub qui refuse une combinaison → elle est dans la liste d'échecs, les 2 autres
   sont actives.

### `tests/test_raccourcis_carbon.py` (nouveau — fonctions pures uniquement)

5. `_mods_qt_vers_carbon` : `"Meta+Alt+Ctrl+D"` → `controlKey|optionKey|cmdKey`
   (le piège §2.1 : Qt-Ctrl→cmdKey, Qt-Meta→controlKey).
6. Table de repli : D→0x02, R→0x0F, J→0x26.
7. La résolution AZERTY (`UCKeyTranslate`) : test marqué **`integration`** (dépend du
   layout de la machine) — sur ce Mac AZERTY : « a » → keycode 0x0C (position Q).

### `tests/test_preferences.py`

8. Validation : doublon entre 2 champs → refus ; combinaison sans modificateur → refus ;
   champ vide → accepté et sauvé `""`.
9. Sauvegarde → `reappliquer_raccourcis` appelé ; s'il retourne des échecs → un
   `QMessageBox.warning` est montré (monkeypatcher).

### Non-régression

- `tests/test_modes.py` et le câblage IPC ne bougent pas (mêmes `toggle_*`).
- La construction `Adaptateurs` dans les fakes de tests (`tests/fakes/adapters.py`,
  `conftest.py`) doit recevoir le nouveau champ `raccourcis` — adapter les fixtures.

---

## 7. Validation manuelle (macOS, après `make test`)

1. `make run`, aller dans **une autre app** (éditeur au premier plan) : **⌃⌥⌘D** →
   l'icône passe en enregistrement ; parler ; **⌃⌥⌘D** → le texte est dans le
   presse-papier. La lettre « d » n'est PAS tapée dans l'éditeur (la touche est consommée).
2. Même chose **⌃⌥⌘R** (réunion, `.md` produit) et **⌃⌥⌘J** (journal, entrée écrite).
3. Préférences → changer Dictée en ⌃⌥⌘F → sans redémarrer, ⌃⌥⌘F marche, ⌃⌥⌘D est libéré.
4. Mettre deux fois le même raccourci → refus à la sauvegarde avec message.
5. Vider le champ Journal → sauvegarde OK, ⌃⌥⌘J ne fait plus rien.
6. Raccourci déjà pris : enregistrer ⌃⌥⌘D dans l'app Raccourcis de macOS, relancer
   debriefMeet → warning loggé, les 2 autres raccourcis actifs.
7. Menu tray : les glyphes ⌃⌥⌘D/R/J apparaissent à côté des actions.
8. Quitter/relancer l'app deux fois → pas de doublon d'enregistrement (Carbon refuse
   silencieusement sinon).
9. **À rejouer depuis l'app packagée** lors de la validation Phase 4 (docs/16 §6) —
   ajouter une ligne à sa checklist : raccourcis fonctionnels depuis le bundle.

---

## 8. Clôture

- `CLAUDE.md` : tableau « Docs de référence » (+ docs/28), « Suite attendue » (nouveau
  compte de tests).
- `docs/01-specifications-fonctionnelles.md` §10.4 et §11 : noter que la « gestion
  intégrée » est implémentée sur macOS (renvoi docs/28), la voie outils-OS restant le
  chemin Windows/Linux.
- `docs/03-phases-implementation.md` : rayer « Raccourcis globaux natifs » de la
  roadmap post-v1 (fait pour macOS, renvoi docs/28).
- `docs/16-packaging-macos.md` §6 : ajouter l'étape de validation n°9 ci-dessus.
