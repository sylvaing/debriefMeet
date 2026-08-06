from __future__ import annotations

import logging
import re
import threading
import wave
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)


class EcrivainJournal:
    """Écrit des entrées horodatées dans un fichier journal append-only (§12.2)."""

    def __init__(self, dossier: Path) -> None:
        self._dossier = dossier

    def ajouter_entree(self, texte: str, horodatage: datetime | None = None) -> Path:
        now = horodatage or datetime.now()
        chemin = self._dossier / now.strftime("%Y-%m-%d.md")
        self._dossier.mkdir(parents=True, exist_ok=True)

        avec_entete = not chemin.exists()
        with chemin.open("a", encoding="utf-8") as f:
            if avec_entete:
                f.write(f"# Activités — {now.strftime('%Y-%m-%d')}\n\n")
            f.write(f"## {now.strftime('%H:%M')}\n\n{texte.strip()}\n\n---\n\n")
        return chemin


def lister_enregistrements(dossier: Path) -> list[Path]:
    """Entrées de journal (`AAAA-MM-JJ.md`, à plat), triées du plus récent au plus
    ancien. Le layout réunion (1 dossier/réunion, docs/43) utilise `lister_reunions` —
    le journal reste un simple fichier par jour, sans dérivés à exclure."""
    if not dossier.exists():
        return []
    return sorted(dossier.glob("*.md"), reverse=True)


def lister_reunions(dossier: Path) -> list[Path]:
    """`transcription.md` de chaque sous-dossier de réunion (docs/43), triés du plus
    récent au plus ancien (tri lexical sur le nom de dossier = chronologique, le
    format horodaté étant zéro-paddé ISO)."""
    if not dossier.exists():
        return []
    out = [sous / "transcription.md" for sous in dossier.iterdir()
           if sous.is_dir() and (sous / "transcription.md").exists()]
    return sorted(out, key=lambda p: p.parent.name, reverse=True)


def chemin_cr_mistral(md: Path) -> Path:
    """Chemin du CR Mistral (`CR.md`, docs/42) associé à une transcription."""
    return md.with_name("CR.md")


def chemin_locuteurs(md: Path) -> Path:
    """Chemin du débrief locuteurs (`locuteurs.md`) associé à une transcription."""
    return md.with_name("locuteurs.md")


# Marqueur d'une réunion enregistrée en « audio seul » dont la transcription
# n'a pas encore été générée (mode transcription différée). Cf. docs/10.
MARQUEUR_EN_ATTENTE = "⏳ Enregistrement audio seul — transcription non générée."


def transcription_en_attente(md: Path) -> bool:
    """Vrai si le `.md` est un placeholder « audio seul » non encore transcrit."""
    try:
        return MARQUEUR_EN_ATTENTE in md.read_text(encoding="utf-8")
    except OSError:
        return False


def chemins_audio_reunion(md: Path) -> tuple[Path, Path]:
    """Chemins **sans extension** des 2 pistes retenues (Moi + Système), dans le même
    dossier que `transcription.md` (docs/43 — noms génériques fixes).

    L'extension (.opus ou .wav) est choisie par `EnregistreurAudioReunion` selon la
    présence de ffmpeg."""
    return md.with_name("moi"), md.with_name("systeme")


def pistes_audio_existantes(md: Path) -> list[Path]:
    """Fichiers audio retenus (`.opus`/`.wav`) présents à côté du `.md` (Moi + Système)."""
    out: list[Path] = []
    for base in chemins_audio_reunion(md):
        for ext in (".opus", ".wav"):
            p = base.with_suffix(ext)
            if p.exists():
                out.append(p)
    return out


# ── Métadonnées d'une réunion (titre éditable + durée) ─────────────────────────
#
# Le **dossier** de la réunion (AAAA-MM-JJ_HH-MM-SS[_slug-titre], docs/43) est
# l'identité stable : il porte la date/heure (et le titre, en miroir) et contient
# tous les fichiers génériques (transcription.md, moi/systeme, locuteurs.md, CR.md,
# bluemind.json). Le **titre** vit dans le H1 de `transcription.md` (source de
# vérité ; le nom du dossier n'est qu'un miroir maintenu par `renommer_dossier_reunion`
# à chaque changement) ; la **durée** dans un commentaire HTML invisible à la
# lecture. Cf. docs/14, docs/43.

