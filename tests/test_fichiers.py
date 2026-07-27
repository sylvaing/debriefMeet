from __future__ import annotations

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
    pistes_audio_existantes,
)


def test_chemins_audio_reunion():
    moi, sys = chemins_audio_reunion(Path("/x/2026-04-11_14-30.md"))
    assert moi == Path("/x/2026-04-11_14-30_moi")            # sans extension
    assert sys == Path("/x/2026-04-11_14-30_systeme")


def test_chemin_locuteurs():
    assert chemin_locuteurs(Path("/x/2026-04-11_14-30.md")) == \
        Path("/x/2026-04-11_14-30_locuteurs.md")


def test_lister_enregistrements_exclut_locuteurs(tmp_path):
    (tmp_path / "2026-05-01_10-00.md").write_text("brut")
    (tmp_path / "2026-05-01_10-00_locuteurs.md").write_text("dérivé")
    noms = [f.name for f in lister_enregistrements(tmp_path)]
    assert noms == ["2026-05-01_10-00.md"]                   # le _locuteurs est exclu


def test_chemin_cr_mistral():
    assert chemin_cr_mistral(Path("/x/2026-04-11_14-30.md")) == \
        Path("/x/2026-04-11_14-30_CR.md")


def test_lister_enregistrements_exclut_cr_mistral(tmp_path):
    """Le CR Mistral (`*_CR.md`, docs/42) est un dérivé, pas une réunion à part
    entière — sinon il apparaît en fantôme dans l'Historique (sans date/durée,
    impossible à associer ou à diariser)."""
    (tmp_path / "2026-05-01_10-00.md").write_text("brut")
    (tmp_path / "2026-05-01_10-00_CR.md").write_text("# CR — Sujet — 2026-05-01")
    noms = [f.name for f in lister_enregistrements(tmp_path)]
    assert noms == ["2026-05-01_10-00.md"]


def test_pistes_audio_existantes(tmp_path):
    md = tmp_path / "r.md"
    md.write_text("x")
    assert pistes_audio_existantes(md) == []
    (tmp_path / "r_moi.opus").write_bytes(b"\x00")
    (tmp_path / "r_systeme.wav").write_bytes(b"\x00")
    noms = sorted(p.name for p in pistes_audio_existantes(md))
    assert noms == ["r_moi.opus", "r_systeme.wav"]


def test_chemin_ffmpeg_dev_repli_shutil_which(monkeypatch):
    from debrief_meet.core import ressources

    monkeypatch.setattr(ressources, "est_figee", lambda: False)
    monkeypatch.setattr("shutil.which", lambda nom: f"/usr/bin/{nom}")
    assert chemin_ffmpeg() == "/usr/bin/ffmpeg"


def test_chemin_ffmpeg_figee_resout_le_binaire_embarque(monkeypatch, tmp_path):
    from debrief_meet.core import ressources

    binaire = tmp_path / "vendor" / "ffmpeg"
    binaire.parent.mkdir()
    binaire.write_bytes(b"\x00")
    monkeypatch.setattr(ressources, "est_figee", lambda: True)
    monkeypatch.setattr(ressources, "chemin_ressource", lambda *p: Path(tmp_path, *p))
    assert chemin_ffmpeg() == str(binaire)


def test_chemin_ffmpeg_figee_binaire_absent_retourne_none(monkeypatch, tmp_path):
    from debrief_meet.core import ressources

    monkeypatch.setattr(ressources, "est_figee", lambda: True)
    monkeypatch.setattr(ressources, "chemin_ressource", lambda *p: Path(tmp_path, *p))
    assert chemin_ffmpeg() is None


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


def test_chemin_reunion_nom_a_la_minute(tmp_path):
    debut = datetime.strptime("2026-04-11 14:30", "%Y-%m-%d %H:%M")
    assert chemin_reunion(tmp_path, debut) == tmp_path / "2026-04-11_14-30.md"


def test_chemin_reunion_suffixe_si_collision(tmp_path):
    """2ᵉ réunion dans la même minute → suffixe -2 (pas d'écrasement)."""
    debut = datetime.strptime("2026-04-11 14:30", "%Y-%m-%d %H:%M")
    (tmp_path / "2026-04-11_14-30.md").write_text("réunion 1", encoding="utf-8")
    assert chemin_reunion(tmp_path, debut) == tmp_path / "2026-04-11_14-30-2.md"
    # une 3ᵉ → -3
    (tmp_path / "2026-04-11_14-30-2.md").write_text("réunion 2", encoding="utf-8")
    assert chemin_reunion(tmp_path, debut) == tmp_path / "2026-04-11_14-30-3.md"


def test_chemin_reunion_n_ecrase_pas_la_precedente(tmp_path):
    debut = datetime.strptime("2026-04-11 14:30", "%Y-%m-%d %H:%M")
    p1 = chemin_reunion(tmp_path, debut)
    EcrivainReunion(p1, debut).creer()
    p2 = chemin_reunion(tmp_path, debut)
    EcrivainReunion(p2, debut).creer()
    assert p1 != p2
    assert p1.exists() and p2.exists()      # les deux réunions coexistent


