"""docs/53 §4 : `packaging/generer_manifeste.py` (generer / signer / verifier) — chargé
par chemin comme `generer_version.py`, paire ed25519 éphémère."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)

MODULE_PATH = Path(__file__).resolve().parents[1] / "packaging" / "generer_manifeste.py"
VERSION = "0.4.0"


def _charger_module():
    spec = importlib.util.spec_from_file_location("generer_manifeste_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _charger_module()


@pytest.fixture
def artefacts(tmp_path) -> Path:
    d = tmp_path / "artefacts"
    d.mkdir()
    for nom in (f"debriefMeet-setup-{VERSION}.exe", f"debriefMeet-{VERSION}.zip",
                f"debriefmeet_{VERSION}_amd64.deb"):
        (d / nom).write_bytes(nom.encode() * 100)
    return d


@pytest.fixture
def paire(tmp_path):
    cle = Ed25519PrivateKey.generate()
    pem_prive = cle.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    pub = tmp_path / "pub.pem"
    pub.write_text(cle.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode())
    return pem_prive, pub


def _generer(mod, artefacts, sortie, date="2026-10-23"):
    assert mod.main(["generer", "--version", VERSION, "--tag", f"v{VERSION}",
                     "--depot", "sylvaing/debriefMeet", "--artefacts", str(artefacts),
                     "--sortie", str(sortie), "--date", date]) == 0
    return sortie


# ── generer ──────────────────────────────────────────────────────────────────

def test_generer_sha256_taille_url(mod, artefacts, tmp_path):
    m = json.loads(_generer(mod, artefacts, tmp_path / "manifest.json").read_bytes())
    assert m["version"] == VERSION and m["tag"] == f"v{VERSION}" and m["date"] == "2026-10-23"
    assert m["notes_url"] == f"https://github.com/sylvaing/debriefMeet/releases/tag/v{VERSION}"
    assert set(m["fichiers"]) == {"windows", "macos", "linux"}
    for os_cible, f in m["fichiers"].items():
        chemin = artefacts / f["nom"]
        assert f["sha256"] == hashlib.sha256(chemin.read_bytes()).hexdigest()
        assert f["taille"] == chemin.stat().st_size
        assert f["url"] == f"https://github.com/sylvaing/debriefMeet/releases/download/v{VERSION}/{f['nom']}"
        assert "+" not in f["nom"]
    assert m["fichiers"]["windows"]["nom"].endswith(".exe")
    assert m["fichiers"]["macos"]["nom"].endswith(".zip")
    assert m["fichiers"]["linux"]["nom"].endswith("_amd64.deb")


def test_generer_deterministe(mod, artefacts, tmp_path):
    a = _generer(mod, artefacts, tmp_path / "a.json").read_bytes()
    b = _generer(mod, artefacts, tmp_path / "b.json").read_bytes()
    assert a == b and a.endswith(b"\n")


def test_generer_refuse_un_asset_manquant(mod, artefacts, tmp_path):
    (artefacts / f"debriefMeet-{VERSION}.zip").unlink()
    with pytest.raises(FileNotFoundError, match="debriefMeet-0.4.0.zip"):
        _generer(mod, artefacts, tmp_path / "manifest.json")


def test_manifeste_genere_est_lisible_par_l_app(mod, artefacts, tmp_path):
    """Le producteur (CI) et le consommateur (app) doivent rester d'accord sur le format."""
    from debrief_meet.core.mise_a_jour import Manifeste
    m = Manifeste.depuis_json(_generer(mod, artefacts, tmp_path / "manifest.json").read_bytes())
    assert m.fichier_pour("macos").nom == f"debriefMeet-{VERSION}.zip"


# ── signer / verifier ────────────────────────────────────────────────────────

def test_ronde_signer_verifier(mod, artefacts, tmp_path, paire, monkeypatch):
    pem_prive, pub = paire
    manifeste = _generer(mod, artefacts, tmp_path / "manifest.json")
    sig = tmp_path / "manifest.sig"
    monkeypatch.setenv(mod.ENV_CLE_PRIVEE, pem_prive)
    assert mod.main(["signer", "--manifeste", str(manifeste), "--sortie", str(sig)]) == 0
    assert sig.read_text().endswith("\n") and sig.read_text().count("\n") == 1
    assert mod.main(["verifier", "--manifeste", str(manifeste), "--signature", str(sig),
                     "--cle-publique-pem", str(pub)]) == 0


