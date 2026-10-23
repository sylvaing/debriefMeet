# 53 — Mise à jour automatique (vérification, notification, installation)

> Décidé et implémenté le 2026-10-23, à la suite de l'incident eMudhra/emSign du
> 2026-10-20 (annonce python.org). Premier build concerné : **0.4.0**, qui est la
> dernière réinstallation manuelle.

## 1. Pourquoi

L'incident emSign a montré qu'un correctif de sécurité n'atteint les utilisateurs que
par une réinstallation manuelle : l'app vérifie TLS sur le bundle `certifi`
**embarqué** par PyInstaller (jamais sur le magasin système), et les postes tournaient
`f77f407` (2026-09-08). Sans auto-update, un poste reste exposé jusqu'à ce que quelqu'un
pense à réinstaller.

Deux décisions d'arrière-plan conditionnent la conception :

- **Le dépôt GitHub passe en public** : la Release devient le canal de distribution,
  lisible sans token. Mais le risque principal change de nature — un compte GitHub
  compromis pourrait pousser un installeur malveillant à tous les postes d'un coup.
  D'où le **manifeste signé** (§3) : la confiance repose sur une clé que nous
  détenons, pas sur GitHub.
- **Pas d'auto-update en v1 depuis le début** (docs/16) : on n'en fait pas une usine.
  Périmètre v1 = *vérifier, prévenir, télécharger sur clic, passer la main à
  l'installeur*. Jamais de remplacement silencieux, jamais de téléchargement sans clic.

## 2. Décisions (Sylvain, 2026-10-23)

| # | Décision | Raison |
|---|----------|--------|
| 1 | Manifeste `manifest.json` **signé ed25519**, clé privée en secret CI, clé publique embarquée | dépôt public, cf. §1 |
| 2 | macOS : la CI publie un **zip de l'app** en plus du DMG | un zip se dézippe et se déplace ; un DMG se monte |
| 3 | Linux : **manuel** (notification + page de release) | installer un `.deb` demande root ; `pkexec` reporté |
| 4 | **Bump à 0.4.0**, un numéro par release ensuite | tout était en 0.3.0 depuis juillet, seule la partie `+date.hash` changeait — un comparateur de versions a besoin d'un vrai numéro |
| 5 | Notification **tray** ET **badge** à côté du numéro de version ; un clic lance la procédure de l'OS | demande explicite |
| 6 | Vérification **30 s après le lancement**, puis **toutes les 24 h** ; bouton « Vérifier maintenant » ; résultat mémorisé en config ; installation refusée pendant un enregistrement ou un job ; opt-out coché par défaut | l'app vit dans le tray et n'est presque jamais relancée : le timer est le chemin principal |

## 3. Chaîne de publication (CI, `build.yml`)

```
tag v0.4.0 ──► version ──► windows / linux / macos ──► release
                                                        │ checkout + pip install cryptography
                                                        │ packaging/publier_manifeste.sh :
                                                        │   assets renommés SANS +date.hash
                                                        │   generer_manifeste.py generer → manifest.json
                                                        │   generer_manifeste.py signer  → manifest.sig (secret MAJ_CLE_PRIVEE_PEM)
                                                        │   generer_manifeste.py verifier (clé publique EMBARQUÉE, même fonction que l'app)
                                                        └ softprops/action-gh-release : .exe .deb .dmg .zip manifest.json manifest.sig
```

- **Noms publics** : `debriefMeet-setup-0.4.0.exe`, `debriefmeet_0.4.0_amd64.deb`,
  `debriefMeet-0.4.0.dmg`, `debriefMeet-0.4.0.zip`. Le `+<date>.<hash>` reste à
  l'intérieur des binaires (`VERSION_COMPLETE`, logs, `--version`) mais sort du nom
  de fichier : l'app ne peut pas deviner le hash, et `+` dans un nom d'asset GitHub
  n'est pas documenté.
- **Manifeste** (JSON déterministe, `sort_keys`, `\n` final) :
  ```json
  {"version": "0.4.0", "tag": "v0.4.0", "date": "2026-10-23",
   "notes_url": "https://github.com/sylvaing/debriefMeet/releases/tag/v0.4.0",
   "fichiers": {"windows": {"nom": "…exe", "url": "https://github.com/…/releases/download/v0.4.0/…exe",
                            "sha256": "…", "taille": 167580560}, "macos": {…zip…}, "linux": {…deb…}}}
  ```
  Les URL des binaires sont **absolues et figées sur le tag**, jamais
  `latest/download` : un manifeste reste cohérent avec ses propres binaires.
- **Signature** : ed25519 sur les **octets exacts** de `manifest.json`, base64 sur une
  ligne dans `manifest.sig`. L'app vérifie sur les octets bruts **avant** tout
  `json.loads`. La CI vérifie avec `debrief_meet.core.mise_a_jour.verifier_signature`
  et la constante `CLE_PUBLIQUE_PEM` du code : si le secret ne correspond pas à la clé
  embarquée, **la release échoue, jamais les postes**.
