from __future__ import annotations

import sys
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from debrief_meet.core.fichiers import (
    EcrivainJournal,
    EcrivainReunion,
    EnregistreurAudioReunion,
    ErreurFfmpegIntrouvable,
    apercu_journal,
    chemin_cr_mistral,
    chemin_ffmpeg,
    chemin_locuteurs,
    chemin_reunion,
    chemins_audio_reunion,
    lister_enregistrements,
    lister_reunions,
    nom_dossier_reunion,
    pistes_audio_existantes,
    renommer_dossier_reunion,
    resoudre_chemin_reunion,
    slugifier_titre,
)


def test_chemins_audio_reunion():
    moi, sys = chemins_audio_reunion(Path("/x/2026-04-11_14-30-45/transcription.md"))
    assert moi == Path("/x/2026-04-11_14-30-45/moi")            # sans extension
    assert sys == Path("/x/2026-04-11_14-30-45/systeme")


def test_chemin_locuteurs():
    assert chemin_locuteurs(Path("/x/2026-04-11_14-30-45/transcription.md")) == \
        Path("/x/2026-04-11_14-30-45/locuteurs.md")


def test_chemin_cr_mistral():
    assert chemin_cr_mistral(Path("/x/2026-04-11_14-30-45/transcription.md")) == \
        Path("/x/2026-04-11_14-30-45/CR.md")


def test_lister_reunions_un_dossier_par_reunion(tmp_path):
    d1 = tmp_path / "2026-05-01_10-00-00"
    d1.mkdir()
    (d1 / "transcription.md").write_text("brut")
    noms = [f.parent.name for f in lister_reunions(tmp_path)]
    assert noms == ["2026-05-01_10-00-00"]


def test_lister_reunions_ignore_dossier_sans_transcription(tmp_path):
    (tmp_path / "2026-05-01_10-00-00").mkdir()   # pas de transcription.md dedans
    assert lister_reunions(tmp_path) == []


def test_lister_reunions_ignore_fichiers_a_plat(tmp_path):
    (tmp_path / ".DS_Store").write_bytes(b"\x00")
    assert lister_reunions(tmp_path) == []


def test_lister_reunions_dossier_absent(tmp_path):
    assert lister_reunions(tmp_path / "absent") == []


def test_lister_reunions_tri_recent_dabord(tmp_path):
    for nom in ("2026-05-01_10-00-00", "2026-05-02_09-00-00", "2026-04-30_08-00-00"):
        d = tmp_path / nom
        d.mkdir()
        (d / "transcription.md").write_text("x")
    noms = [f.parent.name for f in lister_reunions(tmp_path)]
    assert noms == ["2026-05-02_09-00-00", "2026-05-01_10-00-00", "2026-04-30_08-00-00"]


def test_lister_enregistrements_reste_pour_le_journal(tmp_path):
    """Le journal (`AAAA-MM-JJ.md`, à plat) est inchangé par docs/43 — pas de dossier,
    pas de dérivés à exclure."""
    (tmp_path / "2026-05-01.md").write_text("journal")
    noms = [f.name for f in lister_enregistrements(tmp_path)]
    assert noms == ["2026-05-01.md"]


def test_pistes_audio_existantes(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("x")
    assert pistes_audio_existantes(md) == []
    (tmp_path / "moi.opus").write_bytes(b"\x00")
    (tmp_path / "systeme.wav").write_bytes(b"\x00")
    noms = sorted(p.name for p in pistes_audio_existantes(md))
    assert noms == ["moi.opus", "systeme.wav"]


def test_chemin_ffmpeg_dev_repli_shutil_which(monkeypatch):
    from debrief_meet.core import ressources

    monkeypatch.setattr(ressources, "est_figee", lambda: False)
    monkeypatch.setattr("shutil.which", lambda nom: f"/usr/bin/{nom}")
    assert chemin_ffmpeg() == "/usr/bin/ffmpeg"


@pytest.mark.skipif(sys.platform.startswith("linux"),
                    reason="Linux n'embarque pas ffmpeg (docs/49 L3 : Depends: ffmpeg)")
def test_chemin_ffmpeg_figee_resout_le_binaire_embarque(monkeypatch, tmp_path):
    """La disposition embarquée diffère selon l'OS (`core/fichiers.chemin_ffmpeg`) :
    `ffmpeg\\ffmpeg.exe` sur Windows (docs/41), `vendor/ffmpeg` sur macOS. Le test suit
    la branche de la plateforme courante plutôt que de coder en dur celle de macOS —
    il échouait sur la gate VM en assertant `vendor/ffmpeg` sous Windows."""
    from debrief_meet.core import ressources

    parties = ("ffmpeg", "ffmpeg.exe") if sys.platform == "win32" else ("vendor", "ffmpeg")
    binaire = Path(tmp_path, *parties)
    binaire.parent.mkdir(parents=True)
    binaire.write_bytes(b"\x00")
    monkeypatch.setattr(ressources, "est_figee", lambda: True)
    monkeypatch.setattr(ressources, "chemin_ressource", lambda *p: Path(tmp_path, *p))
    assert chemin_ffmpeg() == str(binaire)


@pytest.mark.skipif(sys.platform.startswith("linux"),
                    reason="Linux n'embarque pas ffmpeg (docs/49 L3 : Depends: ffmpeg)")
def test_chemin_ffmpeg_figee_binaire_absent_retourne_none(monkeypatch, tmp_path):
    from debrief_meet.core import ressources

    monkeypatch.setattr(ressources, "est_figee", lambda: True)
    monkeypatch.setattr(ressources, "chemin_ressource", lambda *p: Path(tmp_path, *p))
    assert chemin_ffmpeg() is None


def test_chemin_ffmpeg_figee_sur_linux_utilise_le_ffmpeg_systeme(monkeypatch, tmp_path):
    """docs/49 L3 : le `.deb` déclare `Depends: ffmpeg`, rien n'est embarqué. Même
    figée, l'app doit résoudre `/usr/bin/ffmpeg` par le PATH — une app lancée depuis
    le menu GNOME hérite d'un PATH standard, contrairement au Finder/`console=False`.
    Si la branche embarquée s'appliquait, `chemin_ffmpeg()` rendrait None et toute la
    rétention Opus tomberait en repli WAV chez l'utilisateur."""
    from debrief_meet.core import ressources

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ressources, "est_figee", lambda: True)
    monkeypatch.setattr(ressources, "chemin_ressource",
                        lambda *p: Path(tmp_path, *p))  # inexistant : ne doit pas être consulté
    monkeypatch.setattr("shutil.which", lambda nom: f"/usr/bin/{nom}")
    assert chemin_ffmpeg() == "/usr/bin/ffmpeg"


