"""docs/53 — `core/mise_a_jour.py` : manifeste, signature, versions, téléchargement,
passage de main à l'installeur (sans spawn réel, modèle `test_redemarrage.py`)."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

from debrief_meet import __version__
from debrief_meet.core import mise_a_jour as maj


# ── Outils ───────────────────────────────────────────────────────────────────

@pytest.fixture
def paire():
    """Paire ed25519 éphémère : (clé privée, PEM privé, PEM public)."""
    cle = Ed25519PrivateKey.generate()
    pem_prive = cle.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    pem_public = cle.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    return cle, pem_prive, pem_public


def _signer(cle: Ed25519PrivateKey, octets: bytes) -> str:
    return base64.b64encode(cle.sign(octets)).decode()


def _manifeste_dict(version="9.9.9", contenu: bytes = b"binaire", nom="debriefMeet-9.9.9.zip") -> dict:
    return {
        "version": version, "tag": f"v{version}", "date": "2026-10-23",
        "notes_url": f"https://github.com/sylvaing/debriefMeet/releases/tag/v{version}",
        "fichiers": {
            os_cible: {"nom": nom, "url": f"https://exemple.test/dl/{nom}",
                       "sha256": hashlib.sha256(contenu).hexdigest(), "taille": len(contenu)}
            for os_cible in ("windows", "macos", "linux")
        },
    }


@pytest.fixture(autouse=True)
def _drapeau_baisse(monkeypatch):
    monkeypatch.setattr(maj, "_fichier_demande", None)


# ── Manifeste ────────────────────────────────────────────────────────────────

def test_manifeste_parse_strict():
    m = maj.Manifeste.depuis_json(json.dumps(_manifeste_dict()).encode())
    assert m.version == "9.9.9" and m.tag == "v9.9.9"
    assert m.fichier_pour("macos").nom == "debriefMeet-9.9.9.zip"
    assert m.fichier_pour("inconnu") is None


@pytest.mark.parametrize("casse", [
    lambda d: d.pop("version"),
    lambda d: d["fichiers"]["macos"].pop("sha256"),
    lambda d: d["fichiers"]["macos"].__setitem__("taille", "12"),
    lambda d: d["fichiers"]["macos"].__setitem__("taille", -1),
    lambda d: d.__setitem__("notes_url", ""),
])
def test_manifeste_incomplet_refuse(casse):
    d = _manifeste_dict()
    casse(d)
    with pytest.raises(maj.ErreurManifeste):
        maj.Manifeste.depuis_json(json.dumps(d).encode())


@pytest.mark.parametrize("octets", [b"pas du json", b"[1, 2]", b"\xff\xfe"])
def test_manifeste_illisible_refuse(octets):
    with pytest.raises(maj.ErreurManifeste):
        maj.Manifeste.depuis_json(octets)


def test_sha256_normalise_en_minuscules():
    d = _manifeste_dict()
    d["fichiers"]["macos"]["sha256"] = d["fichiers"]["macos"]["sha256"].upper()
    m = maj.Manifeste.depuis_json(json.dumps(d).encode())
    assert m.fichier_pour("macos").sha256.islower()


# ── Signature ────────────────────────────────────────────────────────────────

def test_signature_valide(paire):
    cle, _, pub = paire
    octets = b'{"version": "1"}\n'
    assert maj.verifier_signature(octets, _signer(cle, octets), pub)


def test_signature_octets_alteres_refusee(paire):
    cle, _, pub = paire
    sig = _signer(cle, b"original")
    assert not maj.verifier_signature(b"origina1", sig, pub)


def test_signature_mauvaise_cle_refusee(paire):
    cle, _, _ = paire
    autre_pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    assert not maj.verifier_signature(b"x", _signer(cle, b"x"), autre_pub)


@pytest.mark.parametrize("sig", ["", "pas du base64 !!", "QUJD"])
def test_signature_mal_formee_rend_false_sans_lever(paire, sig):
    _, _, pub = paire
    assert maj.verifier_signature(b"x", sig, pub) is False


def test_cle_embarquee_est_une_cle_ed25519_valide():
    """La constante du code doit se charger : un PEM corrompu ferait échouer TOUTES
    les vérifications (donc plus aucune mise à jour, silencieusement)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    assert isinstance(load_pem_public_key(maj.CLE_PUBLIQUE_PEM.encode()), Ed25519PublicKey)