_MOTIF_HORODATAGE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})")
_MOTIF_DATE_HEURE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
_MOTIF_DUREE = re.compile(r"<!-- duree_s: (\d+) -->")
_MOTIF_TRANCHE = re.compile(r"^## \d{2}:\d{2} \((\d{2}):(\d{2})\)", re.MULTILINE)
_PREFIXE_DEFAUT = "Réunion — "

# Caractères interdits par les systèmes de fichiers (Windows/macOS) + caractères de
# contrôle — retirés du slug. Accents CONSERVÉS (§3, docs/43) : le but est un nom de
# dossier lisible, pas un slug ASCII pur.
_CARACTERES_INTERDITS_SLUG = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
# Espaces + tirets (ASCII et unicode : en/em dash…) consécutifs → un seul séparateur.
_SEPARATEURS_SLUG = re.compile(r"[\s\-‐-―]+")


def slugifier_titre(titre: str, longueur_max: int = 60) -> str:
    """Convertit un titre en segment de nom de dossier (docs/43 §3).

    - espaces (et tirets, y compris unicode) → un seul tiret ;
    - caractères interdits par les systèmes de fichiers retirés : / \\ : * ? " < > |
      + caractères de contrôle et sauts de ligne ;
    - accents CONSERVÉS (é, à, ç… : macOS/Windows gèrent l'UTF-8) ;
    - tirets/points/espaces en tête et fin supprimés ;
    - tronqué à `longueur_max` caractères.

    Retourne "" si le titre est vide ou ne contient aucun caractère utile après
    nettoyage (dans ce cas le dossier reste horodaté seul)."""
    if not titre:
        return ""
    nettoye = _CARACTERES_INTERDITS_SLUG.sub("", titre)
    nettoye = _SEPARATEURS_SLUG.sub("-", nettoye)
    nettoye = nettoye.strip("-. \t")
    if not nettoye:
        return ""
    if len(nettoye) > longueur_max:
        nettoye = nettoye[:longueur_max].rstrip("-. ")
    return nettoye


def nom_dossier_reunion(debut: datetime, titre: str | None = None) -> str:
    """Nom du dossier d'une réunion : horodatage à la seconde + slug du titre si
    présent (docs/43 §2.1)."""
    base = debut.strftime("%Y-%m-%d_%H-%M-%S")
    slug = slugifier_titre(titre or "")
    return f"{base}_{slug}" if slug else base


def date_heure_reunion(md: Path) -> datetime | None:
    """Date+heure de début déduites du **nom du dossier parent**
    (`AAAA-MM-JJ_HH-MM-SS[_slug]`) ; None si le nom ne suit pas ce schéma (ex. une
    entrée de journal `AAAA-MM-JJ.md`, qui n'a pas de dossier dédié).

    Le motif n'est pas ancré en fin : un éventuel compteur de collision (`-2`, `-3`…
    ajouté en toute fin de nom, §2.2) est simplement ignoré."""
    tokens = md.parent.name.split("_")
    if len(tokens) < 2:
        return None
    m = _MOTIF_HORODATAGE.match(f"{tokens[0]}_{tokens[1]}")
    if not m:
        return None
    a, mo, j, h, mi, ss = m.groups()
    try:
        return datetime(int(a), int(mo), int(j), int(h), int(mi), int(ss))
    except ValueError:
        return None


def _prefixe_horodatage(nom_dossier: str) -> str:
    """Bloc horodaté du nom, slug exclu — conserve un éventuel compteur de collision
    pour ne pas fusionner deux réunions distinctes lors d'un renommage.
    `'2026-07-27_20-12-45_Ancien-titre'` -> `'2026-07-27_20-12-45'`."""
    tokens = nom_dossier.split("_")
    return "_".join(tokens[:2]) if len(tokens) >= 2 else nom_dossier