def test_enregistreur_opus_leve_erreur_typee_si_ffmpeg_introuvable(monkeypatch, tmp_path):
    from debrief_meet.core import fichiers

    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: None)
    with pytest.raises(ErreurFfmpegIntrouvable):
        EnregistreurAudioReunion(base_moi=tmp_path / "m", base_systeme=None, format="opus")


def test_enregistreur_wav_16k_mono_streaming(tmp_path):
    enr = EnregistreurAudioReunion(base_moi=tmp_path / "m", base_systeme=None, format="wav")
    enr.ajouter_moi(np.ones(8000, dtype=np.float32) * 0.5)   # 0,5 s @16k
    enr.ajouter_moi(np.ones(8000, dtype=np.float32) * 0.5)   # +0,5 s (streaming)
    enr.terminer()
    moi = tmp_path / "m.wav"
    assert moi.exists()
    with wave.open(str(moi), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        assert w.getnframes() == 16000                        # 2 chunks concaténés


def test_enregistreur_opus_si_ffmpeg(tmp_path):
    import shutil
    if shutil.which("ffmpeg") is None:
        import pytest
        pytest.skip("ffmpeg absent")
    enr = EnregistreurAudioReunion(base_moi=tmp_path / "m", base_systeme=None, format="opus")
    rng = np.random.default_rng(0)
    enr.ajouter_moi(rng.normal(0, 0.2, 16000).astype(np.float32))  # 1 s
    enr.terminer()
    opus = tmp_path / "m.opus"
    assert opus.exists() and opus.stat().st_size > 0
    assert enr.chemin_moi == opus
    # vérifie que l'Opus est réellement DÉCODABLE et fait ~1 s @16k
    import subprocess
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(opus), "-f", "f32le", "-ar", "16000", "-ac", "1", "-"],
        capture_output=True, check=True).stdout
    n = len(np.frombuffer(raw, dtype=np.float32))
    assert 15000 <= n <= 17000                                     # ~16000 éch. (1 s)


# ── ffmpeg embarqué (docs/41) : chemin résolu, flag console, repli ────────────

def test_pistewriter_opus_utilise_le_chemin_resolu_et_le_flag(tmp_path, monkeypatch):
    """`_PisteWriter` opus doit utiliser `chemin_ffmpeg()` (embarqué si présent) et
    masquer la fenêtre console Windows via `CREATE_NO_WINDOW`."""
    import subprocess

    from debrief_meet.core import fichiers

    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: "/chemin/embarque/ffmpeg")

    appels = {}

    class _FauxProc:
        def __init__(self, *args, **kwargs):
            appels["args"] = args
            appels["kwargs"] = kwargs
            self.stdin = None

    monkeypatch.setattr(subprocess, "Popen", _FauxProc)

    fichiers._PisteWriter(tmp_path / "m", "opus", 24)

    assert appels["args"][0][0] == "/chemin/embarque/ffmpeg"
    assert appels["kwargs"]["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_ffmpeg_present_suit_chemin_ffmpeg(monkeypatch):
    from debrief_meet.core import fichiers

    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: None)
    assert fichiers._ffmpeg_present() is False

    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: "/chemin/ffmpeg")
    assert fichiers._ffmpeg_present() is True


def test_enregistreur_auto_bascule_opus_si_ffmpeg_present(tmp_path, monkeypatch):
    import subprocess

    from debrief_meet.core import fichiers

    class _FauxProc:
        def __init__(self, *args, **kwargs):
            self.stdin = None

    monkeypatch.setattr(fichiers, "_ffmpeg_present", lambda: True)
    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: "/chemin/embarque/ffmpeg")
    monkeypatch.setattr(subprocess, "Popen", _FauxProc)
    enr = EnregistreurAudioReunion(base_moi=tmp_path / "m", base_systeme=None, format="auto")
    assert enr.format == "opus"


