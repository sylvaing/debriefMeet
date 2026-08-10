# Spike — capture système Linux (sources `.monitor` PipeWire)

Exploration préalable à `platform/linux/capture_systeme_monitor.py` (docs/49 §5.1,
étape 2 du §8). **Isolé** : n'importe rien de `debrief_meet` ni de `benchmark/`,
venv dédié, sorties non versionnées.

## Lancer

```sh
sh spike/capture_monitor_linux/lancer.sh
```

Sur une **Ubuntu 26.04 avec session graphique et audio** (UTM arm64 convient — le
comportement PipeWire ne dépend pas de l'architecture ; le poste amd64 du collègue
sert à confirmer). **Jamais dans le conteneur LXC de build**, qui est headless et
sans serveur audio.

Options : `--secondes 20` (durée de la capture phase 2), `--phases 1` (inventaire
seul, sans manipulation).

## Envoyer le spike à quelqu'un

Le dossier est autonome — il ne dépend ni du dépôt ni du venv de l'app. Pour
l'envoyer à l'utilisateur cible :

```sh
zip -r spike-son-ubuntu.zip spike/capture_monitor_linux -x '*/sorties/*' '*/.venv/*'
```

`LISEZ-MOI.txt` est la notice destinée à cette personne : prérequis, déroulé,
ce qu'il faut renvoyer, et ce que contient le fichier de résultat (l'audio capté,
dit explicitement — avec l'option de n'envoyer que le log). Ce README-ci, lui,
reste interne.

## Ce qui est demandé à l'utilisateur

Le script est un **protocole guidé** : il annonce chaque action à l'écran, une à la
fois, attend Entrée, et écrit un marqueur `ACTION` horodaté dans le log. Les
consignes sont rédigées pour quelqu'un **sans contexte** — « ouvre une vidéo YouTube
ou un fichier de musique », « branche le casque USB maintenant » — et jamais en
termes de projet. Prévoir :

1. Un morceau de musique ou une vidéo à jouer sur la sortie par défaut.
2. Un casque **USB ou Bluetooth** à brancher puis débrancher, flux de capture ouvert.
   La phase 3 est **sautable** (touche `s`) : sans casque sous la main, l'utilisateur
   n'est pas bloqué et les deux premières phases restent exploitables.

À la fin, le script produit **un seul `.zip`** à renvoyer (et non un dossier) : une
occasion de moins de se tromper pour quelqu'un qui fait ça une fois.

## Ce que ça produit

`sorties/AAAA-MM-JJ_HH-MM-SS/` :

| Fichier | Contenu |
|---------|---------|
| `sonde.log` | Tout : inventaire, RMS par seconde de chaque flux, marqueurs `ACTION`, lignes `REPONSE Qn` |
| `phase2_micro.wav`, `phase2_monitor.wav` | Capture simultanée — le moniteur doit contenir la musique, le micro la voix |
| `phase3_monitor.wav` | Le moniteur pendant les bascules de sortie |

Lecture rapide des conclusions :

```sh
grep REPONSE sorties/*/sonde.log
```

## Les 5 questions à trancher

| # | Question | Impact sur l'implémentation |
|---|----------|----------------------------|
| Q1 | Nom exact et stabilité des sources moniteur vues de PortAudio | Stratégie de résolution du périphérique dans l'adaptateur |
| Q2 | `pactl` nécessaire pour identifier le bon moniteur ? | `Depends: pulseaudio-utils` dans le `.deb`, ou pas |
| Q3 | Taux natif et nombre de canaux rendus | Rééchantillonnage / downmix (le contrat WASAPI est 48 kHz stéréo→mono) |
| Q4 | Comportement au changement de sortie par défaut, flux ouvert | Toute la logique de réouverture à chaud + repli silence |
| Q5 | Le moniteur capte-t-il le son des applications (RMS non nul) ? | Validation de la voie elle-même |

**Q4 est la plus importante** : les réponses possibles (le flux suit tout seul / il
devient muet / PortAudio remonte une erreur) mènent à trois implémentations
différentes. Elle se lit en alignant les RMS par seconde sur les marqueurs `ACTION`
du log — d'où l'exigence de traçage des actions.

Les réponses obtenues sont à consigner dans docs/49 §5.1 avant d'écrire l'adaptateur.