# ── Versions ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("distante, locale, attendu", [
    ("0.4.0", "0.3.0", True),
    ("0.3.0", "0.3.0", False),
    ("0.2.9", "0.3.0", False),
    ("0.4.0rc1", "0.4.0", False),
    ("0.4.0", "0.4.0rc1", True),
    ("1.0.0", "0.9.9", True),
    ("n'importe quoi", "0.3.0", False),
])
def test_est_plus_recente(distante, locale, attendu):
    assert maj.est_plus_recente(distante, locale) is attendu


def test_est_plus_recente_compare_a_la_version_de_l_app_par_defaut():
    assert maj.est_plus_recente("999.0.0") is True
    assert maj.est_plus_recente(__version__) is False


# ── Client HTTP ──────────────────────────────────────────────────────────────

def _client_mock(routeur) -> maj.ClientMaj:
    return maj.ClientMaj("https://exemple.test/latest/manifest.json",
                         transport=httpx.MockTransport(routeur))


def test_url_signature():
    assert maj.url_signature("https://x/latest/manifest.json") == "https://x/latest/manifest.sig"
    assert maj.url_signature("https://x/m") == "https://x/m.sig"


def test_url_manifeste_surchargeable_par_env(monkeypatch):
    monkeypatch.delenv(maj.ENV_URL_MANIFESTE, raising=False)
    assert maj.url_manifeste() == maj.URL_MANIFESTE_DEFAUT
    monkeypatch.setenv(maj.ENV_URL_MANIFESTE, "http://localhost:8000/manifest.json")
    assert maj.url_manifeste() == "http://localhost:8000/manifest.json"
    assert maj.ClientMaj(transport=httpx.MockTransport(lambda r: httpx.Response(404))).url \
        == "http://localhost:8000/manifest.json"


def test_recuperer_manifeste_suit_les_redirections_et_verifie(paire, monkeypatch):
    """`releases/latest/download` répond 302 (deux fois) : sans `follow_redirects`,
    httpx rendrait le 302 lui-même et le manifeste serait un corps vide."""
    cle, _, pub = paire
    monkeypatch.setattr(maj, "CLE_PUBLIQUE_PEM", pub)
    octets = json.dumps(_manifeste_dict()).encode()
    vus = []

    def routeur(req: httpx.Request):
        vus.append(str(req.url))
        if req.url.path == "/latest/manifest.json":
            return httpx.Response(302, headers={"Location": "https://exemple.test/dl/v9/manifest.json"})
        if req.url.path == "/dl/v9/manifest.json":
            return httpx.Response(200, content=octets)
        if req.url.path == "/latest/manifest.sig":
            return httpx.Response(200, text=_signer(cle, octets) + "\n")
        return httpx.Response(404)

    m = _client_mock(routeur).recuperer_manifeste()
    assert m is not None and m.version == "9.9.9"
    assert "https://exemple.test/dl/v9/manifest.json" in vus


def test_recuperer_manifeste_pose_user_agent():
    vus = {}

    def routeur(req):
        vus["ua"] = req.headers.get("User-Agent")
        return httpx.Response(404)

    _client_mock(routeur).recuperer_manifeste()
    assert vus["ua"].startswith("debriefMeet/")
    assert maj.DEPOT in vus["ua"]


def test_recuperer_manifeste_404_rend_none_sans_lever():
    assert _client_mock(lambda r: httpx.Response(404)).recuperer_manifeste() is None


def test_recuperer_manifeste_signature_absente_rend_none(paire, caplog):
    octets = json.dumps(_manifeste_dict()).encode()

    def routeur(req):
        return httpx.Response(200, content=octets) if req.url.path.endswith(".json") else httpx.Response(404)

    with caplog.at_level(logging.WARNING, logger="debrief_meet.core.mise_a_jour"):
        assert _client_mock(routeur).recuperer_manifeste() is None
    assert "signature absente" in caplog.text


def test_recuperer_manifeste_signature_invalide_leve_et_journalise(paire, monkeypatch, caplog):
    cle, _, pub = paire
    monkeypatch.setattr(maj, "CLE_PUBLIQUE_PEM", pub)
    octets = json.dumps(_manifeste_dict()).encode()
    sig_autre = _signer(cle, octets + b"x")

    def routeur(req):
        return httpx.Response(200, content=octets) if req.url.path.endswith(".json") \
            else httpx.Response(200, text=sig_autre)

    with caplog.at_level(logging.WARNING, logger="debrief_meet.core.mise_a_jour"):
        with pytest.raises(maj.ErreurSignatureMaj):
            _client_mock(routeur).recuperer_manifeste()
    assert "INVALIDE" in caplog.text


