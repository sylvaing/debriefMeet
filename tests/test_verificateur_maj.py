"""docs/53 §2 — `VerificateurMaj` : cadence (opt-out, 24 h), mémoire en config,
notification une fois par version, refus pendant un travail, enchaînement
vérification → téléchargement, arrêt propre. Réseau remplacé par un faux `ClientMaj`."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from debrief_meet import __version__
from debrief_meet.core import mise_a_jour as maj
from debrief_meet.core import verificateur_maj as vm
from debrief_meet.core.mise_a_jour import Fichier, Manifeste
from debrief_meet.core.verificateur_maj import VerificateurMaj

CONTENU = b"binaire de test"


def _manifeste(version="999.0.0") -> Manifeste:
    f = Fichier(nom=f"debriefMeet-{version}.zip", url=f"https://exemple.test/{version}.zip",
                sha256=hashlib.sha256(CONTENU).hexdigest(), taille=len(CONTENU))
    return Manifeste(version=version, tag=f"v{version}", date="2026-10-23",
                     notes_url=f"https://exemple.test/notes/{version}",
                     fichiers={"windows": f, "macos": f, "linux": f})


class _FauxClient:
    """Remplace `ClientMaj` dans le module : réponse réglée par la classe."""
    resultat: object = None          # Manifeste | None | Exception
    appels: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def recuperer_manifeste(self):
        _FauxClient.appels.append("manifeste")
        if isinstance(_FauxClient.resultat, Exception):
            raise _FauxClient.resultat
        return _FauxClient.resultat

    def telecharger(self, fichier, dossier, progression=None):
        _FauxClient.appels.append("telecharger")
        if isinstance(_FauxClient.resultat, Exception):
            raise _FauxClient.resultat
        Path(dossier).mkdir(parents=True, exist_ok=True)
        dest = Path(dossier) / fichier.nom
        dest.write_bytes(CONTENU)
        if progression:
            progression(50)
            progression(100)
        return dest


@pytest.fixture
def faux_client(monkeypatch):
    _FauxClient.resultat = None
    _FauxClient.appels = []
    monkeypatch.setattr(vm, "ClientMaj", _FauxClient)
    return _FauxClient


@pytest.fixture
def verificateur(qapp, config_tmp, faux_client, monkeypatch, tmp_path):
    monkeypatch.setattr(maj, "dossier_telechargements", lambda: tmp_path / "cache")
    monkeypatch.setattr(maj, "_fichier_demande", None)
    v = VerificateurMaj(config_tmp)
    yield v
    v.terminer()


def _attendre_verification(qtbot, v, lancer=None):
    with qtbot.waitSignal(v.verification_terminee, timeout=5000) as blocker:
        assert (lancer or v.verifier)()
    return blocker.args[0]


# ── Cadence ──────────────────────────────────────────────────────────────────

def test_tick_respecte_l_opt_out(verificateur, config_tmp, faux_client):
    config_tmp.set("maj_verifier_auto", False)
    assert verificateur.tick() is False
    assert faux_client.appels == []


def test_tick_ne_verifie_pas_avant_24h(verificateur, config_tmp, faux_client):
    recente = (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat(timespec="seconds")
    config_tmp.set("maj_derniere_verification", recente)
    assert verificateur.tick() is False
    assert faux_client.appels == []


def test_tick_verifie_apres_24h(qtbot, verificateur, config_tmp, faux_client):
    ancienne = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
    config_tmp.set("maj_derniere_verification", ancienne)
    with qtbot.waitSignal(verificateur.verification_terminee, timeout=5000):
        assert verificateur.tick() is True
    assert faux_client.appels == ["manifeste"]


def test_tick_verifie_si_jamais_verifie(qtbot, verificateur, faux_client):
    with qtbot.waitSignal(verificateur.verification_terminee, timeout=5000):
        assert verificateur.tick() is True


def test_tick_date_illisible_revient_a_verifier(qtbot, verificateur, config_tmp):
    config_tmp.set("maj_derniere_verification", "pas une date")
    with qtbot.waitSignal(verificateur.verification_terminee, timeout=5000):
        assert verificateur.tick() is True


def test_date_de_verification_ecrite_en_config(qtbot, verificateur, config_tmp):
    _attendre_verification(qtbot, verificateur)
    d = datetime.fromisoformat(config_tmp.get("maj_derniere_verification"))
    assert d.tzinfo is not None and datetime.now(timezone.utc) - d < timedelta(minutes=1)
    assert Path(config_tmp._chemin).exists() if hasattr(config_tmp, "_chemin") else True


def test_une_seule_verification_a_la_fois(qtbot, verificateur):
    with qtbot.waitSignal(verificateur.verification_terminee, timeout=5000):
        assert verificateur.verifier() is True
        assert verificateur.verifier() is False
        assert verificateur.en_cours()
    assert not verificateur.en_cours()


# ── Résultats ────────────────────────────────────────────────────────────────

def test_a_jour_quand_aucun_manifeste(qtbot, verificateur, config_tmp):
    assert _attendre_verification(qtbot, verificateur) is None
    assert config_tmp.get("maj_version_disponible") == ""


def test_a_jour_quand_version_distante_pas_plus_recente(qtbot, verificateur, faux_client, config_tmp):
    faux_client.resultat = _manifeste(__version__)
    assert _attendre_verification(qtbot, verificateur) is None
    assert verificateur.manifeste() is None


def test_maj_disponible_memorisee_et_emise_une_fois_par_version(qtbot, verificateur, faux_client, config_tmp):
    faux_client.resultat = _manifeste("999.0.0")
    recus = []
    verificateur.maj_disponible.connect(lambda v, u: recus.append((v, u)))
    assert _attendre_verification(qtbot, verificateur) == "999.0.0"
    assert recus == [("999.0.0", "https://exemple.test/notes/999.0.0")]
    assert config_tmp.get("maj_version_disponible") == "999.0.0"
    assert config_tmp.get("maj_notes_url") == "https://exemple.test/notes/999.0.0"
    assert verificateur.version_disponible() == "999.0.0"
    # Même version au passage suivant : pas de re-notification (le badge reste).
    _attendre_verification(qtbot, verificateur)
    assert len(recus) == 1
    # Version différente : notifiée.
    faux_client.resultat = _manifeste("999.1.0")
    _attendre_verification(qtbot, verificateur)
    assert [v for v, _ in recus] == ["999.0.0", "999.1.0"]


def test_retour_a_jour_efface_la_memoire(qtbot, verificateur, faux_client, config_tmp):
    config_tmp.set("maj_version_disponible", "999.0.0")
    config_tmp.set("maj_notes_url", "https://x")
    faux_client.resultat = None
    _attendre_verification(qtbot, verificateur)
    assert config_tmp.get("maj_version_disponible") == "" and config_tmp.get("maj_notes_url") == ""


def test_version_disponible_depuis_config_sans_reseau(verificateur, config_tmp, faux_client):
    """Badge dès le lancement suivant, même hors ligne."""
    config_tmp.set("maj_version_disponible", "999.0.0")
    config_tmp.set("maj_notes_url", "https://x/notes")
    assert verificateur.version_disponible() == "999.0.0"
    assert verificateur.notes_url() == "https://x/notes"
    assert faux_client.appels == []


def test_version_memorisee_perimee_effacee(verificateur, config_tmp):
    """On vient d'être mis à jour : la version mémorisée n'est plus « plus récente »."""
    config_tmp.set("maj_version_disponible", __version__)
    assert verificateur.version_disponible() == ""
    assert config_tmp.get("maj_version_disponible") == ""


def test_echec_reseau_journalise_et_signale(qtbot, verificateur, faux_client, caplog):
    import logging
    faux_client.resultat = maj.ErreurReseauMaj("DNS")
    with caplog.at_level(logging.WARNING, logger="debrief_meet.core.verificateur_maj"):
        with qtbot.waitSignal(verificateur.verification_echouee, timeout=5000) as b:
            verificateur.verifier()
    assert "DNS" in b.args[0] and "échouée" in caplog.text
    assert not verificateur.en_cours()


def test_exception_inattendue_ne_tue_pas_le_thread(qtbot, verificateur, faux_client):
    faux_client.resultat = RuntimeError("boum")
    with qtbot.waitSignal(verificateur.verification_echouee, timeout=5000) as b:
        verificateur.verifier()
    assert "boum" in b.args[0]


# ── Téléchargement + installation ────────────────────────────────────────────

@pytest.fixture
def installable(monkeypatch):
    monkeypatch.setattr(maj, "installation_possible", lambda: True)


def test_refuse_pendant_un_travail(qapp, config_tmp, faux_client, installable):
    v = VerificateurMaj(config_tmp, est_occupe=lambda: True)
    assert v.telecharger_et_installer() == "occupe"
    assert faux_client.appels == []


def test_manuel_quand_installation_impossible(verificateur, faux_client, monkeypatch):
    monkeypatch.setattr(maj, "installation_possible", lambda: False)
    assert verificateur.telecharger_et_installer() == "manuel"
    assert faux_client.appels == []


def test_aucune_quand_rien_a_installer(verificateur, installable):
    assert verificateur.telecharger_et_installer() == "aucune"


def test_telecharge_puis_demande_l_installation(qtbot, verificateur, faux_client, installable, tmp_path):
    faux_client.resultat = _manifeste("999.0.0")
    _attendre_verification(qtbot, verificateur)
    pcts = []
    verificateur.telechargement_progresse.connect(pcts.append)
    with qtbot.waitSignal(verificateur.telechargement_termine, timeout=5000) as b:
        assert verificateur.telecharger_et_installer() == "lance"
        assert verificateur.telecharger_et_installer() == "en_cours"
    chemin = b.args[0]
    assert chemin == tmp_path / "cache" / "debriefMeet-999.0.0.zip"
    assert chemin.read_bytes() == CONTENU
    assert pcts == [50, 100]
    assert maj.est_demande() and maj._fichier_demande == chemin


def test_telechargement_echoue_signale(qtbot, verificateur, faux_client, installable):
    faux_client.resultat = _manifeste("999.0.0")
    _attendre_verification(qtbot, verificateur)
    faux_client.resultat = maj.ErreurIntegriteMaj("sha256")
    with qtbot.waitSignal(verificateur.telechargement_echoue, timeout=5000) as b:
        verificateur.telecharger_et_installer()
    assert "sha256" in b.args[0] and not maj.est_demande()


def test_badge_depuis_config_enchaine_verification_puis_telechargement(qtbot, verificateur, faux_client,
                                                                        installable, config_tmp):
    """Au lancement, le badge vient de la config : aucun manifeste en mémoire. Un clic
    vérifie d'abord, puis télécharge sans second clic."""
    config_tmp.set("maj_version_disponible", "999.0.0")
    faux_client.resultat = _manifeste("999.0.0")
    with qtbot.waitSignal(verificateur.telechargement_termine, timeout=5000):
        assert verificateur.telecharger_et_installer() == "verification"
    assert faux_client.appels == ["manifeste", "telecharger"]


