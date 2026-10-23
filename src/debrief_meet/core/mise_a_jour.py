"""Mise à jour automatique — logique pure, sans Qt (docs/53).

Flux v1 : *vérifier, prévenir, télécharger sur clic, passer la main à l'installeur*.
Jamais de remplacement silencieux.

- Le canal est la **Release GitHub** du dépôt public : `releases/latest/download/`
  pointe sur la dernière release non-prerelease, sans token ni quota (c'est le site,
  pas l'API). Un `manifest.json` y décrit la version et les binaires par OS.
- Le manifeste est **signé ed25519** (clé privée en secret CI, clé publique
  embarquée ci-dessous) : un dépôt public rend la Release visible de tous, et le
  risque principal est un compte GitHub compromis qui pousserait un installeur
  malveillant à tous les postes. La signature est vérifiée sur les **octets bruts**
  du manifeste, avant tout `json.loads` ; puis le SHA256 du binaire téléchargé est
  comparé à celui du manifeste.
- Le passage de main à l'installeur suit le modèle de `core/redemarrage.py` :
  drapeau module + exécution **après** le retour de `app.exec()`, jamais avant — le
  mutex Windows et le QLocalServer IPC vivent jusqu'à la mort du process.

Imports de module = stdlib + `cryptography` **seulement** : le job Release de la CI
importe ce module (avec `pip install cryptography` seul) pour vérifier la signature
avec la MÊME fonction que l'app — un secret qui ne correspond pas à la clé embarquée
casse la release, pas les postes. `httpx` et `platformdirs` sont importés dans les
fonctions qui en ont besoin.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from debrief_meet import APP_NAME, VERSION_COMPLETE, __version__

logger = logging.getLogger(__name__)

DEPOT = "sylvaing/debriefMeet"
URL_MANIFESTE_DEFAUT = f"https://github.com/{DEPOT}/releases/latest/download/manifest.json"
# Surcharge pour les tests manuels (serveur local, prerelease `-rcN` invisible de
# `latest`) : `DEBRIEFMEET_MAJ_URL=http://localhost:8000/manifest.json make run`.
ENV_URL_MANIFESTE = "DEBRIEFMEET_MAJ_URL"

# Paramètre passé au setup Inno (`/AUTOUPDATE=1`) — lu par `EstMiseAJourAuto` dans
# `packaging/windows/debriefMeet.iss` pour relancer l'app après une install
# silencieuse. Le nom est commun aux deux fichiers (test croisé dans test_build.py).
PARAM_AUTOUPDATE = "AUTOUPDATE"

# Clé publique ed25519 de signature des manifestes. La clé privée correspondante vit
# dans le secret CI `MAJ_CLE_PRIVEE_PEM` (docs/53 §4) — jamais dans le dépôt. Une
# constante Python et non un fichier `datas` : la VM Windows ne synchronise que `src/`.
CLE_PUBLIQUE_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEASqasWySogjOx7o0+xhANPmPP1NKCALUFY+mDDi/CmCI=
-----END PUBLIC KEY-----
"""

NOM_EXECUTABLE_WINDOWS = "debriefMeet.exe"
NOM_BUNDLE_MACOS = "debriefMeet.app"
USER_AGENT = f"debriefMeet/{VERSION_COMPLETE} (+https://github.com/{DEPOT})"

_OS_PAR_PLATEFORME = {"win32": "windows", "darwin": "macos"}


def os_courant() -> str:
    """`"windows"`, `"macos"` ou `"linux"` — les clés de `Manifeste.fichiers`."""
    return _OS_PAR_PLATEFORME.get(sys.platform, "linux")


def url_manifeste() -> str:
    return os.environ.get(ENV_URL_MANIFESTE) or URL_MANIFESTE_DEFAUT


def url_signature(url: str) -> str:
    """`…/manifest.json` → `…/manifest.sig` (publiés côte à côte dans la Release)."""
    return url[: -len(".json")] + ".sig" if url.endswith(".json") else url + ".sig"


# ── Erreurs ──────────────────────────────────────────────────────────────────

class ErreurMaj(Exception):
    """Base des erreurs de mise à jour — journalisées, jamais affichées sauf sur
    une action explicite de l'utilisateur (clic sur le badge, « Vérifier maintenant »)."""


class ErreurManifeste(ErreurMaj):
    """Manifeste illisible ou incomplet."""


class ErreurSignatureMaj(ErreurMaj):
    """Signature ed25519 absente ou invalide — le manifeste est IGNORÉ."""


class ErreurReseauMaj(ErreurMaj):
    """Timeout, connexion refusée, DNS…"""


