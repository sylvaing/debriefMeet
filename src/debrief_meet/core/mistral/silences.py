"""Compaction des silences avant envoi à Voxtral (docs/42 §10.2).

Motivation terrain (2026-08-18) : en réunion **physique**, la piste système ne
contient que quelques bips de notification — mesuré chez une utilisatrice : **19 s
sonores sur 98 min**, en 12 événements de 1 à 2 s. Envoyer les 98 min coûte du quota
pour rien et offre surtout à Voxtral 98 min de quasi-silence, terrain d'hallucination
connu (docs/22) dont le texte inventé serait attribué aux « Participants ».

**On ne jette jamais une piste** : on retire seulement ses silences et on envoie les
portions sonores, en conservant la correspondance des instants (`vers_original`) pour
que la fusion Moi/Participants reste juste. Un critère de proportion (« moins de 1 %
de temps sonore ⇒ piste ignorée ») a été étudié puis **rejeté** le 2026-08-18 : une
intervention visio d'une minute dans une réunion de 98 min ne pèse que 0,6 à 0,97 %,
elle aurait donc été jetée avec ses propos. Perdre de la parole réelle est bien pire
que gaspiller du quota — d'où le choix de compacter plutôt que de trancher.

La compaction n'a lieu que si elle retire une part significative de la piste
(`FRACTION_UTILE`) : une piste normalement parlée part inchangée, sans ré-encodage.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from debrief_meet.core.fichiers import ErreurFfmpegIntrouvable, chemin_ffmpeg

#: Plancher de parole, appliqué au RMS d'une tranche de `PAS_S` (audio BRUT, sans
#: normalisation : ici on cherche « où y a-t-il du son », pas « faut-il transcrire »).
SEUIL_RMS_SONORE = 0.005
PAS_S = 1.0
#: Marge conservée autour d'une tranche sonore — une coupe au ras du seuil tronquerait
#: l'attaque et la fin d'un mot.
MARGE_S = 1.0
#: Deux plages séparées par moins que cela sont fusionnées (garder un court silence
#: coûte moins qu'une coupe au milieu d'une phrase).
FUSION_S = 5.0
#: On ne compacte que si l'on garde au plus cette fraction de la piste.
FRACTION_UTILE = 0.8
#: Au-delà, l'écart de fusion est élargi : `aselect` prend une expression par plage et
#: une ligne de commande trop longue casse sous Windows. Élargir la fusion ne fait
#: qu'AJOUTER de l'audio — jamais en perdre.
MAX_PLAGES = 120
#: Profondeur d'imbrication maximale de l'évaluateur d'expressions de ffmpeg
#: (`STACK_SIZE` de `libavutil/eval.c` — **mesurée à 100 exactement** sur le binaire
#: embarqué le 2026-09-08, par dichotomie sur le nombre de termes).
PROFONDEUR_EVAL_FFMPEG = 100
#: Taille des groupes parenthésés de l'expression `aselect` (cf. `expression_selection`).
#: Profondeur obtenue : `n / TAILLE + TAILLE`, soit ~30 niveaux pour les `MAX_PLAGES`
#: plages du pire cas — et la mesure confirme le modèle : à 25 la chaîne tient
#: jusqu'à ~1900 plages là où une chaîne plate cède à 101.
TAILLE_GROUPE_EXPRESSION = 25
#: Sortie de ffmpeg quand `av_expr_parse` rend `AVERROR(ENOMEM)` (= −12 rendu en octet
#: non signé). Documenté ici parce que rien, ni dans le code de sortie ni dans le
#: message (« Cannot allocate memory »), ne désigne le nombre de plages.
CODE_SORTIE_ENOMEM = 244
#: Débit du ré-encodage, aligné sur celui de la rétention (`core.fichiers`).
_DEBIT_KBPS = 24


@dataclass(frozen=True)
class PlanCompaction:
    """Plages sonores à envoyer, dans la timeline d'ORIGINE et par ordre croissant."""

    plages: tuple[tuple[float, float], ...]
    duree_totale_s: float

    @property
    def duree_gardee_s(self) -> float:
        return sum(fin - debut for debut, fin in self.plages)

    @property
    def utile(self) -> bool:
        """Vrai si compacter vaut le ré-encodage (et ne vide pas la piste)."""
        return bool(self.plages) and self.duree_gardee_s <= FRACTION_UTILE * self.duree_totale_s

    def vers_original(self, instant: float) -> float:
        """Convertit un instant de la timeline COMPACTÉE vers celle d'origine.

        Voxtral horodate ce qu'on lui a envoyé ; sans cette conversion, la fusion
        placerait des propos de la 88ᵉ minute au début de la réunion."""
        if not self.plages:
            return instant
        reste = max(0.0, instant)
        for debut, fin in self.plages:
            duree = fin - debut
            if reste <= duree:
                return debut + reste
            reste -= duree
        return self.plages[-1][1]


