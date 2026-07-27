"""Diarization (passe finale post-réunion) — « qui a parlé ».

Re-transcrit l'audio retenu des 2 pistes (micro nettoyé par l'AEC + système), diarize
chaque piste avec pyannote, étiquette **Moi / Présent N / Distant M**, attribue le locuteur
à chaque segment Whisper, fusionne en une timeline unique et écrit `<stem>_locuteurs.md`.
Tout est offline, déclenché à la demande (CLI ici ; bouton Historique en 2ᵉ passe).

Gabarit `core/aec.py` : interface `MoteurDiarization` + une implémentation `DiarizationPyannote`
(import paresseux, repli propre). Cf. docs/07-diarization.md.
"""
from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

import numpy as np

from debrief_meet.core.audio import decoder_audio_16k, normaliser_asr
from debrief_meet.core.fichiers import chemin_locuteurs, chemins_audio_reunion
from debrief_meet.platform.interfaces import ResultatTranscription, Segment

logger = logging.getLogger(__name__)

SR = 16_000
PYANNOTE_PIPELINE = "pyannote/speaker-diarization-community-1"


# ── Moteur de diarization (interface + implémentation pyannote) ────────────────

class MoteurDiarization:
    """Interface : segmente un audio 16 kHz mono en tours de parole par locuteur brut."""

    def diariser(self, audio_16k: np.ndarray) -> list[tuple[float, float, str]]:
        """Retourne une liste de `(debut_s, fin_s, locuteur_brut)` triée par début."""
        raise NotImplementedError

    def precharger(self) -> None:
        """Charge le modèle maintenant (échoue tôt et clairement). No-op par défaut."""


def _token_hf() -> str | None:
    """Token HF depuis l'env (`HF_TOKEN`) ou le cache (`hf auth login`).

    Sert uniquement à **pré-remplir** le champ de l'assistant par confort. Le token
    n'est jamais stocké par l'app (cf. docs/13)."""
    tok = os.environ.get("HF_TOKEN")
    if tok:
        return tok
    try:
        from huggingface_hub import get_token

        return get_token()
    except Exception:
        logger.debug("token HF introuvable", exc_info=True)
        return None


# ── Onboarding du modèle gated (téléchargement à la demande, token à la volée) ──
#
# Le token HF n'est nécessaire qu'au **téléchargement** du modèle gated : il est saisi
# dans l'assistant, passé à la volée à `from_pretrained`, puis **oublié** (jamais
# stocké). Les chargements ultérieurs lisent le cache local en `local_files_only`.
# Cf. docs/13-diarization-onboarding.md.

class ErreurDiarization(Exception):
    """Erreur d'onboarding de la diarization (message destiné à l'utilisateur)."""


class ErreurToken(ErreurDiarization):
    """Token HF incorrect / sans accès (≈ 401)."""


class ErreurLicence(ErreurDiarization):
    """Licence du modèle non acceptée (≈ 403)."""


class ErreurReseau(ErreurDiarization):
    """Téléchargement impossible (réseau, serveur indisponible…)."""