def test_recuperer_manifeste_erreur_serveur():
    with pytest.raises(maj.ErreurServeurMaj):
        _client_mock(lambda r: httpx.Response(503)).recuperer_manifeste()


def test_recuperer_manifeste_erreur_reseau():
    def routeur(req):
        raise httpx.ConnectError("refusé")
    with pytest.raises(maj.ErreurReseauMaj):
        _client_mock(routeur).recuperer_manifeste()


def _fichier(contenu: bytes, nom="debriefMeet-9.9.9.zip", **surcharges) -> maj.Fichier:
    champs = dict(nom=nom, url=f"https://exemple.test/dl/{nom}",
                  sha256=hashlib.sha256(contenu).hexdigest(), taille=len(contenu))
    champs.update(surcharges)
    return maj.Fichier(**champs)


def test_telecharger_verifie_sha256_et_taille(tmp_path):
    contenu = os.urandom(300_000)
    pcts = []
    dest = _client_mock(lambda r: httpx.Response(200, content=contenu)).telecharger(
        _fichier(contenu), tmp_path / "cache", progression=pcts.append)
    assert dest == tmp_path / "cache" / "debriefMeet-9.9.9.zip"
    assert dest.read_bytes() == contenu
    assert not list((tmp_path / "cache").glob("*.part"))
    assert pcts and pcts[-1] == 100 and pcts == sorted(pcts)


