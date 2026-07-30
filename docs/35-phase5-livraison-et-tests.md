# Phase 5 — Livraison, tests et boucle de feedback utilisateurs

> **Statut : 📝 SPEC / PROCÉDURE** (2026-07-03). Dépend de : docs/31 (diagnostic),
> docs/32 (setup). Ce document définit **comment on livre et comment on débogue à
> distance** — les utilisateurs (Bastien, Alix) sont le banc de test, les logs sont
> le debugger. Une partie est du livrable (notice utilisateur, template), une
> partie est de la procédure pour Sylvain.

---

## 1. Cadence et convention de livraison

- **Un livrable = un fichier** : `debriefMeet-setup-<VERSION_COMPLETE>.exe`
  (ex. `debriefMeet-setup-0.2.0+20260710.3f2a1c9.exe`). Le hash git dans le nom =
  correspondance exacte log ↔ exécutable ↔ commit (docs/31 §3.2). Ne jamais
  renommer le fichier avant envoi.
- **Depuis docs/44, deux éditions** : `debriefMeet-setup-*.exe` (complète) et
  `debriefMeet-lite-setup-*.exe` (lite — enregistrement Opus seul, transcription et CR
  via l'API Mistral). Un poste reçoit **une** édition : l'`AppId` étant identique,
  installer l'une remplace l'autre. La version reste une chaîne unique, l'édition n'y
  est jamais collée — elle se lit dans le nom du setup et dans la ligne `edition` de
  l'en-tête de session. **En édition lite, une clé API Mistral est obligatoire** : sans
  elle l'app enregistre mais ne peut jamais transcrire — à dire en première ligne de la
  notice utilisateur (§2), et l'assistant de clé doit être proposé au premier lancement.
  Checklist §3 : l'item « dictée » ne s'applique pas au lite.
- **Avant chaque livraison** (ordre imposé) :
  1. suite `pytest -m "not integration"` verte sur Mac ;
  2. build VM via `scripts/build_app_windows_vm.sh` (inclut le pytest VM bloquant,
     docs/32 §2) ;
  3. **fumée sur la VM** (console Proxmox ou RDP) : installer le setup produit,
     lancer l'app, vérifier tray + en-tête de session dans les logs, une dictée
     de 5 s (micro virtuel VM ou fichier — au minimum vérifier que l'app ne
     crashe pas et logge proprement l'absence de micro) ;
  4. mise à jour du journal de livraisons (§4).
- **Envoi** : le `.exe` + (première fois ou si changement) la notice §2. Canal :
  au choix de Sylvain (mail/partage) — hors scope.

## 2. Notice utilisateur (livrable à rédiger : `docs/assets/notice-windows.md` → PDF/mail)

Une page, langage non technique, captures d'écran à faire lors de la première
installation sur la VM. Contenu imposé :

1. **Installer / mettre à jour** (même procédure) : double-cliquer le fichier
   `debriefMeet-setup-….exe`.
   - Écran bleu « Windows a protégé votre ordinateur » : cliquer
     **« Informations complémentaires »** puis **« Exécuter quand même »**
     (capture d'écran des deux clics). Expliquer en une phrase : l'application
     n'est pas signée commercialement, cet avertissement est normal.
   - Si debriefMeet est ouvert, l'installeur propose de le fermer : accepter.
2. **Où trouver l'app** : menu Démarrer → debriefMeet ; l'icône vit dans la zone de
   notification (systray), près de l'horloge (capture).
3. **Raccourcis** : `Ctrl+Alt+D` dictée, `Ctrl+Alt+R` réunion, `Ctrl+Alt+J` journal.
4. **En cas de problème** : clic droit sur l'icône debriefMeet →
   **« Exporter le diagnostic… »** → un fichier
   `debriefMeet-diagnostic-….zip` apparaît sur le Bureau → l'envoyer à Sylvain
   avec 2 phrases : *ce que vous faisiez* et *ce qui s'est passé*.
   Si l'app ne démarre même plus : envoyer directement le dossier
   `%LOCALAPPDATA%\debriefMeet\Logs` (donner le chemin cliquable :
   appuyer sur `Win+R`, coller le chemin, Entrée, zipper le dossier).
5. **Désinstaller** : Paramètres Windows → Applications → debriefMeet →
   Désinstaller. Vos transcriptions restent dans `Documents\debriefMeet`.

## 3. Checklist de test par livraison (à joindre aux livraisons qui changent l'audio/le moteur)

5 minutes, formulée pour un non-technicien — chaque item répond par oui/non :

| # | Test | Attendu |
|---|------|---------|
| 1 | Installer la nouvelle version par-dessus l'ancienne | L'installation se termine sans erreur |
| 2 | L'icône debriefMeet est dans la zone de notification | Oui |
| 3 | `Ctrl+Alt+D`, dire « ceci est un test de dictée », `Ctrl+Alt+D` | Le texte se colle (Ctrl+V) dans le Bloc-notes |
| 4 | Lancer une Réunion (menu tray) pendant une courte visio ou une vidéo YouTube, 1 min, arrêter | Un fichier apparaît dans `Documents\debriefMeet\reunions` et contient à peu près ce qui s'est dit |
| 5 | Vos réglages (préférences) sont toujours là après la mise à jour | Oui |
| 6 | Si un test échoue | « Exporter le diagnostic… » + envoyer le zip en précisant le n° du test |

## 4. Journal de livraisons — `docs/36-journal-livraisons-windows.md` (à créer à la 1ʳᵉ livraison)

Table append-only, une ligne par setup envoyé :

| Date | VERSION_COMPLETE | Destinataires | Contenu (2 lignes) | Retours |
|------|------------------|---------------|--------------------|---------|

C'est le pendant humain du hash dans les logs : quand un zip diagnostic arrive,
cette table dit ce que contenait exactement la version concernée et ce qui a déjà
été signalé dessus.

## 5. Procédure d'analyse d'un zip diagnostic (pour Sylvain / la session LLM)

À l'arrivée d'un `debriefMeet-diagnostic-<version>-<horodatage>.zip` :

1. **Identifier le build** : version complète dans le nom du zip → `git checkout
   <hash>` mentalement (le code lu doit être celui-là) ; croiser avec le journal §4.
2. **Lire `infos_systeme.json`** : machine, périphériques audio (host API MME vs
   WASAPI, taux), GPU/driver, RAM — beaucoup de bugs audio se voient déjà là
   (docs/33 E-8).
3. **Lire l'en-tête de session** du dernier log, puis remonter : dernière session =
   celle du problème (sauf mention contraire de l'utilisateur).
4. **Chercher dans l'ordre** : `debriefMeet-crash.log` (crash natif ?) → CRITICAL/
   ERROR → WARNING (replis stubs ! AEC absente ! repli « mode silence » du loopback,
   docs/34 §2.3) → DEBUG autour de l'horodatage décrit par l'utilisateur (RMS,
   RTF, hot-plug).
5. **Signatures connues à vérifier systématiquement** (héritées de docs/33) :
   - RMS très bas + texte long → hallucination silence (docs/22, E-1) ;
   - host API `MME` au lieu de `WASAPI` → périphérique dégradé ;
   - changements répétés de périphérique/sortie → scénario BT (docs/20/25, docs/34 §2.3) ;
   - RTF > 1 durable → CPU insuffisant → déclencher le chantier iGPU (docs/30 D2).
6. Verdict consigné dans le journal §4 (colonne Retours) + le cas échéant un
   nouveau doc de fix numéroté (même processus que docs/23-29 côté macOS).

## 6. Tests d'intégration Windows (marqueur `integration`)

Les tests `integration` existants supposent du matériel Mac. Pour Windows, en créer
au fil des adaptateurs (docs/34) — exécutables **sur la VM** uniquement :

- loopback WASAPI réel : capturer 2 s pendant la lecture d'un WAV → énergie non
  nulle (VM : nécessite un périphérique de sortie virtuel — sinon test `skip` avec
  raison explicite) ;
- `winreg` réel : cycle autostart complet ;
- `RegisterHotKey` réel : enregistrement/désenregistrement (sans simuler la frappe).

Ils ne conditionnent pas les livraisons v1 (le pytest bloquant du build est
`-m "not integration"`) mais se lancent manuellement sur la VM quand on touche à
l'adaptateur concerné.

## 7. Definition of Done (premier cycle de livraison complet)

- [ ] Notice §2 rédigée avec captures, envoyée avec le premier setup.
- [ ] Checklist §3 déroulée par au moins un utilisateur, retours consignés (§4).
- [ ] Un zip diagnostic **de test** demandé à un utilisateur (même sans bug) et
      analysé via §5 — valide toute la chaîne d'observabilité en conditions réelles
      avant d'en avoir vraiment besoin.
- [ ] Journal docs/36 initialisé.