class ErreurServeurMaj(ErreurMaj):
    """Code HTTP d'erreur (hors 404, qui signifie « pas de release »)."""


class ErreurIntegriteMaj(ErreurMaj):
    """SHA256 ou taille du binaire téléchargé différents du manifeste."""


# ── Manifeste ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Fichier:
    nom: str
    url: str
    sha256: str
    taille: int


@dataclass(frozen=True)
class Manifeste:
    version: str
    tag: str
    date: str
    notes_url: str
    fichiers: dict[str, Fichier]

    @classmethod
    def depuis_json(cls, octets: bytes) -> "Manifeste":
        """Validation stricte : un champ manquant ou mal typé lève `ErreurManifeste`
        plutôt que de laisser passer un manifeste tronqué."""
        try:
            brut = json.loads(octets.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ErreurManifeste(f"Manifeste illisible : {exc}") from exc
        if not isinstance(brut, dict):
            raise ErreurManifeste("Manifeste : objet JSON attendu")
        try:
            fichiers: dict[str, Fichier] = {}
            for cle, f in brut["fichiers"].items():
                taille = f["taille"]
                if not isinstance(taille, int) or isinstance(taille, bool) or taille < 0:
                    raise ErreurManifeste(f"Manifeste : taille invalide pour {cle}")
                fichiers[str(cle)] = Fichier(
                    nom=_chaine(f, "nom"), url=_chaine(f, "url"),
                    sha256=_chaine(f, "sha256").lower(), taille=taille)
            return cls(
                version=_chaine(brut, "version"), tag=_chaine(brut, "tag"),
                date=_chaine(brut, "date"), notes_url=_chaine(brut, "notes_url"),
                fichiers=fichiers)
        except (KeyError, AttributeError, TypeError) as exc:
            raise ErreurManifeste(f"Manifeste incomplet : {exc!r}") from exc

    def fichier_pour(self, os_cible: str | None = None) -> Fichier | None:
        return self.fichiers.get(os_cible or os_courant())


def _chaine(d: dict, cle: str) -> str:
    v = d[cle]
    if not isinstance(v, str) or not v:
        raise ErreurManifeste(f"Manifeste : champ « {cle} » vide ou non textuel")
    return v


# ── Signature et versions ─────────────────────────────────────────────────────

def verifier_signature(octets: bytes, signature_b64: str, cle_pem: str | None = None) -> bool:
    """True si `signature_b64` est la signature ed25519 des octets BRUTS par la clé
    privée associée à `cle_pem` (défaut : la clé embarquée, résolue à l'appel et non
    à la définition — les tests la substituent). Ne lève jamais : un base64 invalide,
    une clé d'un autre type ou une signature fausse rendent False."""
    try:
        cle = load_pem_public_key((cle_pem or CLE_PUBLIQUE_PEM).encode("utf-8"))
        if not isinstance(cle, Ed25519PublicKey):
            return False
        signature = base64.b64decode(signature_b64.strip(), validate=True)
        cle.verify(signature, octets)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def est_plus_recente(distante: str, locale: str | None = None) -> bool:
    """`distante` > `locale` au sens PEP 440 (`0.4.0` > `0.3.0`, `0.4.0rc1` < `0.4.0`).
    Une chaîne invalide ne vaut jamais « plus récente »."""
    from packaging.version import InvalidVersion, Version

    try:
        return Version(distante) > Version(locale or __version__)
    except InvalidVersion:
        logger.warning("Version de mise à jour illisible : %r", distante)
        return False


# ── Dossier de téléchargement ────────────────────────────────────────────────

def dossier_telechargements() -> Path:
    """`<cache utilisateur>/debriefMeet/mises_a_jour` — sous `%LOCALAPPDATA%\\debriefMeet`
    sur Windows (`appauthor=False`, cf. CLAUDE.md), donc couvert par
    `[UninstallDelete]` du setup."""
    import platformdirs

    return Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False)) / "mises_a_jour"


def purger(sauf: Path | None = None) -> None:
    """Retire les téléchargements précédents (et les `.part` abandonnés), en
    gardant `sauf`. Jamais bloquant."""
    dossier = dossier_telechargements()
    if not dossier.is_dir():
        return
    for p in dossier.iterdir():
        if sauf is not None and p == sauf:
            continue
        try:
            if p.is_file():
                p.unlink()
        except OSError as exc:
            logger.debug("Purge impossible de %s : %s", p, exc)


# ── Client HTTP ──────────────────────────────────────────────────────────────