def test_enregistreur_auto_bascule_wav_si_ffmpeg_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("debrief_meet.core.fichiers._ffmpeg_present", lambda: False)
    enr = EnregistreurAudioReunion(base_moi=tmp_path / "m", base_systeme=None, format="auto")
    assert enr.format == "wav"


def test_enregistreur_piste_none_ignoree(tmp_path):
    enr = EnregistreurAudioReunion(base_moi=None, base_systeme=tmp_path / "s", format="wav")
    enr.ajouter_moi(np.ones(1600, dtype=np.float32))          # piste Moi absente → ignoré
    enr.ajouter_systeme(np.ones(1600, dtype=np.float32) * 0.3)
    enr.terminer()
    assert enr.chemin_moi is None
    with wave.open(str(tmp_path / "s.wav"), "rb") as w:
        assert w.getnframes() == 1600


def test_activer_moi_attache_la_piste_tardivement(tmp_path):
    """Récupération tardive du micro (docs/25) : la piste Moi n'existe pas au
    démarrage (base_moi=None) mais peut être branchée en cours de session."""
    enr = EnregistreurAudioReunion(base_moi=None, base_systeme=None, format="wav")
    assert enr.chemin_moi is None

    enr.activer_moi(tmp_path / "m")
    enr.ajouter_moi(np.ones(1600, dtype=np.float32))
    enr.terminer()

    moi = tmp_path / "m.wav"
    assert enr.chemin_moi == moi
    with wave.open(str(moi), "rb") as w:
        assert w.getnframes() == 1600


def test_activer_moi_second_appel_est_un_no_op(tmp_path):
    enr = EnregistreurAudioReunion(base_moi=None, base_systeme=None, format="wav")
    enr.activer_moi(tmp_path / "m")
    chemin_initial = enr.chemin_moi

    enr.activer_moi(tmp_path / "autre")

    assert enr.chemin_moi == chemin_initial


# ── Slug de titre (docs/43 §3) ─────────────────────────────────────────────────

def test_slugifier_titre_espaces_en_tirets():
    assert slugifier_titre("Point commerce Bastien") == "Point-commerce-Bastien"


def test_slugifier_titre_accents_conserves():
    assert slugifier_titre("Réunion R&D — sprint 12") == "Réunion-R&D-sprint-12"


def test_slugifier_titre_caracteres_interdits_retires():
    assert slugifier_titre("Suivi client : Acme/Corp") == "Suivi-client-AcmeCorp"


def test_slugifier_titre_vide():
    assert slugifier_titre("   ") == ""
    assert slugifier_titre("") == ""


def test_slugifier_titre_tirets_multiples_replies():
    assert slugifier_titre("Point   commerce -- Bastien") == "Point-commerce-Bastien"


def test_slugifier_titre_tronque():
    long_titre = "x" * 100
    assert len(slugifier_titre(long_titre)) == 60


def test_slugifier_titre_tous_caracteres_interdits():
    assert slugifier_titre('/\\:*?"<>|') == ""


# ── Nom de dossier / chemin d'une nouvelle réunion (docs/43 §2, §5.1) ──────────

def test_nom_dossier_reunion_sans_titre():
    debut = datetime(2026, 7, 27, 15, 30, 45)
    assert nom_dossier_reunion(debut) == "2026-07-27_15-30-45"


def test_nom_dossier_reunion_avec_titre():
    debut = datetime(2026, 7, 27, 16, 5, 12)
    assert nom_dossier_reunion(debut, "Point commerce Bastien") == \
        "2026-07-27_16-05-12_Point-commerce-Bastien"


def test_nom_dossier_reunion_titre_vide_egale_sans_titre():
    debut = datetime(2026, 7, 27, 15, 30, 45)
    assert nom_dossier_reunion(debut, "") == nom_dossier_reunion(debut)


def test_chemin_reunion_dossier_precision_seconde(tmp_path):
    debut = datetime(2026, 7, 27, 15, 30, 45)
    assert chemin_reunion(tmp_path, debut) == \
        tmp_path / "2026-07-27_15-30-45" / "transcription.md"


def test_chemin_reunion_avec_titre(tmp_path):
    debut = datetime(2026, 7, 27, 16, 5, 12)
    assert chemin_reunion(tmp_path, debut, "Point commerce Bastien") == \
        tmp_path / "2026-07-27_16-05-12_Point-commerce-Bastien" / "transcription.md"


def test_chemin_reunion_suffixe_si_collision(tmp_path):
    debut = datetime(2026, 7, 27, 15, 30, 45)
    (tmp_path / "2026-07-27_15-30-45").mkdir()
    assert chemin_reunion(tmp_path, debut) == \
        tmp_path / "2026-07-27_15-30-45-2" / "transcription.md"
    (tmp_path / "2026-07-27_15-30-45-2").mkdir()
    assert chemin_reunion(tmp_path, debut) == \
        tmp_path / "2026-07-27_15-30-45-3" / "transcription.md"


def test_chemin_reunion_n_ecrase_pas_la_precedente(tmp_path):
    debut = datetime(2026, 7, 27, 15, 30, 45)
    p1 = chemin_reunion(tmp_path, debut)
    EcrivainReunion(p1, debut).creer()
    p2 = chemin_reunion(tmp_path, debut)
    EcrivainReunion(p2, debut).creer()
    assert p1 != p2
    assert p1.exists() and p2.exists()      # les deux réunions coexistent