def test_enchainement_abandonne_si_finalement_a_jour(qtbot, verificateur, faux_client, installable, config_tmp):
    config_tmp.set("maj_version_disponible", "999.0.0")
    faux_client.resultat = None
    with qtbot.waitSignal(verificateur.telechargement_echoue, timeout=5000) as b:
        assert verificateur.telecharger_et_installer() == "verification"
    assert "Aucune mise à jour" in b.args[0]
    assert faux_client.appels == ["manifeste"]


# ── Arrêt ────────────────────────────────────────────────────────────────────

def test_terminer_joint_le_thread(qtbot, verificateur, faux_client):
    import threading
    pret = threading.Event()

    class _Lent(_FauxClient):
        def recuperer_manifeste(self):
            pret.set()
            import time
            time.sleep(0.2)
            return None
    import debrief_meet.core.verificateur_maj as module
    module.ClientMaj = _Lent
    verificateur.verifier()
    assert pret.wait(2)
    verificateur.terminer()
    assert verificateur._thread is not None and not verificateur._thread.isRunning()


def test_demarrer_arme_les_timers(verificateur, monkeypatch):
    programmes = []
    monkeypatch.setattr(vm.QTimer, "singleShot", staticmethod(lambda ms, f: programmes.append(ms)))
    verificateur.demarrer()
    assert programmes == [vm.DELAI_PREMIERE_VERIF_MS]
    assert verificateur._timer.isActive() and verificateur._timer.interval() == vm.INTERVALLE_TICK_MS
    verificateur.arreter()
    assert not verificateur._timer.isActive()