- **Ordre des uploads** : `files:` en noms exacts (plus de globs,
  `fail_on_unmatched_files: true` refuse une release incomplète), `manifest.*` en
  **dernier** — un poste qui lit `latest/download/manifest.json` pendant la publication
  ne peut pas tomber sur un manifeste dont les binaires ne sont pas encore en ligne.
- **`releases/latest/download/`** : dépôt public, sans token ni quota (c'est le site,
  pas l'API). Sémantique GitHub : *dernière release non-prerelease, non-draft, triée
  par `created_at`*, et `created_at` est **la date du commit taggé**. Conséquence :
  ne jamais tagger une release sur un commit antérieur à la précédente.
- **Prerelease** : un tag `v0.4.0-rc1` est accepté par le garde-fou `version` et produit
  une release `prerelease: true`, ignorée par `latest` (aucun poste ne la voit), testable
  en pointant l'app dessus via `DEBRIEFMEET_MAJ_URL` (§6). Nettoyage :
  `gh release delete v0.4.0-rc1 --cleanup-tag --yes`.
- **Dispatch** : le job `manifeste` (dispatch seulement) rejoue toute la chaîne sauf
  l'upload et dépose `manifest.json`/`manifest.sig` en artefact.

## 4. Clés et secret (une fois, à la main)

```bash
openssl genpkey -algorithm ed25519 -out ~/.debriefmeet/maj_cle_privee.pem
chmod 600 ~/.debriefmeet/maj_cle_privee.pem
openssl pkey -in ~/.debriefmeet/maj_cle_privee.pem -pubout      # → CLE_PUBLIQUE_PEM dans core/mise_a_jour.py
gh secret set MAJ_CLE_PRIVEE_PEM < ~/.debriefmeet/maj_cle_privee.pem
```

La clé privée ne vit **que** dans ce fichier (hors dépôt) et dans le secret CI ; le
script `signer` la lit en variable d'environnement, jamais sur disque du runner. Sans
le secret, le job `release` échoue explicitement (`::error::`). Changer de clé =
nouvelle constante dans le code **et** nouveau secret, livrés ensemble : un poste à
l'ancienne clé ignorerait tout manifeste signé par la nouvelle (il faut alors une
dernière réinstallation manuelle, comme pour 0.4.0).

## 5. Côté app

### 5.1 Modules

- `core/mise_a_jour.py` — **pur** (stdlib + `cryptography` au niveau module ; `httpx` et
  `platformdirs` importés dans les fonctions, pour que le job `release` puisse
  l'importer avec `pip install cryptography` seul). Manifeste, signature, comparaison
  PEP 440 (`packaging.version`), `ClientMaj` (téléchargement en `.part`, SHA256 +
  taille au fil de l'eau), et le **passage de main** (§5.3).
- `core/verificateur_maj.py` — `VerificateurMaj(QObject)`, gestionnaire persistant sur
  le modèle de `SynchroCalendrier` : timers, workers QThread, mémoire en config,
  signaux `maj_disponible` (une fois par version), `verification_terminee/echouee`,
  `telechargement_progresse/termine/echoue`.
- `ui/maj_actions.py` — câblage badge/tray/dialogues et `gerer_clic_maj`.
- Config : `maj_verifier_auto` (True), `maj_derniere_verification` (ISO UTC),
  `maj_version_disponible`, `maj_notes_url`. Clés nouvelles ⇒ pas de migration.

### 5.2 Quand et comment on vérifie

- `demarrer()` : `singleShot(30 s, tick)` + timer horaire. `tick()` relit la config
  (pas de signal sur `Config`) et ne vérifie que si `maj_verifier_auto` et dernière
  vérification > 24 h. Un échec réseau = une ligne WARNING, jamais une popup.
- Résultat mémorisé : le badge est posé **dès le lancement suivant, même hors ligne** ;
  `maj_disponible` (donc la notification tray) n'est émis qu'**une fois par version**.
  Au lancement, une version mémorisée qui n'est plus « plus récente » (on vient d'être
  mis à jour) est effacée.
- Tray : jamais pendant un enregistrement — différée au retour en `IDLE`. Gardée par
  la case « Activer les notifications ». Le clic ouvre la fenêtre principale.
- Préférences › Général › Mises à jour : opt-out + « Vérifier maintenant » (label à
  3 états : à jour / version X disponible / échec).

### 5.3 Le clic sur le badge, par OS

1. Badge périmé ⇒ retiré. Enregistrement ou job en cours ⇒ dialogue « reportée », rien
   d'autre (on ne ferme jamais l'app sous un travail).