def _fusionner(plages: list[tuple[float, float]], ecart: float) -> list[tuple[float, float]]:
    fusionnees: list[tuple[float, float]] = []
    for debut, fin in plages:
        if fusionnees and debut - fusionnees[-1][1] <= ecart:
            precedent = fusionnees[-1]
            fusionnees[-1] = (precedent[0], max(precedent[1], fin))
        else:
            fusionnees.append((debut, fin))
    return fusionnees


def plan_compaction(audio: np.ndarray, sr: int = 16_000) -> PlanCompaction:
    """Repère les plages sonores de `audio` (float32 mono) par tranches de `PAS_S`."""
    duree_totale = len(audio) / sr if sr else 0.0
    pas = int(PAS_S * sr)
    nb = len(audio) // pas if pas else 0
    if nb == 0:
        # Trop court pour être analysé par tranches : on garde tout tel quel.
        return PlanCompaction(((0.0, duree_totale),) if len(audio) else (), duree_totale)

    tranches = np.asarray(audio[: nb * pas], dtype=np.float32).reshape(nb, pas)
    niveaux = np.sqrt((tranches**2).mean(axis=1))
    plages = [
        (max(0.0, i * PAS_S - MARGE_S), min(duree_totale, (i + 1) * PAS_S + MARGE_S))
        for i in np.flatnonzero(niveaux > SEUIL_RMS_SONORE)
    ]
    if not plages:
        return PlanCompaction((), duree_totale)

    ecart = FUSION_S
    plages = _fusionner(plages, ecart)
    while len(plages) > MAX_PLAGES:
        ecart *= 2
        plages = _fusionner(plages, ecart)
    return PlanCompaction(tuple(plages), duree_totale)


class ErreurCompactionFfmpeg(RuntimeError):
    """Échec d'une commande ffmpeg de compaction, **stderr compris**.

    `CalledProcessError` ne rend que la commande et le code de sortie, et le repli
    se contentait de journaliser `exc` : le message de ffmpeg était donc perdu. Le
    diagnostic du 2026-09-08 a coûté une reproduction manuelle du binaire embarqué
    pour découvrir un « Cannot allocate memory » que le code 244 ne laissait pas
    deviner — d'où cette exception, qui embarque le résumé de stderr."""


def expression_selection(plages: tuple[tuple[float, float], ...]) -> str:
    """Expression `aselect` gardant `plages`, groupée pour rester analysable.

    Terrain du 2026-09-07 : une réunion de 93 min à **107 plages** sortait en
    `CODE_SORTIE_ENOMEM` sur les deux tentatives de CR. L'évaluateur de ffmpeg
    analyse `a+b+c` par récursion — **un niveau par terme** — et s'arrête à
    `PROFONDEUR_EVAL_FFMPEG` : au-delà de 100 plages la compaction échouait donc
    toujours, sur les 3 OS (la limite est dans `libavutil`, pas dans le build
    minimal de macOS), alors que `MAX_PLAGES` en autorise 120. Ni la longueur de la
    ligne de commande (3,4 ko mesurés, très loin d'`ARG_MAX`) ni un filtre absent
    (docs/16 §5.5) n'étaient en cause.

    Réunir les termes en groupes parenthésés de `TAILLE_GROUPE_EXPRESSION` ramène la
    profondeur de `n` à `n / TAILLE + TAILLE`. Le groupement est neutre : chaque
    `between` vaut 0 ou 1, l'addition est associative, et `aselect` ne regarde que
    la nullité du résultat. Un seul groupe reste sans parenthèses — les pistes
    courantes gardent l'expression plate, lisible dans les logs.
    """
    termes = [f"between(t,{debut:.3f},{fin:.3f})" for debut, fin in plages]
    groupes = [
        "+".join(termes[i:i + TAILLE_GROUPE_EXPRESSION])
        for i in range(0, len(termes), TAILLE_GROUPE_EXPRESSION)
    ]
    if len(groupes) <= 1:
        return groupes[0] if groupes else ""
    return "+".join(f"({groupe})" for groupe in groupes)


def _termes_de_premier_niveau(expression: str) -> list[str]:
    """Découpe sur les `+` hors parenthèses (celles de `between(t,a,b)` comprises)."""
    termes: list[str] = []
    niveau = debut = 0
    for i, car in enumerate(expression):
        if car == "(":
            niveau += 1
        elif car == ")":
            niveau -= 1
        elif car == "+" and niveau == 0:
            termes.append(expression[debut:i])
            debut = i + 1
    termes.append(expression[debut:])
    return termes