def renommer_dossier_reunion(md: Path, titre: str | None) -> Path:
    """Renomme le dossier pour refléter `titre` (ou horodatage seul si vide/None) et
    retourne le nouveau chemin de `transcription.md`. No-op (retourne `md`) si le nom
    ne change pas.

    ⚠️ Ne jamais appeler pendant un enregistrement actif (handles audio ouverts →
    échec du rename de dossier sous Windows, WinError 32). Cf. docs/43 §6.3 — le seul
    déclencheur en cours d'enregistrement (pré-association F3) crée le dossier déjà
    titré, donc cet appel y est toujours un no-op."""
    dossier = md.parent
    prefixe = _prefixe_horodatage(dossier.name)
    slug = slugifier_titre(titre or "")
    nouveau_nom = f"{prefixe}_{slug}" if slug else prefixe
    if nouveau_nom == dossier.name:
        return md
    cible = dossier.with_name(nouveau_nom)
    i = 2
    while cible.exists():
        cible = dossier.with_name(f"{nouveau_nom}-{i}")
        i += 1
    dossier.rename(cible)
    return cible / md.name


def _h1(texte: str) -> tuple[int, str] | None:
    """(index de ligne, contenu sans « # ») du premier titre H1, ou None."""
    for i, ligne in enumerate(texte.splitlines()):
        if ligne.startswith("# "):
            return i, ligne[2:].strip()
    return None


def titre_reunion(md: Path) -> str | None:
    """Titre **custom** de la réunion (H1 du .md), ou None si c'est le titre par défaut
    « Réunion — <date> » (= aucun titre saisi par l'utilisateur)."""
    try:
        texte = md.read_text(encoding="utf-8")
    except OSError:
        return None
    h1 = _h1(texte)
    if h1 is None:
        return None
    contenu = h1[1]
    if contenu.startswith(_PREFIXE_DEFAUT):
        reste = contenu[len(_PREFIXE_DEFAUT):]
        if _MOTIF_DATE_HEURE.match(reste):
            return None
    return contenu or None


def apercu_journal(md: Path, longueur: int = 80) -> str:
    """Aperçu court de la dernière entrée d'un fichier journal (colonne « note » de
    l'Historique, refonte design) — dernière ligne de texte utile, sans `#`/`##`/`---`."""
    try:
        texte = md.read_text(encoding="utf-8")
    except OSError:
        return ""
    lignes_utiles = [
        ligne.strip() for ligne in texte.splitlines()
        if ligne.strip() and not ligne.startswith("#") and ligne.strip() != "---"
    ]
    if not lignes_utiles:
        return ""
    apercu = lignes_utiles[-1]
    if len(apercu) > longueur:
        apercu = apercu[: longueur - 1].rstrip() + "…"
    return apercu


def definir_titre(md: Path, titre: str) -> None:
    """Réécrit le H1 du .md avec `titre`. Un titre vide **restaure** le titre par défaut
    « Réunion — <date> ». N'altère pas le reste du fichier (transcription, durée…)."""
    try:
        texte = md.read_text(encoding="utf-8")
    except OSError:
        return
    titre = titre.strip()
    if not titre:
        dh = date_heure_reunion(md)
        titre = _PREFIXE_DEFAUT + (dh.strftime("%Y-%m-%d %H:%M") if dh else md.parent.name)
    lignes = texte.splitlines(keepends=True)
    for i, ligne in enumerate(lignes):
        if ligne.startswith("# "):
            fin = "\n" if ligne.endswith("\n") else ""
            lignes[i] = f"# {titre}{fin}"
            md.write_text("".join(lignes), encoding="utf-8")
            return
    md.write_text(f"# {titre}\n\n{texte}", encoding="utf-8")


def definir_duree(md: Path, secondes: int) -> None:
    """Écrit (ou met à jour) la durée en secondes dans un commentaire HTML, juste après
    le H1. Invisible au rendu Markdown ; lu ensuite par `duree_reunion`."""
    try:
        texte = md.read_text(encoding="utf-8")
    except OSError:
        return
    marqueur = f"<!-- duree_s: {max(0, int(secondes))} -->"
    if _MOTIF_DUREE.search(texte):
        md.write_text(_MOTIF_DUREE.sub(marqueur, texte, count=1), encoding="utf-8")
        return
    lignes = texte.splitlines(keepends=True)
    for i, ligne in enumerate(lignes):
        if ligne.startswith("# "):
            if not ligne.endswith("\n"):
                lignes[i] = ligne + "\n"
            lignes.insert(i + 1, marqueur + "\n")
            md.write_text("".join(lignes), encoding="utf-8")
            return
    md.write_text(f"{marqueur}\n{texte}", encoding="utf-8")