2. `installation_possible()` faux ⇒ page de release dans le navigateur (**Linux**,
   exécution depuis les sources, ou **macOS avec `/Applications` non inscriptible** —
   `root:admin 775`, un non-admin ne peut pas y renommer : on ne tente rien en silence).
3. Dialogue « Installer la version X ? » → « Installer et redémarrer ».
4. Téléchargement en fond (badge = jauge), SHA256 vérifié, `mise_a_jour.demander(fichier)`,
   puis `app.quit()`.
5. **Après le retour de `app.exec()`** (même règle que `core/redemarrage.py` : mutex
   Windows et QLocalServer IPC vivent jusqu'à la mort du process), `appliquer()` :
   - **Windows** : un `.cmd` écrit dans le cache attend la mort du PID
     (`tasklist /FO CSV` + `findstr "debriefMeet.exe","<pid>"`, ~1 s par tour, borne 120)
     puis `start "" setup.exe /SILENT /AUTOUPDATE=1 /LOG=…`. Le contrôle `AppMutex`
     d'Inno a lieu **avant** `[Code]` : attendre côté app est la seule méthode sûre.
     `/SILENT` et non `/VERYSILENT` (la copie dure 10-40 s, l'utilisateur doit voir
     qu'il se passe quelque chose) ; pas de `/SUPPRESSMSGBOXES` (la boîte « en cours
     d'exécution » reste un filet interactif). `cwd` hors de `{app}` (sinon
     `[InstallDelete]` échoue), environnement sans `_PYI_*`. Le `.iss` relance l'app
     via une entrée `[Run]` conditionnée par `EstMiseAJourAuto` (`WizardSilent` +
     `/AUTOUPDATE=1`), et `SetupMutex` empêche deux setups simultanés. Pas de
     Mark-of-the-Web sur un fichier écrit par httpx ⇒ pas d'écran SmartScreen.
   - **macOS** : un `/bin/sh` détaché attend `kill -0 <pid>`, `ditto -x -k` dans un
     dossier **frère caché** du bundle (même volume ⇒ les deux `mv` sont des
     `rename(2)`), `codesign --verify --deep --strict` avant l'échange, `mv` ancien →
     tmp puis `mv` nouveau → `/Applications/debriefMeet.app` avec **retour arrière** si
     le second échoue, puis `open <chemin>` (jamais `open -a`, qui peut résoudre une
     copie périmée). Aucun `xattr` : le zip téléchargé par httpx n'a pas de quarantaine
     ⇒ pas d'écran Gatekeeper, et le bundle signé n'est pas touché. TCC conservé :
     même `CFBundleIdentifier` et même identité « debriefMeet Local » (docs/16 §6).
     Journal dans `~/Library/Caches/debriefMeet/mises_a_jour/installation.log`.

## 6. Tester

- **Unitaire** : `tests/test_mise_a_jour.py` (66, dont un test `integration` darwin qui
  exécute réellement le script de remplacement sur une fausse `.app`),
  `test_generer_manifeste.py`, `test_verificateur_maj.py`, `test_maj_ui.py`,
  `test_build.py` (`.iss`, `build_dmg.sh`, `build.yml`, exécution réelle de
  `publier_manifeste.sh` avec une paire éphémère).
- **Local, sans GitHub** : `DEBRIEFMEET_MAJ_URL=http://localhost:8000/manifest.json`
  avec `python -m http.server` servant un manifeste signé (via
  `publier_manifeste.sh` et `MAJ_CLE_PRIVEE_PEM`) et le zip de `make dmg`. Le script
  shell macOS peut aussi être rejoué seul sur une fausse `.app`.
- **Prerelease** : tag `v0.4.0-rc1`, puis `DEBRIEFMEET_MAJ_URL=https://github.com/sylvaing/debriefMeet/releases/download/v0.4.0-rc1/manifest.json`.

## 7. Pièges mesurés ou anticipés

1. **`follow_redirects=True` obligatoire** : httpx ne suit pas les redirections par
   défaut, et `releases/latest/download/…` en fait deux. Sans ce drapeau on lit un corps
   vide en 302 — figé par un test.
2. La **clé par défaut d'une fonction est liée à la définition** : `verifier_signature`
   résout `CLE_PUBLIQUE_PEM` à l'appel (`None` par défaut), sinon les tests qui
   substituent la constante ne testent rien.
3. **Un zombie répond à `kill -0`** : le test d'exécution du script macOS doit
   moissonner le process attendu (en réel, launchd le fait).
4. Un `.cmd` doit être écrit en `\r\n`.
5. `test_build.py::_section` coupe à la **première** occurrence d'un nom de section :
   un seul bloc `[Code]`, et jamais de nom de section entre crochets dans un
   commentaire `//`.
6. `packaging` n'était embarqué que par transitivité (via `huggingface_hub`) et **pas
   du tout dans le `.deb`** : désormais dépendance explicite, comme `cryptography`.