def _ecrivain(tmp_path, heure="14:30:00", nom="reunion"):
    debut = datetime.strptime(f"2026-04-11 {heure}", "%Y-%m-%d %H:%M:%S")
    chemin = tmp_path / nom / "transcription.md"
    return EcrivainReunion(chemin, debut)


def test_creer_ecrit_entete(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer()
    assert "# Réunion —" in e.chemin.read_text(encoding="utf-8")


def test_creer_repli_micro_seul(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer(avec_systeme=False)
    assert "⚠️" in e.chemin.read_text(encoding="utf-8")


def test_creer_sans_repli_pas_de_warning(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer(avec_systeme=True)
    assert "⚠️" not in e.chemin.read_text(encoding="utf-8")


def test_creer_repli_systeme_seul(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer(avec_micro=False)
    assert "Microphone non disponible" in e.chemin.read_text(encoding="utf-8")


def test_creer_micro_ok_pas_de_warning_micro(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer(avec_systeme=True, avec_micro=True)
    assert "Microphone non disponible" not in e.chemin.read_text(encoding="utf-8")


def test_placeholder_marque_en_attente(tmp_path):
    from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE, transcription_en_attente
    e = _ecrivain(tmp_path)
    e.creer_placeholder()
    contenu = e.chemin.read_text(encoding="utf-8")
    assert MARQUEUR_EN_ATTENTE in contenu
    assert contenu.startswith("# Réunion —")
    assert transcription_en_attente(e.chemin) is True


def test_transcription_non_en_attente_apres_creer(tmp_path):
    from debrief_meet.core.fichiers import transcription_en_attente
    e = _ecrivain(tmp_path)
    e.creer()
    assert transcription_en_attente(e.chemin) is False


def test_transcription_en_attente_fichier_absent(tmp_path):
    from debrief_meet.core.fichiers import transcription_en_attente
    assert transcription_en_attente(tmp_path / "absent.md") is False


def test_ajouter_tranche_format_complet(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer()
    e.ajouter_tranche("Bonjour à tous.", "Oui bonjour.", 300.0)
    contenu = e.chemin.read_text(encoding="utf-8")
    assert "**Moi :**" in contenu
    assert "**Participants :**" in contenu


def test_ajouter_tranche_vide_skip(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer()
    contenu_avant = e.chemin.read_text(encoding="utf-8")
    e.ajouter_tranche("", "", 60.0)
    assert e.chemin.read_text(encoding="utf-8") == contenu_avant


def test_ajouter_tranche_seulement_moi(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer()
    e.ajouter_tranche("J'ai dit quelque chose.", "", 120.0)
    contenu = e.chemin.read_text(encoding="utf-8")
    assert "**Moi :**" in contenu
    assert "**Participants :**" not in contenu


def test_ajouter_tranche_seulement_participants(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer()
    e.ajouter_tranche("", "Les participants ont parlé.", 120.0)
    contenu = e.chemin.read_text(encoding="utf-8")
    assert "**Participants :**" in contenu
    assert "**Moi :**" not in contenu


def test_ajouter_tranche_incremental(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer()
    e.ajouter_tranche("un", "", 60.0)
    e.ajouter_tranche("deux", "", 120.0)
    e.ajouter_tranche("trois", "", 180.0)
    contenu = e.chemin.read_text(encoding="utf-8")
    assert contenu.count("##") == 3


def test_elapsed_format_mm_ss(tmp_path):
    e = _ecrivain(tmp_path)
    e.creer()
    e.ajouter_tranche("texte", "", 90.0)
    contenu = e.chemin.read_text(encoding="utf-8")
    assert "01:30" in contenu


def test_chemin_property(tmp_path):
    chemin = tmp_path / "sub" / "fichier.md"
    debut = datetime(2026, 4, 11, 14, 30)
    e = EcrivainReunion(chemin, debut)
    assert e.chemin == chemin


# ── Métadonnées réunion : date/heure depuis le nom du dossier (docs/14, docs/43) ─

from debrief_meet.core.fichiers import (  # noqa: E402
    date_heure_reunion,
    definir_duree,
    definir_titre,
    duree_reunion,
    formater_duree,
    titre_reunion,
)


def test_date_heure_reunion_dossier_seconde(tmp_path):
    md = tmp_path / "2026-06-29_10-02-30" / "transcription.md"
    assert date_heure_reunion(md) == datetime(2026, 6, 29, 10, 2, 30)


def test_date_heure_reunion_sans_secondes_est_none(tmp_path):
    """Les secondes sont obligatoires depuis la normalisation des dossiers legacy
    (docs/43 §7) : un nom à la minute seule n'est plus un nom de réunion valide."""
    md = tmp_path / "2026-06-29_10-02" / "transcription.md"
    assert date_heure_reunion(md) is None


def test_date_heure_reunion_ignore_le_compteur_de_collision(tmp_path):
    """Le compteur `-2` ajouté en fin de nom (§2.2) n'altère pas la date lue."""
    md = tmp_path / "2026-06-29_10-02-30-2" / "transcription.md"
    assert date_heure_reunion(md) == datetime(2026, 6, 29, 10, 2, 30)


def test_date_heure_reunion_dossier_titre_slug_ignore_pour_la_date(tmp_path):
    md = tmp_path / "2026-07-27_16-05-12_Point-commerce-Bastien" / "transcription.md"
    assert date_heure_reunion(md) == datetime(2026, 7, 27, 16, 5, 12)


def test_date_heure_reunion_slug_contenant_underscore(tmp_path):
    md = tmp_path / "2026-07-27_16-05-12_Suivi_client_Acme" / "transcription.md"
    assert date_heure_reunion(md) == datetime(2026, 7, 27, 16, 5, 12)


def test_date_heure_reunion_nom_journal_est_none(tmp_path):
    assert date_heure_reunion(tmp_path / "2026-06-29.md") is None    # entrée de journal


def test_date_heure_reunion_date_invalide(tmp_path):
    md = tmp_path / "2026-13-40_25-99-99" / "transcription.md"
    assert date_heure_reunion(md) is None    # motif reconnu, mais datetime() refuse


# ── Renommage du dossier sur changement de titre (docs/43 §6) ──────────────────

def _dossier_reunion(tmp_path, nom):
    d = tmp_path / nom
    d.mkdir()
    return d / "transcription.md"


def test_renommer_dossier_ajout_de_titre(tmp_path):
    md = _dossier_reunion(tmp_path, "2026-07-27_15-30-45")
    nouveau = renommer_dossier_reunion(md, "Point commerce Bastien")
    assert nouveau == tmp_path / "2026-07-27_15-30-45_Point-commerce-Bastien" / "transcription.md"
    assert nouveau.parent.exists()
    assert not md.parent.exists()


def test_renommer_dossier_changement_de_titre(tmp_path):
    md = _dossier_reunion(tmp_path, "2026-07-27_15-30-45_Ancien-titre")
    nouveau = renommer_dossier_reunion(md, "Nouveau titre")
    assert nouveau.parent.name == "2026-07-27_15-30-45_Nouveau-titre"


def test_renommer_dossier_titre_vide_revient_a_l_horodatage(tmp_path):
    md = _dossier_reunion(tmp_path, "2026-07-27_15-30-45_Ancien-titre")
    nouveau = renommer_dossier_reunion(md, "")
    assert nouveau.parent.name == "2026-07-27_15-30-45"


def test_renommer_dossier_no_op_si_nom_inchange(tmp_path):
    md = _dossier_reunion(tmp_path, "2026-07-27_15-30-45_Point-commerce-Bastien")
    nouveau = renommer_dossier_reunion(md, "Point commerce Bastien")
    assert nouveau == md


def test_renommer_dossier_collision_cible_existante(tmp_path):
    md = _dossier_reunion(tmp_path, "2026-07-27_15-30-45")
    (tmp_path / "2026-07-27_15-30-45_Titre").mkdir()   # cible déjà prise
    nouveau = renommer_dossier_reunion(md, "Titre")
    assert nouveau.parent.name == "2026-07-27_15-30-45_Titre-2"


def test_renommer_dossier_preserve_l_horodatage_a_la_seconde(tmp_path):
    """Le renommage ne touche qu'au slug : l'horodatage d'origine est repris tel quel."""
    md = _dossier_reunion(tmp_path, "2026-07-06_09-56-04")
    nouveau = renommer_dossier_reunion(md, "Titre")
    assert nouveau.parent.name == "2026-07-06_09-56-04_Titre"


def test_renommer_dossier_preserve_le_compteur_de_collision(tmp_path):
    """Deux réunions distinctes séparées par un compteur ne doivent pas fusionner :
    le suffixe `-2` fait partie du bloc horodaté conservé."""
    md = _dossier_reunion(tmp_path, "2026-07-06_09-56-04-2")
    nouveau = renommer_dossier_reunion(md, "Titre")
    assert nouveau.parent.name == "2026-07-06_09-56-04-2_Titre"


# ── Titre éditable (H1 du .md) ─────────────────────────────────────────────────

def test_titre_reunion_defaut_est_none(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    assert titre_reunion(md) is None                    # titre par défaut = pas de titre custom


def test_titre_reunion_custom(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Budget Q3\n\ncorps", encoding="utf-8")
    assert titre_reunion(md) == "Budget Q3"


def test_titre_reunion_fichier_absent(tmp_path):
    assert titre_reunion(tmp_path / "absent" / "transcription.md") is None


def test_definir_titre_puis_relecture(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    definir_titre(md, "Budget Q3")
    assert titre_reunion(md) == "Budget Q3"
    assert "corps" in md.read_text(encoding="utf-8")    # le reste est préservé


def test_definir_titre_vide_restaure_le_defaut(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Budget Q3\n\ncorps", encoding="utf-8")
    definir_titre(md, "   ")
    assert titre_reunion(md) is None
    assert md.read_text(encoding="utf-8").startswith("# Réunion — 2026-06-29 10:02")


def test_definir_titre_preserve_la_duree(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Réunion — 2026-06-29 10:02\n<!-- duree_s: 600 -->\n\ncorps", encoding="utf-8")
    definir_titre(md, "Budget Q3")
    assert titre_reunion(md) == "Budget Q3"
    assert duree_reunion(md) == 600                      # durée intacte


def test_definir_titre_vide_sans_date_utilise_le_nom_du_dossier(tmp_path):
    """Repli quand le nom du dossier ne suit pas le schéma réunion (ex. dossier
    renommé manuellement en dehors de l'app) : pas de crash, on retombe sur le nom
    du dossier plutôt qu'un `.stem` de fichier générique (`transcription`)."""
    md = tmp_path / "dossier-quelconque" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Un titre\n\ncorps", encoding="utf-8")
    definir_titre(md, "   ")
    assert md.read_text(encoding="utf-8").startswith("# Réunion — dossier-quelconque")


# ── Durée (commentaire HTML + replis) ──────────────────────────────────────────

def test_definir_duree_ecrit_un_commentaire(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    definir_duree(md, 1834)
    assert duree_reunion(md) == 1834
    assert "<!-- duree_s: 1834 -->" in md.read_text(encoding="utf-8")


def test_definir_duree_est_idempotent(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    definir_duree(md, 100)
    definir_duree(md, 250)                               # remplace, pas de doublon
    contenu = md.read_text(encoding="utf-8")
    assert contenu.count("duree_s") == 1
    assert duree_reunion(md) == 250


def test_definir_duree_conserve_le_marqueur_en_attente(tmp_path):
    from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE, transcription_en_attente
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text(f"# Réunion — 2026-06-29 10:02\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    definir_duree(md, 42)
    assert transcription_en_attente(md) is True
    assert duree_reunion(md) == 42


def test_duree_reunion_repli_audio_wav(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")   # pas de commentaire
    # piste de 2 s @16k → durée ≈ 2 s
    enr = EnregistreurAudioReunion(
        base_moi=md.parent / "moi", base_systeme=None, format="wav")
    enr.ajouter_moi(np.zeros(32000, dtype=np.float32))
    enr.terminer()
    assert duree_reunion(md) == 2


def test_duree_reunion_repli_derniere_tranche(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text(
        "# Réunion — 2026-06-29 10:02\n\n"
        "---\n\n## 10:05 (05:00)\n\n**Moi :** a\n\n"
        "---\n\n## 10:32 (30:15)\n\n**Moi :** b\n\n",
        encoding="utf-8")
    assert duree_reunion(md) == 30 * 60 + 15             # dernière tranche : 30:15


def test_duree_reunion_inconnue(tmp_path):
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    assert duree_reunion(md) is None


def test_duree_reunion_priorite_au_commentaire(tmp_path):
    """Le commentaire stocké prime sur le repli (tranche)."""
    md = tmp_path / "2026-06-29_10-02-00" / "transcription.md"
    md.parent.mkdir()
    md.write_text(
        "# Réunion — 2026-06-29 10:02\n<!-- duree_s: 1800 -->\n\n## 10:05 (05:00)\n\n**Moi :** a\n",
        encoding="utf-8")
    assert duree_reunion(md) == 1800


# ── Format d'affichage de la durée ─────────────────────────────────────────────

def test_formater_duree_sous_une_heure():
    assert formater_duree(32 * 60) == "32 min"


def test_formater_duree_au_dela_dune_heure():
    assert formater_duree(65 * 60) == "1 h 05"


def test_formater_duree_pile_une_heure():
    assert formater_duree(3600) == "1 h 00"


def test_formater_duree_inconnue():
    assert formater_duree(None) == "—"


# ── Aperçu journal (colonne « note », refonte design) ──────────────────────────

def test_apercu_journal_derniere_ligne_utile(tmp_path):
    md = tmp_path / "2026-07-04.md"
    EcrivainJournal(tmp_path).ajouter_entree(
        "Première entrée", horodatage=datetime(2026, 7, 4, 9, 0)
    )
    EcrivainJournal(tmp_path).ajouter_entree(
        "Deuxième entrée", horodatage=datetime(2026, 7, 4, 9, 5)
    )
    assert apercu_journal(md) == "Deuxième entrée"


def test_apercu_journal_tronque(tmp_path):
    md = tmp_path / "j.md"
    md.write_text("# Titre\n\n## 10:00\n\n" + "x" * 100 + "\n\n---\n", encoding="utf-8")
    apercu = apercu_journal(md, longueur=20)
    assert len(apercu) == 20
    assert apercu.endswith("…")


def test_apercu_journal_fichier_absent(tmp_path):
    assert apercu_journal(tmp_path / "absent.md") == ""


def test_apercu_journal_vide(tmp_path):
    md = tmp_path / "j.md"
    md.write_text("# Titre\n\n---\n", encoding="utf-8")
    assert apercu_journal(md) == ""


# ── prechauffer_ffmpeg() — scan antivirus payé au lancement, pas au 1ᵉʳ enregistrement ──

def test_prechauffage_sans_ffmpeg_ne_fait_rien(monkeypatch):
    from debrief_meet.core import fichiers
    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: None)
    assert fichiers.prechauffer_ffmpeg() is None


def test_prechauffage_lance_ffmpeg_version_en_arriere_plan(monkeypatch):
    import subprocess
    from debrief_meet.core import fichiers
    appels = []
    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: "/chemin/ffmpeg")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: appels.append(cmd))
    thread = fichiers.prechauffer_ffmpeg()
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert appels == [["/chemin/ffmpeg", "-version"]]


def test_prechauffage_echec_silencieux(monkeypatch, tmp_path):
    # Binaire inexistant : subprocess.run lève FileNotFoundError — absorbé (DEBUG).
    from debrief_meet.core import fichiers
    monkeypatch.setattr(fichiers, "chemin_ffmpeg", lambda: str(tmp_path / "absent.exe"))
    thread = fichiers.prechauffer_ffmpeg()
    thread.join(timeout=5)
    assert not thread.is_alive()


# ── Dédoublonnage inter-pistes à la fusion (docs/48 §4.1) ────────────────────────

def _entrelaces_(moi, participants):
    from debrief_meet.core.fichiers import _entrelaces
    return _entrelaces("x", "y", moi, participants)


def test_dedup_ecarte_le_doublon_micro():
    # Écho HP→micro non annulé : la phrase du correspondant est transcrite sur les
    # deux pistes (décalage inter-pistes ≤ 0,7 s mesuré) → la copie micro est écartée.
    blocs = _entrelaces_(
        moi=[(10.0, "Je vous propose plutôt quatorze heures lundi ou mardi.")],
        participants=[(10.7, "Je vous propose plutôt 14h lundi ou mardi.")])
    assert blocs == [("Participants", "Je vous propose plutôt 14h lundi ou mardi.")]


def test_dedup_variantes_de_transcription():
    # Les deux captations du même propos divergent un peu (« Rob calme » / « Bastien
    # calme ») : similarité ≥ 0,8 → doublon quand même.
    blocs = _entrelaces_(
        moi=[(5.0, "il y a Rob calme son collègue pour la réunion il le calme")],
        participants=[(5.6, "Et Bastien calme son collègue pendant la réunion. Il le calme.")])
    assert len(blocs) == 1 and blocs[0][0] == "Participants"


def test_dedup_hors_fenetre_conserve():
    blocs = _entrelaces_(
        moi=[(2.0, "Je vous propose plutôt quatorze heures lundi ou mardi.")],
        participants=[(9.0, "Je vous propose plutôt quatorze heures lundi ou mardi.")])
    assert [b[0] for b in blocs] == ["Moi", "Participants"]


def test_dedup_repetition_courte_legitime_conservee():
    # « Oui. » des deux camps à 2 s d'écart = accord, pas un écho.
    blocs = _entrelaces_(
        moi=[(3.0, "Oui, ça marche.")],
        participants=[(4.0, "Oui, ça marche.")])
    assert [b[0] for b in blocs] == ["Moi", "Participants"]


def test_dedup_textes_differents_conserves():
    blocs = _entrelaces_(
        moi=[(3.0, "Nous avons soixante-treize mille euros de factures en attente.")],
        participants=[(3.5, "Je fais un point de trésorerie et je vous envoie un mail récapitulatif.")])
    assert [b[0] for b in blocs] == ["Moi", "Participants"]


def test_dedup_limite_le_fragment_court_reste_conserve():
    """Limite ASSUMÉE du critère, mesurée sur la réunion du 2026-08-18.

    Ce doublon (fragment court noyé dans un long segment système) plafonne à 0,70
    d'inclusion, et un tour parfaitement légitime de la même réunion — « Oui, c'est censé
    être une vitrine. », qui reformule le propos du correspondant — en fait 0,71. Les deux
    sont indiscernables : aucun seuil ne les sépare. Il est placé au-dessus des deux, parce
    qu'un doublon qui subsiste se voit et se corrige à la lecture, alors qu'un tour
    supprimé est une information définitivement perdue."""
    blocs = _entrelaces_(
        moi=[(1700.0, "Mais tu vois, j'avais réfléchi en termes de séparation.")],
        participants=[(1700.2, "Donc, en gros, voilà. Sinon, j'avais réfléchi en termes de "
                               "séparation. En gros, vu qu'on va se retrouver avec une "
                               "plateforme de démo qui va servir autant pour nous.")])
    assert [b[0] for b in blocs] == ["Moi", "Participants"]


def test_dedup_reformulation_legitime_conservee():
    """Le contre-exemple qui fixe le seuil : Sylvain reprend les mots du correspondant pour
    les corriger (« démo technique » → « vitrine »). 0,71 d'inclusion, et c'est la chute de
    l'échange — l'écarter changerait le sens du compte-rendu."""
    blocs = _entrelaces_(
        moi=[(300.0, "Oui, c'est censé être une vitrine.")],
        participants=[(299.0, "Enfin, pas problématique, mais ça fait quand même un... "
                              "C'est censé être une démo technique. Donc, tu vois, il "
                              "manque quand même quelque chose.")])
    assert [b[0] for b in blocs] == ["Participants", "Moi"]   # la réplique est conservée


def test_dedup_reformulation_partielle_ecartee():
    """Même propos, mots différents au milieu (0,74 de ratio mesuré sur le terrain) :
    sous le seuil de similarité, mais couvert par le segment système."""
    blocs = _entrelaces_(
        moi=[(1695.0, "Potentiellement on est des machines qui soient réservées à nous pour "
                      "les démos, alors une seule ce sera largement suffisant.")],
        participants=[(1695.4, "Potentiellement qu'on ait des poules de machines qui soient "
                               "réservées à nous pour les démos. Alors, une seule, ce sera "
                               "largement suffisant. Et le reste pour les clients.")])
    assert len(blocs) == 1 and blocs[0][0] == "Participants"


def test_dedup_inclusion_jamais_dans_l_autre_sens():
    """Écho renvoyé par le poste d'en face : un court fragment de MA phrase revient sur la
    piste système. C'est toujours la copie micro qui serait écartée — donc ici on perdrait
    30 mots de l'utilisateur pour 7 mots d'écho. La couverture se mesure sur le micro."""
    blocs = _entrelaces_(
        moi=[(40.0, "chez Olféo et avant chez le prestataire de sauvegarde je ne sais plus "
                    "lequel mais bon ça c'est autre chose par contre si tu veux faire ça")],
        participants=[(40.3, "Par contre, si tu veux faire ça,")])
    assert [b[0] for b in blocs] == ["Moi", "Participants"]


def test_dedup_inclusion_ignore_les_segments_micro_tres_courts():
    """Sous 6 mots, l'inclusion ne décide de rien : une relance banale se retrouve mot pour
    mot dans n'importe quelle phrase longue du correspondant."""
    blocs = _entrelaces_(
        moi=[(12.0, "Oui, tout à fait, exactement.")],
        participants=[(12.2, "Oui, tout à fait, exactement ce que je disais tantôt à propos "
                             "du calendrier de déploiement chez le client.")])
    assert [b[0] for b in blocs] == ["Moi", "Participants"]


# ── resoudre_chemin_reunion : job de fond + dossier renommé sous ses pieds ──────
#
# 5 échecs réels sur le poste de Sylvain entre le 2026-07-29 et le 2026-08-26 : un job
# (CR Mistral, transcription différée) tenait un chemin absolu capturé à son lancement
# pendant que l'association BlueMind renommait le dossier. Cf. docs/43 §6.


def _dossier_reunion(tmp_path, nom="2026-08-26_16-20-54"):
    d = tmp_path / nom
    d.mkdir()
    (d / "transcription.md").write_text("# Réunion\n", encoding="utf-8")
    return d / "transcription.md"


def test_resoudre_no_op_si_le_dossier_existe_toujours(tmp_path):
    md = _dossier_reunion(tmp_path)
    assert resoudre_chemin_reunion(md) == md


def test_resoudre_retrouve_le_dossier_renomme(tmp_path):
    md = _dossier_reunion(tmp_path)
    nouveau = renommer_dossier_reunion(md, "Point Acme")     # slug ajouté

    # Le job, lui, tient toujours l'ancien chemin.
    assert resoudre_chemin_reunion(md) == nouveau
    assert nouveau.parent.name == "2026-08-26_16-20-54_Point-Acme"


def test_resoudre_retrouve_apres_retrait_du_titre(tmp_path):
    """Le renommage marche dans les deux sens : titre effacé → dossier horodaté seul."""
    md = _dossier_reunion(tmp_path, "2026-08-26_16-20-54_Ancien-titre")
    nu = renommer_dossier_reunion(md, "")
    assert resoudre_chemin_reunion(md) == nu


def test_resoudre_conserve_le_nom_de_fichier_demande(tmp_path):
    """Le helper sert aussi pour `CR.md` et `locuteurs.md`, pas seulement la transcription."""
    md = _dossier_reunion(tmp_path)
    nouveau = renommer_dossier_reunion(md, "Point Acme")
    cr_avant = chemin_cr_mistral(md)
    assert resoudre_chemin_reunion(cr_avant) == nouveau.with_name("CR.md")


def test_resoudre_inchange_si_la_reunion_a_ete_supprimee(tmp_path):
    """Réunion supprimée (et non renommée) : on rend le chemin tel quel — l'appelant
    échoue comme avant, avec le même message. Réparer un renommage n'est pas inventer
    une réunion."""
    md = _dossier_reunion(tmp_path)
    import shutil
    shutil.rmtree(md.parent)
    assert resoudre_chemin_reunion(md) == md


def test_resoudre_inchange_si_plusieurs_dossiers_partagent_l_horodatage(tmp_path):
    """Le compteur de collision (`-2`) est posé APRÈS le slug : deux réunions démarrées
    à la même seconde partagent donc le préfixe horodaté. Ambiguïté → on ne devine pas,
    sous peine d'écrire le CR dans la mauvaise réunion."""
    md = _dossier_reunion(tmp_path)
    renommer_dossier_reunion(md, "Titre A")
    autre = _dossier_reunion(tmp_path)                          # même horodatage, recréé
    renommer_dossier_reunion(autre, "Titre B")
    assert resoudre_chemin_reunion(md) == md


def test_resoudre_ignore_les_dossiers_d_un_autre_horodatage(tmp_path):
    md = _dossier_reunion(tmp_path)
    voisine = _dossier_reunion(tmp_path, "2026-08-26_17-06-40")
    renommer_dossier_reunion(voisine, "Une autre réunion")
    import shutil
    shutil.rmtree(md.parent)
    assert resoudre_chemin_reunion(md) == md                     # surtout pas la voisine


def test_resoudre_inchange_sur_un_nom_non_horodate(tmp_path):
    """Journal (`AAAA-MM-JJ.md`, à plat) ou chemin arbitraire : rien à résoudre."""
    md = tmp_path / "dossier-disparu" / "notes.md"
    assert resoudre_chemin_reunion(md) == md