def profondeur_expression(nb_plages: int) -> int:
    """Profondeur d'analyse de l'expression RÉELLEMENT produite pour `nb_plages`.

    Mesurée sur la sortie de `expression_selection`, jamais recalculée par une
    formule parallèle : un garde-fou qui refait le calcul de son côté reste vert
    même si le groupement disparaît du code (piège déjà rencontré sur la largeur de
    la colonne d'actions, CLAUDE.md 2026-08-24). `av_expr_parse` descend d'un niveau
    par terme d'une chaîne `a+b+c`, et d'un niveau de plus pour entrer dans une
    parenthèse."""
    expression = expression_selection(tuple((0.0, 0.0) for _ in range(nb_plages)))
    if not expression:
        return 0
    groupes = _termes_de_premier_niveau(expression)
    interne = max(
        (1 + len(_termes_de_premier_niveau(groupe[1:-1]))
         for groupe in groupes if groupe.startswith("(")),
        default=0,
    )
    return len(groupes) + interne


def compacter_piste(chemin: Path, dossier_sortie: Path, plan: PlanCompaction) -> Path:
    """Écrit un Opus 16 kHz mono ne contenant que les plages de `plan`.

    `aselect` garde les tranches voulues et `asetpts=N/SR` réécrit les horodatages
    pour que la sortie soit continue — d'où le besoin de `plan.vers_original` en
    retour. L'expression est entre apostrophes : sans elles, les virgules de
    `between(t,a,b)` seraient lues comme des séparateurs de filtres par ffmpeg ; elle
    est aussi groupée par parenthèses (cf. `expression_selection`).

    Sortie en Opus (même codec et débit que la rétention) et non en WAV : garder 60 %
    d'une piste de 98 min ferait un WAV de plus de 100 Mo, soit un envoi bien pire que
    l'original compressé.

    **Deux passes obligatoires** : sélectionner et encoder en Opus d'un seul coup
    produit un Ogg dont l'en-tête annonce une durée absurde (0,08 s mesuré pour 38 s
    d'audio le 2026-08-18) — un serveur qui s'y fie ne transcrirait que le début. En
    passant par un WAV intermédiaire, chaque étape reste une opération ordinaire et la
    durée est exacte. Le WAV est supprimé aussitôt : il peut être volumineux."""
    exe = chemin_ffmpeg()
    if exe is None:
        raise ErreurFfmpegIntrouvable()
    expression = expression_selection(plan.plages)
    intermediaire = dossier_sortie / (chemin.stem + "_compacte.wav")
    sortie = dossier_sortie / (chemin.stem + "_compacte.opus")
    _ffmpeg(exe, "-i", str(chemin),
            "-af", f"aselect='{expression}',asetpts=N/SR",
            "-ac", "1", "-ar", "16000", str(intermediaire))
    try:
        _ffmpeg(exe, "-i", str(intermediaire),
                "-c:a", "libopus", "-b:a", f"{_DEBIT_KBPS}k", str(sortie))
    finally:
        intermediaire.unlink(missing_ok=True)
    return sortie


#: Bornes du résumé de stderr : ffmpeg réémet l'expression entière dans son message
#: d'erreur (3 ko ici), or l'information tient dans les dernières lignes.
_MAX_LIGNES_STDERR = 5
_MAX_CAR_LIGNE = 200


def _abreger(texte: str) -> str:
    if len(texte) <= _MAX_CAR_LIGNE:
        return texte
    return f"{texte[:_MAX_CAR_LIGNE]}… (+{len(texte) - _MAX_CAR_LIGNE} car.)"


def _resumer_stderr(flux: bytes | str | None) -> str:
    """Dernières lignes de stderr, chacune tronquée — journalisables telles quelles."""
    if not flux:
        return "aucune sortie d'erreur"
    texte = flux.decode("utf-8", "replace") if isinstance(flux, bytes) else flux
    lignes = [ligne.strip() for ligne in texte.splitlines() if ligne.strip()]
    if not lignes:
        return "aucune sortie d'erreur"
    return " | ".join(_abreger(ligne) for ligne in lignes[-_MAX_LIGNES_STDERR:])


def _ffmpeg(exe: str, *args: str) -> None:
    commande = [exe, "-y", "-loglevel", "error", *args]
    try:
        subprocess.run(
            commande,
            check=True, capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.CalledProcessError as exc:
        raise ErreurCompactionFfmpeg(
            f"ffmpeg code {exc.returncode} : {_resumer_stderr(exc.stderr)}"
            f" — commande : {' '.join(_abreger(a) for a in commande)}"
        ) from exc