class ClientMaj:
    """`httpx` sync, appelé depuis un thread de fond uniquement.

    `follow_redirects=True` est **obligatoire** : httpx ne suit pas les redirections
    par défaut, et `releases/latest/download/…` en fait deux (vers le tag, puis vers
    `objects.githubusercontent.com`) — sans ce drapeau on lit un corps vide en 302.
    """

    def __init__(self, url: str | None = None, transport=None) -> None:
        import httpx

        self._url = url or url_manifeste()
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0),
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            transport=transport,
        )

    @property
    def url(self) -> str:
        return self._url

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClientMaj":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _get(self, url: str):
        import httpx

        try:
            return self._client.get(url)
        except httpx.TimeoutException as exc:
            raise ErreurReseauMaj(f"Délai dépassé ({url}) : {exc}") from exc
        except httpx.HTTPError as exc:
            raise ErreurReseauMaj(f"Connexion impossible ({url}) : {exc}") from exc

    def recuperer_manifeste(self) -> Manifeste | None:
        """Télécharge manifeste + signature, vérifie la signature sur les octets
        bruts, puis parse. `None` si l'un des deux est en 404 (aucune release
        publiée, ou release en cours de publication) — ce n'est pas une erreur."""
        r = self._get(self._url)
        if r.status_code == 404:
            logger.info("Aucun manifeste de mise à jour publié (404)")
            return None
        if r.status_code >= 400:
            raise ErreurServeurMaj(f"Erreur serveur ({r.status_code}) sur le manifeste")
        octets = r.content

        rs = self._get(url_signature(self._url))
        if rs.status_code == 404:
            logger.warning("Manifeste présent mais signature absente (404) — ignoré")
            return None
        if rs.status_code >= 400:
            raise ErreurServeurMaj(f"Erreur serveur ({rs.status_code}) sur la signature")

        if not verifier_signature(octets, rs.text):
            # WARNING et non DEBUG : c'est exactement l'événement qu'un diagnostic doit
            # pouvoir retrouver (manifeste altéré, ou clé de signature changée).
            logger.warning("Signature du manifeste de mise à jour INVALIDE — ignoré")
            raise ErreurSignatureMaj("Signature du manifeste invalide")
        return Manifeste.depuis_json(octets)

    def telecharger(self, fichier: Fichier, dossier: Path,
                    progression: Callable[[int], None] | None = None) -> Path:
        """Télécharge `fichier` dans `dossier/<nom>` via un `.part`, SHA256 et taille
        calculés au fil de l'eau ; le `.part` est supprimé si l'intégrité échoue.
        `progression(pct)` reçoit 0..100."""
        import httpx

        dossier.mkdir(parents=True, exist_ok=True)
        destination = dossier / fichier.nom
        partiel = destination.with_name(destination.name + ".part")
        empreinte = hashlib.sha256()
        recu = 0
        dernier_pct = -1
        try:
            with self._client.stream("GET", fichier.url) as r:
                if r.status_code >= 400:
                    raise ErreurServeurMaj(f"Erreur serveur ({r.status_code}) sur {fichier.nom}")
                with partiel.open("wb") as f:
                    for bloc in r.iter_bytes(chunk_size=256 * 1024):
                        f.write(bloc)
                        empreinte.update(bloc)
                        recu += len(bloc)
                        if progression is not None and fichier.taille > 0:
                            pct = min(100, recu * 100 // fichier.taille)
                            if pct != dernier_pct:
                                dernier_pct = pct
                                progression(pct)
        except httpx.TimeoutException as exc:
            partiel.unlink(missing_ok=True)
            raise ErreurReseauMaj(f"Délai dépassé ({fichier.nom}) : {exc}") from exc
        except httpx.HTTPError as exc:
            partiel.unlink(missing_ok=True)
            raise ErreurReseauMaj(f"Connexion impossible ({fichier.nom}) : {exc}") from exc
        except BaseException:
            partiel.unlink(missing_ok=True)
            raise

        if recu != fichier.taille or empreinte.hexdigest() != fichier.sha256:
            partiel.unlink(missing_ok=True)
            raise ErreurIntegriteMaj(
                f"{fichier.nom} : {recu} octets / sha256 {empreinte.hexdigest()[:12]}… "
                f"≠ manifeste ({fichier.taille} octets / {fichier.sha256[:12]}…)")
        destination.unlink(missing_ok=True)
        partiel.replace(destination)
        logger.info("Mise à jour téléchargée et vérifiée : %s", destination)
        return destination


# ── Où tourne-t-on, peut-on installer ? ───────────────────────────────────────

def est_figee() -> bool:
    return bool(getattr(sys, "frozen", False))


def chemin_bundle_macos(executable: str | Path | None = None) -> Path | None:
    """`…/debriefMeet.app/Contents/MacOS/debriefMeet` → `…/debriefMeet.app` ;
    `None` hors d'un bundle (sources, chemin inattendu)."""
    chemin = Path(executable or sys.executable)
    try:
        bundle = chemin.parents[2]
    except IndexError:
        return None
    if bundle.suffix != ".app" or chemin.parent.name != "MacOS":
        return None
    return bundle


def installation_possible() -> bool:
    """True si `appliquer()` sait remplacer l'app sur ce poste : Windows figé
    (setup per-user, sans UAC) ; macOS figé **et** dossier parent du bundle
    inscriptible (`/Applications` est `root:admin 775` — un utilisateur non-admin
    ne peut pas y renommer : on ne tente rien en silence, l'UI propose le Finder).
    Linux et exécution depuis les sources : False (flux manuel)."""
    if not est_figee():
        return False
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        bundle = chemin_bundle_macos()
        return bundle is not None and os.access(bundle.parent, os.W_OK | os.X_OK)
    return False


# ── Passage de main à l'installeur (après app.exec()) ─────────────────────────

_fichier_demande: Path | None = None


def demander(fichier: Path) -> None:
    """Marque qu'`appliquer()` devra suivre la fermeture en cours."""
    global _fichier_demande
    _fichier_demande = Path(fichier)


def est_demande() -> bool:
    return _fichier_demande is not None


def script_lanceur_windows(pid: int, setup: Path, journal: Path) -> str:
    """`.cmd` qui attend la mort du process `pid` (libération du mutex
    `debriefMeet-instance` — le contrôle `AppMutex` d'Inno a lieu AVANT `[Code]`, on
    ne peut donc pas attendre côté setup) puis lance le setup en `/SILENT`.

    - `tasklist` en CSV + `findstr` sur `"debriefMeet.exe","<pid>"` : pas de faux
      positif sur un PID réutilisé par un autre process.
    - `ping -n 2` ≈ 1 s (pas `timeout` : refuse de tourner sans console), borne 120.
    - `/SILENT` et non `/VERYSILENT` : la copie dure 10-40 s, l'utilisateur doit voir
      qu'il se passe quelque chose, sinon il relance l'app à la main et entre en
      collision avec le setup. Pas de `/SUPPRESSMSGBOXES` : la boîte « debriefMeet
      est en cours d'exécution » reste un filet de sécurité interactif.
    - `/LOG` explicite dans le cache : sans valeur, Inno écrit dans `%TEMP%` sous un
      nom daté, introuvable pour l'export de diagnostic.
    """
    return (
        "@echo off\r\n"
        "rem Genere par debriefMeet (core/mise_a_jour) - attend la fin du processus\r\n"
        "rem parent (liberation du mutex debriefMeet-instance) puis lance le setup.\r\n"
        f'set "PID={int(pid)}"\r\n'
        f'set "SETUP={setup}"\r\n'
        f'set "JOURNAL={journal}"\r\n'
        "set /a n=0\r\n"
        ":attente\r\n"
        'tasklist /FI "PID eq %PID%" /FO CSV /NH 2>nul'
        f' | findstr /C:"\\"{NOM_EXECUTABLE_WINDOWS}\\",\\"%PID%\\"" >nul\r\n'
        "if errorlevel 1 goto lancer\r\n"
        "set /a n+=1\r\n"
        "if %n% geq 120 goto lancer\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto attente\r\n"
        ":lancer\r\n"
        f'start "" "%SETUP%" /SILENT /{PARAM_AUTOUPDATE}=1 /LOG="%JOURNAL%"\r\n'
    )


def script_remplacement_macos(pid: int, zip_: Path, app: Path, journal: Path) -> str:
    """`/bin/sh` POSIX qui remplace le bundle `app` par celui contenu dans `zip_`,
    après la mort du process `pid`.

    - Dossiers de travail créés **à côté** du bundle (même volume ⇒ les deux `mv`
      sont des `rename(2)` instantanés, avec retour arrière possible). Jamais
      `rm -rf` du bundle avant d'avoir le nouveau en place.
    - `ditto -x -k` et non `unzip` : liens symboliques des frameworks Qt et bits
      exécutables préservés. `codesign --verify --deep --strict` avant l'échange :
      un sceau corrompu donnerait un `Killed: 9` au lancement.
    - `open "$APP"` par chemin, jamais `open -a` (LaunchServices peut résoudre le nom
      vers une copie périmée : DMG encore monté, `~/Downloads`).
    - Aucun `xattr` : le zip téléchargé par httpx n'a pas de quarantaine, le bundle
      extrait non plus ⇒ pas d'écran Gatekeeper, et on ne touche pas au bundle signé.
    - Tout échec : l'ancienne app reste (ou revient) en place, le zip est montré
      dans le Finder, l'app est relancée.
    """
    nom = app.name
    return (
        "#!/bin/sh\n"
        "# Genere par debriefMeet (core/mise_a_jour) - remplace le bundle apres la mort du PID.\n"
        f"PID={int(pid)}\n"
        f"ZIP={shlex.quote(str(zip_))}\n"
        f"APP={shlex.quote(str(app))}\n"
        f"exec >>{shlex.quote(str(journal))} 2>&1\n"
        'echo "--- $(date) debut"\n'
        "relancer_et_sortir() {\n"
        '  [ -d "$APP" ] && open "$APP"\n'
        '  exit "$1"\n'
        "}\n"
        "repli() {\n"
        '  echo "ECHEC: $1"\n'
        '  [ -n "$NOUVEAU" ] && rm -rf "$NOUVEAU" 2>/dev/null\n'
        '  open -R "$ZIP"\n'
        "  relancer_et_sortir 1\n"
        "}\n"
        "i=0\n"
        'while kill -0 "$PID" 2>/dev/null; do\n'
        '  i=$((i+1)); [ "$i" -ge 600 ] && repli "le processus $PID ne se termine pas"\n'
        "  sleep 0.1\n"
        "done\n"
        'PARENT=$(dirname "$APP")\n'
        'NOUVEAU=$(mktemp -d "$PARENT/.debriefMeet-maj.XXXXXX") || repli "$PARENT non inscriptible"\n'
        'ditto -x -k "$ZIP" "$NOUVEAU" || repli "ditto -x -k"\n'
        f'[ -d "$NOUVEAU/{nom}" ] || repli "{nom} absent du zip"\n'
        f'codesign --verify --deep --strict "$NOUVEAU/{nom}" || repli "signature invalide"\n'
        'ANCIEN=$(mktemp -d "$PARENT/.debriefMeet-ancien.XXXXXX") || repli "mktemp ancien"\n'
        'mv "$APP" "$ANCIEN/" || repli "mv ancien"\n'
        f'if mv "$NOUVEAU/{nom}" "$APP"; then\n'
        '  rm -rf "$ANCIEN" "$NOUVEAU" "$ZIP"\n'
        '  echo "OK"\n'
        "else\n"
        f'  mv "$ANCIEN/{nom}" "$APP"\n'
        '  repli "mv nouveau (retour arriere effectue)"\n'
        "fi\n"
        "relancer_et_sortir 0\n"
    )


def appliquer() -> None:
    """Lance l'installeur détaché — à n'appeler qu'une fois `app.exec()` rendu
    (aboutToQuit exécutés, threads joints) : le process meurt juste après, et le
    script attend sa mort avant d'agir. Ne lève jamais."""
    fichier = _fichier_demande
    if fichier is None:
        return
    try:
        dossier = dossier_telechargements()
        dossier.mkdir(parents=True, exist_ok=True)
        journal = dossier / "installation.log"
        pid = os.getpid()
        if sys.platform == "win32":
            script = dossier / "installer.cmd"
            script.write_text(script_lanceur_windows(pid, fichier, journal), encoding="utf-8")
            # Environnement sans les variables du bootloader PyInstaller : l'app
            # relancée par `[Run]` les hériterait via cmd → setup → debriefMeet.exe.
            env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_")}
            subprocess.Popen(
                ["cmd.exe", "/c", str(script)],
                creationflags=(subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NEW_PROCESS_GROUP),
                # Jamais `{app}` : un cwd sous `{app}\_internal` ferait échouer
                # `[InstallDelete]`.
                cwd=str(dossier),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, env=env,
            )
        elif sys.platform == "darwin":
            app = chemin_bundle_macos()
            if app is None:
                logger.error("Mise à jour impossible : exécutable hors d'un bundle .app")
                return
            script = dossier / "installer.sh"
            script.write_text(script_remplacement_macos(pid, fichier, app, journal), encoding="utf-8")
            subprocess.Popen(
                ["/bin/sh", str(script)],
                start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        else:
            logger.error("Mise à jour automatique non prise en charge sur %s", sys.platform)
            return
        logger.info("Installation de la mise à jour programmée : %s", fichier)
    except OSError as exc:
        # Jamais bloquant : au pire l'utilisateur installe le fichier téléchargé à la main.
        logger.error("Mise à jour impossible (%s) — installer %s manuellement", exc, fichier)
