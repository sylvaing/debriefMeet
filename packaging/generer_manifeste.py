"""Manifeste de mise à jour signé — exécuté par le job Release de la CI (docs/53 §4).

Trois sous-commandes, pensées pour s'enchaîner sur les assets renommés
(`debriefMeet-setup-<ver>.exe`, `debriefMeet-<ver>.zip`, `debriefmeet_<ver>_amd64.deb`) :

    generer  --version 0.4.0 --tag v0.4.0 --depot sylvaing/debriefMeet \\
             --artefacts artefacts --sortie artefacts/manifest.json
    signer   --manifeste artefacts/manifest.json --sortie artefacts/manifest.sig
    verifier --manifeste artefacts/manifest.json --signature artefacts/manifest.sig

- `generer` : SHA256 + taille de chaque binaire, URLs **absolues et figées sur le
  tag** (`releases/download/<tag>/<nom>`), JSON déterministe (`sort_keys`, `\\n`
  final) — le test compare les octets.
- `signer` : lit la clé privée ed25519 (PEM) dans la variable d'environnement
  `MAJ_CLE_PRIVEE_PEM` (secret CI) — jamais écrite sur disque — et signe les octets
  exacts du manifeste (base64 sur une ligne).
- `verifier` : importe `debrief_meet.core.mise_a_jour.verifier_signature`, la MÊME
  fonction que l'app, avec la clé publique **embarquée** : si le secret ne
  correspond pas à la constante du code, la release échoue ici, pas chez les
  utilisateurs. `--cle-publique-pem` sert aux tests (paire éphémère).

Seule dépendance hors stdlib : `cryptography` (le job fait `pip install cryptography`).
Le script vit hors de `src/` ; les tests le chargent par chemin, comme
`generer_version.py`.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ENV_CLE_PRIVEE = "MAJ_CLE_PRIVEE_PEM"

# Nom public de chaque binaire, dérivé de la version seule — sans `+<date>.<hash>` :
# l'app ne peut pas deviner le hash, et `+` dans un nom d'asset GitHub n'est pas
# documenté. Le `VERSION_COMPLETE` reste à l'intérieur des binaires.
NOMS_PAR_OS = {
    "windows": "debriefMeet-setup-{version}.exe",
    "macos": "debriefMeet-{version}.zip",
    "linux": "debriefmeet_{version}_amd64.deb",
}


def sha256_fichier(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloc)
    return h.hexdigest()


def construire(version: str, tag: str, depot: str, artefacts: Path,
               date: str | None = None) -> dict:
    """Dictionnaire du manifeste — lève `FileNotFoundError` si un binaire attendu
    manque (une release incomplète ne doit jamais être publiée)."""
    fichiers = {}
    for os_cible, gabarit in NOMS_PAR_OS.items():
        nom = gabarit.format(version=version)
        chemin = artefacts / nom
        if not chemin.is_file():
            raise FileNotFoundError(f"asset attendu absent : {chemin}")
        fichiers[os_cible] = {
            "nom": nom,
            "url": f"https://github.com/{depot}/releases/download/{tag}/{nom}",
            "sha256": sha256_fichier(chemin),
            "taille": chemin.stat().st_size,
        }
    return {
        "version": version,
        "tag": tag,
        "date": date or _dt.date.today().isoformat(),
        "notes_url": f"https://github.com/{depot}/releases/tag/{tag}",
        "fichiers": fichiers,
    }


def serialiser(manifeste: dict) -> bytes:
    """Octets déterministes : deux appels sur le même contenu rendent la même
    signature."""
    return json.dumps(manifeste, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def signer(octets: bytes, cle_privee_pem: str) -> str:
    """Signature ed25519 des octets, base64 sur une ligne."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    cle = load_pem_private_key(cle_privee_pem.encode("utf-8"), password=None)
    if not isinstance(cle, Ed25519PrivateKey):
        raise SystemExit(f"{ENV_CLE_PRIVEE} : clé ed25519 attendue, reçu {type(cle).__name__}")
    return base64.b64encode(cle.sign(octets)).decode("ascii")


def verifier(octets: bytes, signature_b64: str, cle_publique_pem: str | None = None) -> bool:
    """Passe par `debrief_meet.core.mise_a_jour.verifier_signature` : c'est le code
    de l'app qui juge, avec sa clé embarquée sauf `cle_publique_pem` explicite."""
    sys.path.insert(0, str(RACINE / "src"))
    from debrief_meet.core.mise_a_jour import CLE_PUBLIQUE_PEM, verifier_signature

    return verifier_signature(octets, signature_b64, cle_publique_pem or CLE_PUBLIQUE_PEM)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manifeste de mise à jour signé (docs/53)")
    sous = parser.add_subparsers(dest="commande", required=True)

    p = sous.add_parser("generer")
    p.add_argument("--version", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--depot", required=True, help="owner/repo GitHub")
    p.add_argument("--artefacts", type=Path, required=True)
    p.add_argument("--sortie", type=Path, required=True)
    p.add_argument("--date", default=None, help="AAAA-MM-JJ (défaut : aujourd'hui)")

    p = sous.add_parser("signer")
    p.add_argument("--manifeste", type=Path, required=True)
    p.add_argument("--sortie", type=Path, required=True)

    p = sous.add_parser("verifier")
    p.add_argument("--manifeste", type=Path, required=True)
    p.add_argument("--signature", type=Path, required=True)
    p.add_argument("--cle-publique-pem", type=Path, default=None,
                   help="fichier PEM (tests) — défaut : la clé embarquée dans l'app")

    args = parser.parse_args(argv)

    if args.commande == "generer":
        manifeste = construire(args.version, args.tag, args.depot, args.artefacts, args.date)
        args.sortie.write_bytes(serialiser(manifeste))
        print(f"-> {args.sortie}")
        return 0

    if args.commande == "signer":
        pem = os.environ.get(ENV_CLE_PRIVEE, "")
        if not pem.strip():
            raise SystemExit(f"{ENV_CLE_PRIVEE} absent de l'environnement — secret CI non pose")
        args.sortie.write_text(signer(args.manifeste.read_bytes(), pem) + "\n", encoding="ascii")
        print(f"-> {args.sortie}")
        return 0

    pem_pub = args.cle_publique_pem.read_text(encoding="utf-8") if args.cle_publique_pem else None
    if not verifier(args.manifeste.read_bytes(), args.signature.read_text(encoding="ascii"), pem_pub):
        print("SIGNATURE INVALIDE : la cle privee du secret ne correspond pas a la cle "
              "publique embarquee dans core/mise_a_jour.py", file=sys.stderr)
        return 1
    print("signature OK (cle publique embarquee)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