def duree_reunion(md: Path) -> int | None:
    """Durée d'une réunion en secondes. Priorité : commentaire stocké → longueur de
    l'audio retenu (WAV) → offset de la dernière tranche transcrite → None."""
    try:
        texte = md.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _MOTIF_DUREE.search(texte)
    if m:
        return int(m.group(1))
    audio = _duree_audio_wav(md)
    if audio is not None:
        return audio
    tranches = _MOTIF_TRANCHE.findall(texte)
    if tranches:
        mm, ss = tranches[-1]
        return int(mm) * 60 + int(ss)
    return None


def _duree_audio_wav(md: Path) -> int | None:
    """Durée (s) de la plus longue piste WAV retenue ; None si aucune (les .opus
    sont ignorés ici : repli léger sans sous-processus, pour les réunions héritées)."""
    durees: list[float] = []
    for p in pistes_audio_existantes(md):
        if p.suffix != ".wav":
            continue
        try:
            with wave.open(str(p), "rb") as w:
                if w.getframerate():
                    durees.append(w.getnframes() / w.getframerate())
        except (OSError, wave.Error):
            continue
    return int(max(durees)) if durees else None


def formater_duree(secondes: int | None) -> str:
    """Durée lisible : « 32 min » sous l'heure, « 1 h 05 » au-delà, « — » si inconnue."""
    if secondes is None:
        return "—"
    minutes = int(secondes) // 60
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


_SR_AUDIO = 16_000


class ErreurFfmpegIntrouvable(RuntimeError):
    """ffmpeg requis (embarqué ou système) mais introuvable."""

    def __init__(self) -> None:
        super().__init__("ffmpeg requis pour relire l'audio Opus.")


def chemin_ffmpeg() -> str | None:
    """Chemin de l'exécutable ffmpeg à utiliser, ou None si introuvable.

    En app figée (bundle), le binaire LGPL embarqué est résolu via
    `ressources.chemin_ressource` — une app lancée depuis le Finder (macOS) ou en
    `console=False` (Windows) hérite d'un PATH minimal, donc `shutil.which`
    échouerait même si ffmpeg est installé sur la machine. Emplacement embarqué
    selon l'OS : `vendor/ffmpeg` (macOS, docs/16 §5.5) ou `ffmpeg/ffmpeg.exe`
    (Windows, docs/41). En dev, repli sur le PATH courant."""
    import shutil
    import sys

    from debrief_meet.core.ressources import chemin_ressource, est_figee

    if est_figee():
        if sys.platform == "win32":
            embarque = chemin_ressource("ffmpeg", "ffmpeg.exe")
        else:
            embarque = chemin_ressource("vendor", "ffmpeg")
        return str(embarque) if embarque.exists() else None
    return shutil.which("ffmpeg")


def _ffmpeg_present() -> bool:
    return chemin_ffmpeg() is not None


