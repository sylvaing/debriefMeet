from __future__ import annotations

from debrief_meet.core.bluemind.association import InviteAssocie
from debrief_meet.core.bluemind.mapping import extraire_locuteurs, pre_remplir, renommer_locuteurs

_LOCUTEURS_MD = """# Réunion — locuteurs

> Diarization post-réunion (qui a parlé) — généré à la demande.

---

**Moi** [00:05] Bonjour à tous, on commence.

**Présent 1** [00:12] Merci, j'ai préparé le point budget.

**Moi** [00:40] Parfait, vas-y.

**Présent 1** [00:45] Donc pour ce trimestre les chiffres sont bons.
"""


def _invite(nom, email, part_status=None, organisateur=False):
    return InviteAssocie(nom=nom, email=email, part_status=part_status,
                          organisateur=organisateur, coche=True)


# ── extraire_locuteurs ───────────────────────────────────────────────────────

def test_extraire_locuteurs_ordre_premiere_apparition(tmp_path):
    md = tmp_path / "r_locuteurs.md"
    md.write_text(_LOCUTEURS_MD, encoding="utf-8")
    locuteurs = extraire_locuteurs(md)
    assert [l.label for l in locuteurs] == ["Moi", "Présent 1"]


def test_extraire_locuteurs_apercu_contenu(tmp_path):
    md = tmp_path / "r_locuteurs.md"
    md.write_text(_LOCUTEURS_MD, encoding="utf-8")
    locuteurs = extraire_locuteurs(md)
    moi = next(l for l in locuteurs if l.label == "Moi")
    assert "Bonjour à tous, on commence." in moi.apercu


def test_extraire_locuteurs_poids_parole_cumule(tmp_path):
    md = tmp_path / "r_locuteurs.md"
    md.write_text(_LOCUTEURS_MD, encoding="utf-8")
    locuteurs = extraire_locuteurs(md)
    present1 = next(l for l in locuteurs if l.label == "Présent 1")
    assert present1.poids_parole > 0


def test_extraire_locuteurs_fichier_absent(tmp_path):
    assert extraire_locuteurs(tmp_path / "absent.md") == []


# ── pre_remplir ──────────────────────────────────────────────────────────────

def test_regle_1_nb_locuteurs_egal_nb_invites_acceptes_plus_organisateur(tmp_path):
    md = tmp_path / "r_locuteurs.md"
    md.write_text(_LOCUTEURS_MD, encoding="utf-8")
    locuteurs = extraire_locuteurs(md)  # Moi (poids fort), Présent 1
    invites = [
        _invite("Sylvain Garcia", "sylvain@ex.com", organisateur=True),
        _invite("Jean Dupont", "jean@ex.com", part_status="Accepted"),
    ]
    mapping = pre_remplir(locuteurs, invites)
    ordre = sorted(locuteurs, key=lambda l: l.poids_parole, reverse=True)
    assert mapping[ordre[0].label] == "Sylvain Garcia"
    assert mapping[ordre[1].label] == "Jean Dupont"


def test_regle_2_seuls_locuteurs_moi_et_un_accepte():
    l1 = _det("A", poids=100)
    l2 = _det("B", poids=10)
    invites = [_invite("Jean Dupont", "jean@ex.com", part_status="Accepted")]
    mapping = pre_remplir([l1, l2], invites)
    assert mapping == {"A": "Moi", "B": "Jean Dupont"}


def test_regle_3_top_locuteur_organisateur_seul():
    l1 = _det("A", poids=100)
    l2 = _det("B", poids=10)
    l3 = _det("C", poids=5)
    invites = [_invite("Sylvain Garcia", "s@ex.com", organisateur=True)]
    mapping = pre_remplir([l1, l2, l3], invites)
    assert mapping == {"A": "Sylvain Garcia"}


def test_aucune_suggestion_si_rien_ne_colle():
    l1 = _det("A", poids=100)
    l2 = _det("B", poids=10)
    l3 = _det("C", poids=5)
    invites = [_invite("Jean", "jean@ex.com", part_status="Declined")]
    assert pre_remplir([l1, l2, l3], invites) == {}


def test_aucun_locuteur():
    assert pre_remplir([], [_invite("Jean", "jean@ex.com", organisateur=True)]) == {}


def _det(label, poids):
    from debrief_meet.core.bluemind.mapping import LocuteurDetecte
    return LocuteurDetecte(label=label, apercu=[], poids_parole=poids)


# ── renommer_locuteurs ───────────────────────────────────────────────────────

def test_renommer_remplace_partout_y_compris_horodatage(tmp_path):
    md = tmp_path / "r_locuteurs.md"
    md.write_text(_LOCUTEURS_MD, encoding="utf-8")
    renommer_locuteurs(md, {"Moi": "Sylvain Garcia", "Présent 1": "Jean Dupont"})
    texte = md.read_text(encoding="utf-8")
    assert "**Sylvain Garcia** [00:05]" in texte
    assert "**Jean Dupont** [00:12]" in texte
    assert "Présent 1" not in texte
    assert "**Moi**" not in texte


def test_renommer_mapping_vide_no_op(tmp_path):
    md = tmp_path / "r_locuteurs.md"
    md.write_text(_LOCUTEURS_MD, encoding="utf-8")
    original = md.read_text(encoding="utf-8")
    renommer_locuteurs(md, {})
    assert md.read_text(encoding="utf-8") == original


def test_renommer_labels_prefixes_ne_se_corrompent_pas(tmp_path):
    md = tmp_path / "r_locuteurs.md"
    md.write_text("**Présent 1** [00:00] a\n\n**Présent 10** [00:01] b\n", encoding="utf-8")
    renommer_locuteurs(md, {"Présent 1": "Alice", "Présent 10": "Bob"})
    texte = md.read_text(encoding="utf-8")
    assert "**Alice** [00:00] a" in texte
    assert "**Bob** [00:01] b" in texte