def _ecrivain(tmp_path, heure="14:30"):
    debut = datetime.strptime(f"2026-04-11 {heure}", "%Y-%m-%d %H:%M")
    chemin = tmp_path / "reunion.md"
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


# ── Métadonnées réunion : date/heure depuis le nom (docs/14) ───────────────────

from debrief_meet.core.fichiers import (  # noqa: E402
    date_heure_reunion,
    definir_duree,
    definir_titre,
    duree_reunion,
    formater_duree,
    titre_reunion,
)


def test_date_heure_reunion_depuis_le_nom(tmp_path):
    assert date_heure_reunion(tmp_path / "2026-06-29_10-02.md") == datetime(2026, 6, 29, 10, 2)


def test_date_heure_reunion_avec_suffixe_collision(tmp_path):
    assert date_heure_reunion(tmp_path / "2026-06-29_10-02-3.md") == datetime(2026, 6, 29, 10, 2)


def test_date_heure_reunion_nom_journal_est_none(tmp_path):
    assert date_heure_reunion(tmp_path / "2026-06-29.md") is None    # entrée de journal


def test_date_heure_reunion_date_invalide(tmp_path):
    assert date_heure_reunion(tmp_path / "2026-13-40_25-99.md") is None


# ── Titre éditable (H1 du .md) ─────────────────────────────────────────────────

def test_titre_reunion_defaut_est_none(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    assert titre_reunion(md) is None                    # titre par défaut = pas de titre custom


def test_titre_reunion_defaut_depuis_stem_est_none(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29_10-02\n\ncorps", encoding="utf-8")
    assert titre_reunion(md) is None                    # repli sur le stem = pas de titre custom


def test_titre_reunion_custom(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Budget Q3\n\ncorps", encoding="utf-8")
    assert titre_reunion(md) == "Budget Q3"


def test_titre_reunion_fichier_absent(tmp_path):
    assert titre_reunion(tmp_path / "absent.md") is None


def test_definir_titre_puis_relecture(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    definir_titre(md, "Budget Q3")
    assert titre_reunion(md) == "Budget Q3"
    assert "corps" in md.read_text(encoding="utf-8")    # le reste est préservé


def test_definir_titre_vide_restaure_le_defaut(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Budget Q3\n\ncorps", encoding="utf-8")
    definir_titre(md, "   ")
    assert titre_reunion(md) is None
    assert md.read_text(encoding="utf-8").startswith("# Réunion — 2026-06-29 10:02")


def test_definir_titre_preserve_la_duree(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29 10:02\n<!-- duree_s: 600 -->\n\ncorps", encoding="utf-8")
    definir_titre(md, "Budget Q3")
    assert titre_reunion(md) == "Budget Q3"
    assert duree_reunion(md) == 600                      # durée intacte


# ── Durée (commentaire HTML + replis) ──────────────────────────────────────────

def test_definir_duree_ecrit_un_commentaire(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    definir_duree(md, 1834)
    assert duree_reunion(md) == 1834
    assert "<!-- duree_s: 1834 -->" in md.read_text(encoding="utf-8")


def test_definir_duree_est_idempotent(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    definir_duree(md, 100)
    definir_duree(md, 250)                               # remplace, pas de doublon
    contenu = md.read_text(encoding="utf-8")
    assert contenu.count("duree_s") == 1
    assert duree_reunion(md) == 250


def test_definir_duree_conserve_le_marqueur_en_attente(tmp_path):
    from debrief_meet.core.fichiers import MARQUEUR_EN_ATTENTE, transcription_en_attente
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text(f"# Réunion — 2026-06-29 10:02\n\n> {MARQUEUR_EN_ATTENTE}\n\n", encoding="utf-8")
    definir_duree(md, 42)
    assert transcription_en_attente(md) is True
    assert duree_reunion(md) == 42


def test_duree_reunion_repli_audio_wav(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")   # pas de commentaire
    # piste de 2 s @16k → durée ≈ 2 s
    enr = EnregistreurAudioReunion(
        base_moi=tmp_path / "2026-06-29_10-02_moi", base_systeme=None, format="wav")
    enr.ajouter_moi(np.zeros(32000, dtype=np.float32))
    enr.terminer()
    assert duree_reunion(md) == 2


def test_duree_reunion_repli_derniere_tranche(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text(
        "# Réunion — 2026-06-29 10:02\n\n"
        "---\n\n## 10:05 (05:00)\n\n**Moi :** a\n\n"
        "---\n\n## 10:32 (30:15)\n\n**Moi :** b\n\n",
        encoding="utf-8")
    assert duree_reunion(md) == 30 * 60 + 15             # dernière tranche : 30:15


def test_duree_reunion_inconnue(tmp_path):
    md = tmp_path / "2026-06-29_10-02.md"
    md.write_text("# Réunion — 2026-06-29 10:02\n\ncorps", encoding="utf-8")
    assert duree_reunion(md) is None


def test_duree_reunion_priorite_au_commentaire(tmp_path):
    """Le commentaire stocké prime sur le repli (tranche)."""
    md = tmp_path / "2026-06-29_10-02.md"
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