def test_telecharger_sha256_faux_supprime_le_part(tmp_path):
    contenu = b"vrai contenu"
    with pytest.raises(maj.ErreurIntegriteMaj):
        _client_mock(lambda r: httpx.Response(200, content=contenu)).telecharger(
            _fichier(contenu, sha256="0" * 64), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_telecharger_taille_fausse_refusee(tmp_path):
    contenu = b"vrai contenu"
    with pytest.raises(maj.ErreurIntegriteMaj):
        _client_mock(lambda r: httpx.Response(200, content=contenu)).telecharger(
            _fichier(contenu, taille=len(contenu) + 1), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_telecharger_erreur_serveur_et_reseau(tmp_path):
    with pytest.raises(maj.ErreurServeurMaj):
        _client_mock(lambda r: httpx.Response(500)).telecharger(_fichier(b"x"), tmp_path)

    def coupe(req):
        raise httpx.ReadTimeout("coupé")
    with pytest.raises(maj.ErreurReseauMaj):
        _client_mock(coupe).telecharger(_fichier(b"x"), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_telecharger_remplace_un_fichier_existant(tmp_path):
    (tmp_path / "debriefMeet-9.9.9.zip").write_bytes(b"ancien")
    contenu = b"nouveau"
    _client_mock(lambda r: httpx.Response(200, content=contenu)).telecharger(_fichier(contenu), tmp_path)
    assert (tmp_path / "debriefMeet-9.9.9.zip").read_bytes() == b"nouveau"


# ── Dossier de cache ─────────────────────────────────────────────────────────

def test_dossier_telechargements_sous_le_cache_utilisateur(monkeypatch, tmp_path):
    import platformdirs
    monkeypatch.setattr(platformdirs, "user_cache_dir", lambda nom, appauthor=None: str(tmp_path / nom))
    assert maj.dossier_telechargements() == tmp_path / "debriefMeet" / "mises_a_jour"


def test_purger_garde_le_fichier_courant(monkeypatch, tmp_path):
    monkeypatch.setattr(maj, "dossier_telechargements", lambda: tmp_path)
    garde = tmp_path / "debriefMeet-9.9.9.zip"
    garde.write_bytes(b"x")
    (tmp_path / "debriefMeet-9.8.0.zip").write_bytes(b"y")
    (tmp_path / "debriefMeet-9.8.0.zip.part").write_bytes(b"z")
    maj.purger(sauf=garde)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["debriefMeet-9.9.9.zip"]


# ── Où tourne-t-on ───────────────────────────────────────────────────────────

def test_chemin_bundle_macos():
    assert maj.chemin_bundle_macos("/Applications/debriefMeet.app/Contents/MacOS/debriefMeet") \
        == Path("/Applications/debriefMeet.app")
    assert maj.chemin_bundle_macos("/usr/local/bin/python3") is None
    assert maj.chemin_bundle_macos("/x/debriefMeet.app/Contents/Resources/debriefMeet") is None


def test_installation_impossible_depuis_les_sources(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert maj.installation_possible() is False


def test_installation_possible_windows_figee(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert maj.installation_possible() is True


def test_installation_macos_exige_un_parent_inscriptible(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    bundle = tmp_path / "Apps" / "debriefMeet.app"
    exe = bundle / "Contents" / "MacOS" / "debriefMeet"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    assert maj.installation_possible() is True
    verrouille = []
    monkeypatch.setattr(maj.os, "access", lambda p, m: verrouille.append(p) and False or False)
    assert maj.installation_possible() is False
    assert verrouille == [bundle.parent]


def test_installation_linux_toujours_manuelle(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert maj.installation_possible() is False


# ── Scripts générés ──────────────────────────────────────────────────────────

def test_script_windows_attend_le_pid_puis_lance_en_silent():
    s = maj.script_lanceur_windows(4242, Path(r"C:\cache\debriefMeet-setup-0.4.0.exe"), Path(r"C:\cache\setup.log"))
    assert 'tasklist /FI "PID eq %PID%" /FO CSV /NH' in s
    assert 'findstr /C:"\\"debriefMeet.exe\\",\\"%PID%\\""' in s
    assert 'set "PID=4242"' in s
    assert "goto attente" in s and "ping -n 2" in s and "geq 120" in s
    assert f'start "" "%SETUP%" /SILENT /{maj.PARAM_AUTOUPDATE}=1 /LOG="%JOURNAL%"' in s
    assert "/VERYSILENT" not in s and "/SUPPRESSMSGBOXES" not in s
    assert "\r\n" in s   # fin de ligne Windows : cmd.exe lit mal un script en \n seuls


def test_script_macos_remplace_avec_retour_arriere():
    s = maj.script_remplacement_macos(
        4242, Path("/Users/x y/Library/Caches/debriefMeet/mises_a_jour/debriefMeet-0.4.0.zip"),
        Path("/Applications/debriefMeet.app"), Path("/Users/x y/Library/Caches/debriefMeet/mises_a_jour/installation.log"))
    assert s.startswith("#!/bin/sh\n")
    assert 'while kill -0 "$PID"' in s and "PID=4242" in s
    assert "ZIP='/Users/x y/Library/Caches/debriefMeet/mises_a_jour/debriefMeet-0.4.0.zip'" in s
    assert 'ditto -x -k "$ZIP" "$NOUVEAU"' in s
    assert 'codesign --verify --deep --strict "$NOUVEAU/debriefMeet.app"' in s
    assert 'mv "$APP" "$ANCIEN/"' in s and 'mv "$NOUVEAU/debriefMeet.app" "$APP"' in s
    assert 'mv "$ANCIEN/debriefMeet.app" "$APP"' in s          # retour arrière
    assert 'open "$APP"' in s and "open -a" not in s
    assert 'rm -rf "$APP"' not in s
    assert 'open -R "$ZIP"' in s                               # repli : montrer le zip
    assert "xattr" not in s
    assert "unzip" not in s


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "darwin", reason="ditto/sh macOS")
def test_script_macos_execute_reellement(tmp_path):
    """Exécute le script sur une fausse `.app` — `codesign` et `open` remplacés par
    des stubs via PATH, le PID attendu est un `sleep` court."""
    apps = tmp_path / "Apps"
    apps.mkdir()
    app = apps / "debriefMeet.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "v").write_text("ancienne")
    nouveau = tmp_path / "src" / "debriefMeet.app" / "Contents"
    nouveau.mkdir(parents=True)
    (nouveau / "v").write_text("nouvelle")
    zip_ = tmp_path / "debriefMeet-0.4.0.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(tmp_path / "src" / "debriefMeet.app"), str(zip_)], check=True)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for outil in ("codesign", "open"):
        p = stubs / outil
        p.write_text(f"#!/bin/sh\necho {outil} \"$@\" >> {tmp_path / 'appels.log'}\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    dormeur = subprocess.Popen(["sleep", "0.3"])
    # Moissonner le dormeur dès sa mort : un zombie non attendu répond encore à
    # `kill -0` (en réel, launchd moissonne l'app aussitôt).
    import threading
    threading.Thread(target=dormeur.wait, daemon=True).start()
    script = tmp_path / "installer.sh"
    script.write_text(maj.script_remplacement_macos(dormeur.pid, zip_, app, tmp_path / "journal.log"))
    env = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}")
    subprocess.run(["/bin/sh", str(script)], env=env, check=True, timeout=30)
    assert (app / "Contents" / "v").read_text() == "nouvelle"
    assert not list(apps.glob(".debriefMeet-*"))
    assert not zip_.exists()
    appels = (tmp_path / "appels.log").read_text()
    assert "codesign --verify --deep --strict" in appels and f"open {app}" in appels
    assert "OK" in (tmp_path / "journal.log").read_text()


# ── Passage de main (après app.exec()) ───────────────────────────────────────

def test_drapeau_demande():
    assert not maj.est_demande()
    maj.demander(Path("/tmp/x.zip"))
    assert maj.est_demande()


def test_appliquer_sans_demande_ne_fait_rien(monkeypatch):
    appels = []
    monkeypatch.setattr(maj.subprocess, "Popen", lambda *a, **k: appels.append((a, k)))
    maj.appliquer()
    assert appels == []


def test_appliquer_windows_spawn_detache_hors_de_app(monkeypatch, tmp_path):
    monkeypatch.setattr(maj, "dossier_telechargements", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(maj.subprocess, "DETACHED_PROCESS", 8, raising=False)
    monkeypatch.setattr(maj.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "x")
    appels = []
    monkeypatch.setattr(maj.subprocess, "Popen", lambda *a, **k: appels.append((a, k)))
    maj.demander(tmp_path / "debriefMeet-setup-0.4.0.exe")
    maj.appliquer()
    (args, kwargs), = appels
    assert args[0][:2] == ["cmd.exe", "/c"] and args[0][2] == str(tmp_path / "installer.cmd")
    assert kwargs["creationflags"] == 8 | 512
    assert kwargs["cwd"] == str(tmp_path)
    assert "_PYI_ARCHIVE_FILE" not in kwargs["env"]
    assert "/SILENT" in (tmp_path / "installer.cmd").read_text()


def test_appliquer_macos_spawn_sh_detache(monkeypatch, tmp_path):
    monkeypatch.setattr(maj, "dossier_telechargements", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", "/Applications/debriefMeet.app/Contents/MacOS/debriefMeet")
    appels = []
    monkeypatch.setattr(maj.subprocess, "Popen", lambda *a, **k: appels.append((a, k)))
    maj.demander(tmp_path / "debriefMeet-0.4.0.zip")
    maj.appliquer()
    (args, kwargs), = appels
    assert args[0] == ["/bin/sh", str(tmp_path / "installer.sh")]
    assert kwargs["start_new_session"] is True
    assert "APP=/Applications/debriefMeet.app\n" in (tmp_path / "installer.sh").read_text()


def test_appliquer_macos_hors_bundle_ne_lance_rien(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(maj, "dossier_telechargements", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    appels = []
    monkeypatch.setattr(maj.subprocess, "Popen", lambda *a, **k: appels.append((a, k)))
    maj.demander(tmp_path / "x.zip")
    with caplog.at_level(logging.ERROR, logger="debrief_meet.core.mise_a_jour"):
        maj.appliquer()
    assert appels == [] and "hors d'un bundle" in caplog.text


def test_appliquer_linux_ne_lance_rien(monkeypatch, tmp_path):
    monkeypatch.setattr(maj, "dossier_telechargements", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    appels = []
    monkeypatch.setattr(maj.subprocess, "Popen", lambda *a, **k: appels.append((a, k)))
    maj.demander(tmp_path / "x.deb")
    maj.appliquer()
    assert appels == []


def test_appliquer_ne_leve_jamais(monkeypatch, tmp_path, caplog):
    """Au pire l'utilisateur installe le fichier à la main — jamais un crash à la fermeture."""
    monkeypatch.setattr(maj, "dossier_telechargements", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", "/Applications/debriefMeet.app/Contents/MacOS/debriefMeet")

    def _echec(*a, **k):
        raise OSError("spawn refusé")
    monkeypatch.setattr(maj.subprocess, "Popen", _echec)
    maj.demander(tmp_path / "x.zip")
    with caplog.at_level(logging.ERROR, logger="debrief_meet.core.mise_a_jour"):
        maj.appliquer()
    assert "Mise à jour impossible" in caplog.text