def prechauffer_ffmpeg() -> threading.Thread | None:
    """Exécute `ffmpeg -version` en arrière-plan, une fois, au lancement de l'app.

    Le premier spawn de ffmpeg après le lancement paie le scan antivirus du binaire
    embarqué (mesuré 4 à 7 s sur poste Windows, au moment de la création des écrivains
    Opus — soit en plein démarrage d'enregistrement, thread UI bloqué). Le payer ici,
    hors du chemin critique, rend le premier enregistrement aussi rapide que les
    suivants. Sans effet si ffmpeg est introuvable (le repli WAV ne passe pas par
    ffmpeg). Renvoie le thread de préchauffage (None si rien à faire) — les appelants
    l'ignorent, les tests peuvent le joindre."""
    exe = chemin_ffmpeg()
    if exe is None:
        logger.debug("Préchauffage ffmpeg : binaire introuvable — ignoré")
        return None

    def _chauffer() -> None:
        import subprocess
        try:
            subprocess.run(
                [exe, "-version"], timeout=60,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            logger.debug("Préchauffage ffmpeg terminé (%s)", exe)
        except Exception:
            logger.debug("Préchauffage ffmpeg échoué (sans gravité)", exc_info=True)

    thread = threading.Thread(target=_chauffer, name="prechauffe-ffmpeg", daemon=True)
    thread.start()
    return thread


class _PisteWriter:
    """Une piste : encode Opus en streaming via ffmpeg, ou WAV (repli sans ffmpeg)."""

    def __init__(self, base: Path, mode: str, debit_kbps: int) -> None:
        base.parent.mkdir(parents=True, exist_ok=True)
        self._mode = mode
        if mode == "opus":
            self.chemin = base.with_name(base.name + ".opus")
            import subprocess
            exe = chemin_ffmpeg()
            if exe is None:
                raise ErreurFfmpegIntrouvable()
            self._proc = subprocess.Popen(
                [exe, "-y", "-loglevel", "error",
                 "-f", "f32le", "-ar", str(_SR_AUDIO), "-ac", "1", "-i", "pipe:0",
                 "-c:a", "libopus", "-b:a", f"{debit_kbps}k", str(self.chemin)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._wav = None
        else:
            self.chemin = base.with_name(base.name + ".wav")
            self._proc = None
            self._wav = wave.open(str(self.chemin), "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(_SR_AUDIO)

    def ecrire(self, audio_16k: "np.ndarray | None") -> None:
        if audio_16k is None or len(audio_16k) == 0:
            return
        import numpy as np
        a = np.clip(audio_16k, -1.0, 1.0)
        if self._mode == "opus":
            try:
                self._proc.stdin.write(a.astype(np.float32).tobytes())
            except (BrokenPipeError, OSError):
                pass
        else:
            self._wav.writeframes((a * 32767).astype(np.int16).tobytes())

    def fermer(self) -> None:
        if self._mode == "opus" and self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=15)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        elif self._wav is not None:
            try:
                self._wav.close()
            except Exception:
                pass


class EnregistreurAudioReunion:
    """Écrit en continu (streaming, faible mémoire) les pistes Moi + Système, en
    **Opus 16 kHz mono** (via ffmpeg) ou **WAV** en repli si ffmpeg est absent.

    Pour la passe finale de diarization (cf. docs/07). Chaque piste est optionnelle.
    `format` : "auto" (Opus si ffmpeg, sinon WAV), "opus" ou "wav"."""

    SR = _SR_AUDIO

    def __init__(self, base_moi: Path | None, base_systeme: Path | None,
                 format: str = "auto", debit_kbps: int = 24) -> None:
        self.format = "opus" if (format == "opus" or (format == "auto" and _ffmpeg_present())) else "wav"
        self._debit_kbps = debit_kbps
        logger.debug("Rétention audio réunion : format=%s, ffmpeg=%s",
                     self.format, chemin_ffmpeg() or "absent → WAV")
        self._moi = _PisteWriter(base_moi, self.format, debit_kbps) if base_moi else None
        self._systeme = _PisteWriter(base_systeme, self.format, debit_kbps) if base_systeme else None
        # Chemins conservés même après terminer() (utiles à la passe finale).
        self.chemin_moi: Path | None = self._moi.chemin if self._moi else None
        self.chemin_systeme: Path | None = self._systeme.chemin if self._systeme else None

    def activer_moi(self, base: Path) -> None:
        """Attache la piste Moi en cours de session (récupération tardive du micro,
        cf. docs/25). No-op si la piste existe déjà."""
        if self._moi is None:
            self._moi = _PisteWriter(base, self.format, self._debit_kbps)
            self.chemin_moi = self._moi.chemin

    def ajouter_moi(self, audio_16k: "np.ndarray") -> None:
        if self._moi is not None:
            self._moi.ecrire(audio_16k)

    def ajouter_systeme(self, audio_16k: "np.ndarray") -> None:
        if self._systeme is not None:
            self._systeme.ecrire(audio_16k)

    def terminer(self) -> None:
        for p in (self._moi, self._systeme):
            if p is not None:
                p.fermer()
        self._moi = self._systeme = None


def chemin_reunion(dossier: Path, debut: datetime, titre: str | None = None) -> Path:
    """Chemin `<dossier>/<nom[-N]>/transcription.md` **unique** pour une nouvelle
    réunion (docs/43 — 1 dossier/réunion). Le nom du sous-dossier est horodaté à la
    seconde, et porte un slug du titre si `titre` est fourni (démarrage pré-associé,
    docs/40 §8). Si le dossier cible existe déjà (collision quasi impossible à la
    seconde), suffixe `-2`, `-3`, … à la toute fin du nom.

    Ne crée pas le dossier ici : `EcrivainReunion.creer()`/`creer_placeholder()` le
    fait via `parent.mkdir(parents=True, exist_ok=True)`."""
    nom = nom_dossier_reunion(debut, titre)
    cible = dossier / nom
    i = 2
    while cible.exists():
        cible = dossier / f"{nom}-{i}"
        i += 1
    return cible / "transcription.md"


class EcrivainReunion:
    def __init__(self, chemin: Path, debut: datetime) -> None:
        self._chemin = chemin
        self._debut = debut

    def creer(self, avec_systeme: bool = True, avec_micro: bool = True) -> None:
        self._chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._chemin.open("w", encoding="utf-8") as f:
            f.write(f"# Réunion — {self._debut.strftime('%Y-%m-%d %H:%M')}\n\n")
            if not avec_systeme:
                f.write("> ⚠️ Audio système non disponible — transcription micro uniquement.\n")
            if not avec_micro:
                f.write("> ⚠️ Microphone non disponible — transcription audio système uniquement.\n")
            f.write("\n")

    def creer_placeholder(self) -> None:
        """Crée un `.md` « audio seul » : en-tête + marqueur de transcription à générer.

        Mode enregistrement seul (docs/10) : l'audio est retenu à côté, la transcription
        sera lancée plus tard depuis l'Historique."""
        self._chemin.parent.mkdir(parents=True, exist_ok=True)
        with self._chemin.open("w", encoding="utf-8") as f:
            f.write(f"# Réunion — {self._debut.strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"> {MARQUEUR_EN_ATTENTE}\n\n")

    def ajouter_tranche(
        self,
        texte_moi: str,
        texte_participants: str,
        offset_s: float,
        segments_moi: "list[tuple[float, str]] | None" = None,
        segments_participants: "list[tuple[float, str]] | None" = None,
    ) -> None:
        if not texte_moi.strip() and not texte_participants.strip():
            return
        heure_tranche = self._debut + timedelta(seconds=offset_s)
        hh_mm = heure_tranche.strftime("%H:%M")
        total_s = int(offset_s)
        mm = total_s // 60
        ss = total_s % 60
        elapsed = f"{mm:02d}:{ss:02d}"
        blocs = _entrelaces(
            texte_moi.strip(), texte_participants.strip(),
            segments_moi or [], segments_participants or [],
        )
        with self._chemin.open("a", encoding="utf-8") as f:
            f.write(f"---\n\n## {hh_mm} ({elapsed})\n\n")
            for locuteur, texte in blocs:
                f.write(f"**{locuteur} :** {texte}\n\n")

    @property
    def chemin(self) -> Path:
        return self._chemin


def _entrelaces(
    texte_moi: str,
    texte_participants: str,
    segments_moi: "list[tuple[float, str]]",
    segments_participants: "list[tuple[float, str]]",
) -> "list[tuple[str, str]]":
    """Entrelace les segments micro et système par timestamp.

    Si des segments sont disponibles (Whisper retourne des timestamps),
    on trie par début et on groupe les prises de parole consécutives du
    même locuteur. Sinon, on retombe sur les textes bruts.
    """
    if not segments_moi and not segments_participants:
        blocs = []
        if texte_moi:
            blocs.append(("Moi", texte_moi))
        if texte_participants:
            blocs.append(("Participants", texte_participants))
        return blocs

    tous = [(debut, "Moi", texte.strip()) for debut, texte in segments_moi if texte.strip()]
    tous += [(debut, "Participants", texte.strip()) for debut, texte in segments_participants if texte.strip()]
    tous.sort(key=lambda x: x[0])

    # Grouper les segments consécutifs du même locuteur
    groupes: list[list[str]] = []
    for _, locuteur, texte in tous:
        if groupes and groupes[-1][0] == locuteur:
            groupes[-1][1] += " " + texte
        else:
            groupes.append([locuteur, texte])
    return [(g[0], g[1]) for g in groupes]