def modele_telecharge() -> bool:
    """Vrai si le pipeline pyannote est présent dans le **cache HF local**.

    Test **léger** (pas de chargement du modèle, pas de réseau) : on vérifie la
    présence du `config.yaml` du pipeline dans le cache. Appelable souvent (gating UI)."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except Exception:
        return False
    chemin = try_to_load_from_cache(PYANNOTE_PIPELINE, "config.yaml")
    return isinstance(chemin, str)


def configuree() -> bool:
    """Vrai si la diarization est utilisable : le modèle est téléchargé (le token
    n'entre pas dans la condition — il n'est plus nécessaire après l'onboarding)."""
    return modele_telecharge()


def _verifier_acces(token: str) -> None:
    """Sonde authentifiée → erreurs **typées** (pyannote avale les erreurs et renvoie
    None, d'où cette vérif préalable via huggingface_hub)."""
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import (
        GatedRepoError,
        HfHubHTTPError,
        RepositoryNotFoundError,
    )

    try:
        hf_hub_download(PYANNOTE_PIPELINE, "config.yaml", token=token)
    except GatedRepoError as exc:
        raise ErreurLicence(
            "Licence non acceptée — revenez à l'étape 2 et cliquez « Agree and access ».") from exc
    except RepositoryNotFoundError as exc:
        raise ErreurToken("Token incorrect ou sans accès — vérifiez l'étape 3.") from exc
    except HfHubHTTPError as exc:
        statut = getattr(getattr(exc, "response", None), "status_code", None)
        if statut == 401:
            raise ErreurToken("Token incorrect — vérifiez l'étape 3.") from exc
        if statut == 403:
            raise ErreurLicence("Licence non acceptée — revenez à l'étape 2.") from exc
        raise ErreurReseau("Téléchargement impossible (serveur) — réessayez.") from exc
    except ErreurDiarization:
        raise
    except Exception as exc:  # réseau, DNS, timeout…
        raise ErreurReseau(
            "Téléchargement impossible — vérifiez votre connexion et réessayez.") from exc


def _peupler_cache(token: str) -> None:
    """Télécharge le pipeline complet (sous-modèles inclus) dans le cache, token à la volée."""
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(PYANNOTE_PIPELINE, token=token)
    if pipeline is None:
        raise ErreurDiarization("Échec du téléchargement du pipeline pyannote.")


def telecharger(token: str, progression=None) -> None:
    """Peuple le cache HF avec le modèle pyannote gated, **token utilisé à la volée puis
    oublié** (jamais stocké). Lève `ErreurToken`/`ErreurLicence`/`ErreurReseau`."""
    if not token or not token.strip():
        raise ErreurToken("Token manquant — collez le token créé à l'étape 3.")
    token = token.strip()
    _verifier_acces(token)        # erreurs typées 401/403/réseau
    _peupler_cache(token)         # téléchargement effectif
    if progression:
        progression(1.0)


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


class DiarizationPyannote(MoteurDiarization):
    """pyannote community-1 (gated). Import paresseux ; device CUDA > MPS > CPU."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token or _token_hf()
        self._pipeline = None  # chargé paresseusement (ou injecté en test)

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

    def precharger(self) -> None:
        if self._pipeline is None:
            self._pipeline = self._charger()

    def diariser(self, audio_16k: np.ndarray) -> list[tuple[float, float, str]]:
        import torch

        self.precharger()
        waveform = torch.from_numpy(
            np.ascontiguousarray(audio_16k, dtype=np.float32)).unsqueeze(0)
        out = self._pipeline({"waveform": waveform, "sample_rate": SR})
        ann = getattr(out, "speaker_diarization", out)
        segs = [(float(tr.start), float(tr.end), str(lbl))
                for tr, _, lbl in ann.itertracks(yield_label=True)]
        segs.sort(key=lambda x: x[0])
        return segs


# ── Fonctions pures (cœur testable) ───────────────────────────────────────────

def etiqueter(segments: list[tuple[float, float, str]], mode: str
              ) -> list[tuple[float, float, str]]:
    """Renomme les clusters bruts en labels lisibles selon la piste.

    - `mode="micro"` : **1 seul cluster ⇒ tout « Moi »** ; sinon **« Présent 1..N »**.
    - `mode="systeme"` : **« Distant 1..M »**.
    Ordre d'attribution = 1ʳᵉ apparition (labels stables)."""
    ordre: list[str] = []
    for _, _, spk in segments:
        if spk not in ordre:
            ordre.append(spk)
    if mode == "micro" and len(ordre) <= 1:
        mapping = {spk: "Moi" for spk in ordre}
    else:
        prefixe = "Présent" if mode == "micro" else "Distant"
        mapping = {spk: f"{prefixe} {i}" for i, spk in enumerate(ordre, start=1)}
    return [(deb, fin, mapping[spk]) for deb, fin, spk in segments]


def attribuer(segs_whisper: list[Segment], segs_diar: list[tuple[float, float, str]]
              ) -> list[tuple[float, float, str, str]]:
    """Attribue à chaque segment Whisper le locuteur au plus grand chevauchement.

    Porté de `spike/diarization/comparer.py:attribuer`. Renvoie `(debut, fin, locuteur, texte)`.
    Locuteur « — » si aucun recouvrement."""
    out: list[tuple[float, float, str, str]] = []
    for s in segs_whisper:
        meilleur, best = "—", 0.0
        for d0, d1, spk in segs_diar:
            chevauch = max(0.0, min(s.fin, d1) - max(s.debut, d0))
            if chevauch > best:
                best, meilleur = chevauch, spk
        out.append((s.debut, s.fin, meilleur, s.texte))
    return out


def fusionner(*listes: list[tuple[float, float, str, str]]
              ) -> list[tuple[float, str, str]]:
    """Fusionne les pistes attribuées en une timeline unique triée par début, en
    regroupant les tours consécutifs du même locuteur. Renvoie `(debut, locuteur, texte)`."""
    tous = [item for liste in listes for item in liste if item[3].strip()]
    tous.sort(key=lambda x: x[0])
    tours: list[tuple[float, str, str]] = []
    for deb, _fin, spk, txt in tous:
        txt = txt.strip()
        if tours and tours[-1][1] == spk:
            deb0, _, txt0 = tours[-1]
            tours[-1] = (deb0, spk, f"{txt0} {txt}".strip())
        else:
            tours.append((deb, spk, txt))
    return tours


def rendre_locuteurs_md(chemin: Path, titre: str,
                        tours: list[tuple[float, str, str]]) -> None:
    """Écrit le débrief final `<stem>_locuteurs.md` : tours chronologiques préfixés du locuteur."""
    lignes = [f"# {titre}", "",
              "> Diarization post-réunion (qui a parlé) — généré à la demande.", "",
              "---", ""]
    for deb, spk, txt in tours:
        m, s = divmod(int(deb), 60)
        lignes.append(f"**{spk}** [{m:02d}:{s:02d}] {txt}")
        lignes.append("")
    chemin.write_text("\n".join(lignes), encoding="utf-8")


# ── Orchestration ─────────────────────────────────────────────────────────────

def _trouver_piste(base: Path) -> Path | None:
    """Localise la piste retenue (.opus prioritaire, sinon .wav) ; None si absente."""
    for ext in (".opus", ".wav"):
        candidat = base.with_suffix(ext)
        if candidat.exists():
            return candidat
    return None


def _traiter_piste(chemin_audio: Path, mode: str, moteur_transcription,
                   moteur_diarization: MoteurDiarization, langue: str | None
                   ) -> list[tuple[float, float, str, str]]:
    """Décode → normalise → re-transcrit → diarize → étiquette une piste. Peut lever."""
    # normalisation conservée pour pyannote ; le moteur re-normalise en no-op (audio déjà à la cible)
    audio = normaliser_asr(decoder_audio_16k(chemin_audio))
    res: ResultatTranscription = moteur_transcription.transcrire(audio, langue)
    diar = etiqueter(moteur_diarization.diariser(audio), mode)
    return attribuer(res.segments, diar)


def generer_locuteurs(chemin_md, moteur_transcription,
                      moteur_diarization: MoteurDiarization, *,
                      langue: str | None = None) -> Path:
    """Passe finale : produit `<stem>_locuteurs.md` depuis l'audio retenu de la réunion.

    Chaque piste est isolée : une piste manquante ou en échec dégrade le résultat
    (l'autre passe) sans casser. Lève seulement si AUCUNE piste n'est exploitable."""
    chemin_md = Path(chemin_md)
    base_moi, base_sys = chemins_audio_reunion(chemin_md)
    pistes = [(_trouver_piste(base_moi), "micro"), (_trouver_piste(base_sys), "systeme")]
    if all(p is None for p, _ in pistes):
        raise FileNotFoundError(
            f"Aucune piste audio retenue à côté de {chemin_md.name} "
            "(rétention désactivée ou audio supprimé).")

    # Chargée une fois, hors de la boucle par piste : une incompatibilité de chargement
    # (systématique, actionnable) ne doit pas se déguiser en « toutes les pistes en échec »
    # (cf. docs/29). Le try/except par piste ci-dessous reste réservé aux erreurs propres
    # à une piste (audio corrompu, etc.).
    try:
        moteur_diarization.precharger()
    except ErreurDiarization:
        raise
    except Exception as exc:
        raise ErreurDiarization(
            f"Chargement du modèle de diarization impossible : {exc}") from exc

    attribues: list[list[tuple[float, float, str, str]]] = []
    for chemin_audio, mode in pistes:
        if chemin_audio is None:
            continue
        try:
            attribues.append(_traiter_piste(chemin_audio, mode, moteur_transcription,
                                            moteur_diarization, langue))
        except Exception as exc:
            logger.warning("Diarization piste %s : ÉCHEC (%s)", mode, exc, exc_info=True)

    if not attribues:
        raise RuntimeError("Diarization : aucune piste exploitable (toutes en échec).")

    tours = fusionner(*attribues)
    sortie = chemin_locuteurs(chemin_md)
    rendre_locuteurs_md(sortie, f"Réunion — {chemin_md.parent.name} — locuteurs", tours)
    logger.info("Débrief locuteurs écrit : %s", sortie)
    return sortie


# ── CLI (déclenchement sans UI) ───────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse

    from debrief_meet.core.config import Config
    from debrief_meet.platform.factory import creer_adaptateurs

    ap = argparse.ArgumentParser(
        prog="debrief_meet.core.diarization",
        description="Diarization post-réunion → <stem>_locuteurs.md")
    ap.add_argument("reunion", type=Path, help="Chemin du .md de réunion")
    ap.add_argument("--langue", default=None, help="Langue forcée (défaut : config).")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = Config()
    config.charger()
    adaptateurs = creer_adaptateurs()
    adaptateurs.moteur.charger_modele(config.get("modele"))
    moteur_diar = DiarizationPyannote()
    langue = args.langue or config.get("langue")

    sortie = generer_locuteurs(args.reunion, adaptateurs.moteur, moteur_diar, langue=langue)
    print(f"✓ Débrief locuteurs : {sortie}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