def test_verifier_refuse_un_octet_modifie(mod, artefacts, tmp_path, paire, monkeypatch):
    pem_prive, pub = paire
    manifeste = _generer(mod, artefacts, tmp_path / "manifest.json")
    sig = tmp_path / "manifest.sig"
    monkeypatch.setenv(mod.ENV_CLE_PRIVEE, pem_prive)
    mod.main(["signer", "--manifeste", str(manifeste), "--sortie", str(sig)])
    octets = bytearray(manifeste.read_bytes())
    octets[-2] ^= 0x01
    manifeste.write_bytes(bytes(octets))
    assert mod.main(["verifier", "--manifeste", str(manifeste), "--signature", str(sig),
                     "--cle-publique-pem", str(pub)]) == 1


def test_verifier_refuse_une_autre_cle(mod, artefacts, tmp_path, paire, monkeypatch):
    pem_prive, _ = paire
    autre_pub = tmp_path / "autre.pem"
    autre_pub.write_text(Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode())
    manifeste = _generer(mod, artefacts, tmp_path / "manifest.json")
    sig = tmp_path / "manifest.sig"
    monkeypatch.setenv(mod.ENV_CLE_PRIVEE, pem_prive)
    mod.main(["signer", "--manifeste", str(manifeste), "--sortie", str(sig)])
    assert mod.main(["verifier", "--manifeste", str(manifeste), "--signature", str(sig),
                     "--cle-publique-pem", str(autre_pub)]) == 1


def test_signer_sans_secret_echoue_clairement(mod, artefacts, tmp_path, monkeypatch):
    manifeste = _generer(mod, artefacts, tmp_path / "manifest.json")
    monkeypatch.delenv(mod.ENV_CLE_PRIVEE, raising=False)
    with pytest.raises(SystemExit, match="MAJ_CLE_PRIVEE_PEM"):
        mod.main(["signer", "--manifeste", str(manifeste), "--sortie", str(tmp_path / "s")])


def test_signer_refuse_une_cle_d_un_autre_type(mod, artefacts, tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa
    rsa_pem = rsa.generate_private_key(65537, 2048).private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    manifeste = _generer(mod, artefacts, tmp_path / "manifest.json")
    monkeypatch.setenv(mod.ENV_CLE_PRIVEE, rsa_pem)
    with pytest.raises(SystemExit, match="ed25519"):
        mod.main(["signer", "--manifeste", str(manifeste), "--sortie", str(tmp_path / "s")])


def test_verifier_passe_par_la_fonction_de_l_app(mod, artefacts, tmp_path, paire, monkeypatch):
    """Sans `--cle-publique-pem`, c'est `debrief_meet.core.mise_a_jour.verifier_signature`
    avec `CLE_PUBLIQUE_PEM` qui juge — fige que la CI vérifie avec le code de l'app."""
    from debrief_meet.core import mise_a_jour
    pem_prive, pub = paire
    monkeypatch.setattr(mise_a_jour, "CLE_PUBLIQUE_PEM", pub.read_text())
    manifeste = _generer(mod, artefacts, tmp_path / "manifest.json")
    sig = tmp_path / "manifest.sig"
    monkeypatch.setenv(mod.ENV_CLE_PRIVEE, pem_prive)
    mod.main(["signer", "--manifeste", str(manifeste), "--sortie", str(sig)])
    assert mod.main(["verifier", "--manifeste", str(manifeste), "--signature", str(sig)]) == 0
    monkeypatch.setattr(mise_a_jour, "CLE_PUBLIQUE_PEM", mise_a_jour.CLE_PUBLIQUE_PEM.replace("M", "N", 1))
    assert mod.main(["verifier", "--manifeste", str(manifeste), "--signature", str(sig)]) == 1
