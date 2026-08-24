"""Tests unitaires — transcription différée (depuis l'audio retenu)."""
from __future__ import annotations

import numpy as np
import pytest
from scipy.io import wavfile

from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE
from debrief_meet.core.transcription_differee import transcrire_reunion
from debrief_meet.platform.interfaces import ResultatTranscription, Segment
from tests.fakes.adapters import MoteurFake


def _placeholder(tmp_path, nom="2026-01-01_10-00-00"):
    md = tmp_path / f"{nom}.md"
    md.write_text(f"# Réunion — 2026-01-01 10:00\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    return md


def _piste(tmp_path, suffixe):
    # Constante audible (pas du silence) : depuis docs/27, le moteur applique la porte
    # anti-silence en interne (héritée par MoteurFake) — un WAV muet serait ignoré.
    wavfile.write(tmp_path / f"{suffixe}.wav", 16000, np.full(16000, 3000, dtype=np.int16))


def test_transcrit_les_deux_pistes_et_reecrit_le_md(tmp_path):
    md = _placeholder(tmp_path)
    _piste(tmp_path, "moi")
    _piste(tmp_path, "systeme")
    moteur = MoteurFake()

    resultat = transcrire_reunion(md, moteur)

    assert resultat == md
    contenu = md.read_text(encoding="utf-8")
    assert MARQUEUR_EN_ATTENTE not in contenu          # placeholder remplacé
    assert "**Moi :**" in contenu
    assert "**Participants :**" in contenu
    assert "transcription de test" in contenu
    assert len(moteur.appels_transcrire) == 2           # 2 pistes transcrites


def test_une_seule_piste_presente(tmp_path):
    md = _placeholder(tmp_path)
    _piste(tmp_path, "moi")          # pas de système
    moteur = MoteurFake()

    transcrire_reunion(md, moteur)

    contenu = md.read_text(encoding="utf-8")
    assert "**Moi :**" in contenu
    assert "Audio système non disponible" in contenu     # warning piste manquante
    assert len(moteur.appels_transcrire) == 1


def test_aucune_piste_leve(tmp_path):
    md = _placeholder(tmp_path)
    with pytest.raises(FileNotFoundError):
        transcrire_reunion(md, MoteurFake())


def test_titre_conserve_depuis_le_md(tmp_path):
    md = _placeholder(tmp_path)
    _piste(tmp_path, "moi")
    transcrire_reunion(md, MoteurFake())
    assert md.read_text(encoding="utf-8").startswith("# Réunion — 2026-01-01 10:00")


def test_titre_custom_conserve(tmp_path):
    md = _placeholder(tmp_path)
    md.write_text(md.read_text(encoding="utf-8").replace(
        "# Réunion — 2026-01-01 10:00", "# Budget Q3"), encoding="utf-8")
    _piste(tmp_path, "moi")
    transcrire_reunion(md, MoteurFake())
    from debrief_meet.core.fichiers import titre_reunion
    assert titre_reunion(md) == "Budget Q3"             # le titre custom survit à la réécriture


def test_duree_conservee_apres_reecriture(tmp_path):
    from debrief_meet.core.fichiers import definir_duree, duree_reunion
    md = _placeholder(tmp_path)
    definir_duree(md, 900)                               # durée posée en fin de captation
    _piste(tmp_path, "moi")
    transcrire_reunion(md, MoteurFake())
    assert duree_reunion(md) == 900                      # préservée malgré la réécriture du .md


# ── Cartouche invités BlueMind préservé à la réécriture (2026-08-24) ──────────

def _associer(md, titre="point commerce Alix"):
    """Sidecar minimal, comme après une association F1."""
    from debrief_meet.core.bluemind.association import Association, InviteAssocie, ecrire
    ecrire(md, Association(
        event_uid="e1", cal_uid="cal", titre=titre, debut="2026-08-24T10:00:00+02:00",
        invites=[
            InviteAssocie(nom="Sylvain Garcia", email="sylvain.garcia@bluemind.net",
                          part_status=None, organisateur=True, coche=True),
            InviteAssocie(nom="Alix Morel", email="alix.morel@exemple.fr",
                          part_status="Accepted", organisateur=False, coche=True),
        ],
    ))


def test_reecriture_conserve_le_cartouche_invites(tmp_path):
    """Le bug du 2026-08-24 : la réécriture repart d'une page blanche et effaçait le
    cartouche, que seul le chemin Voxtral savait ré-insérer."""
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT

    md = _placeholder(tmp_path)
    _associer(md)
    _piste(tmp_path, "moi")
    _piste(tmp_path, "systeme")

    transcrire_reunion(md, MoteurFake())

    contenu = md.read_text(encoding="utf-8")
    assert MARQUEUR_DEBUT in contenu
    assert "Alix Morel <alix.morel@exemple.fr> — accepté" in contenu
    assert "Sylvain Garcia <sylvain.garcia@bluemind.net> — organisateur" in contenu
    assert "« point commerce Alix » — 2026-08-24 10:00" in contenu


def test_cartouche_pose_entre_le_titre_et_la_duree(tmp_path):
    """Même ordonnancement que le chemin Voxtral — les deux s'insèrent après le H1."""
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT

    md = _placeholder(tmp_path)
    _associer(md)
    _piste(tmp_path, "moi")
    from debrief_meet.core.fichiers import definir_duree
    definir_duree(md, 1529)

    transcrire_reunion(md, MoteurFake())

    contenu = md.read_text(encoding="utf-8")
    assert contenu.index("# ") < contenu.index(MARQUEUR_DEBUT) < contenu.index("<!-- duree_s:")


def test_reunion_non_associee_reste_sans_cartouche(tmp_path):
    from debrief_meet.core.bluemind.participants import MARQUEUR_DEBUT

    md = _placeholder(tmp_path)
    _piste(tmp_path, "moi")

    transcrire_reunion(md, MoteurFake())

    assert MARQUEUR_DEBUT not in md.read_text(encoding="utf-8")
