"""Construction du rapport (schéma JSON identique tous OS) + verdict + emballage zip.

Le schéma JSON est documenté champ par champ dans docs/08-benchmark.md (clé
d'interprétation lors du dépouillement). Tout changement ici doit s'y refléter
(un test garde-fou compare les clés produites à la liste documentée).
"""
from __future__ import annotations

import datetime
import re
import zipfile
from pathlib import Path

from benchmark import VERSION_SCHEMA
from benchmark.journalisation import journal

# Ordre croissant de « taille » des modèles (pour modele_max_viable).
ORDRE_MODELES = ["small", "medium", "large-v3"]

SEUIL_CONFORTABLE = 0.5   # RTF en deçà duquel c'est confortable
SEUIL_VIABLE = 1.0        # RTF < 1.0 : suit le temps réel (mode réunion par tranches)


def horodatage_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(texte: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", (texte or "machine")).strip("-") or "machine"


def _rtf_soutenu(modele: dict) -> float | None:
    """RTF retenu pour la viabilité : le pire entre moyen et fin (anti-throttling)."""
    valeurs = [v for v in (modele.get("rtf_moyen"), modele.get("rtf_fin")) if v is not None]
    return max(valeurs) if valeurs else None


def calculer_verdict(transcription: list[dict]) -> dict:
    """Détermine le plus gros modèle viable (RTF soutenu < 1.0) et le niveau global."""
    viables = []
    for m in transcription:
        rtf = _rtf_soutenu(m)
        if rtf is not None and rtf < SEUIL_VIABLE and m.get("modele") in ORDRE_MODELES:
            viables.append(m["modele"])

    modele_max = None
    if viables:
        modele_max = max(viables, key=ORDRE_MODELES.index)

    if modele_max is None:
        niveau = "insuffisant"
        details = "Aucun modèle ne suit le temps réel (RTF ≥ 1.0) : machine insuffisante."
    elif modele_max == "large-v3":
        rtf_lv3 = _rtf_soutenu(next(m for m in transcription if m.get("modele") == "large-v3"))
        confortable = rtf_lv3 is not None and rtf_lv3 < SEUIL_CONFORTABLE
        niveau = "viable"
        details = (f"large-v3 fait tourner le temps réel (RTF {rtf_lv3})"
                   + (" — marge confortable." if confortable else " — viable, marge réduite."))
    else:
        niveau = "limite"
        details = (f"Seul {modele_max} suit le temps réel ; large-v3 trop lent. "
                   "Qualité moindre mais utilisable.")

    return {"modele_max_viable": modele_max, "niveau": niveau, "details": details}


def construire_rapport(*, materiel: dict, mode: dict, audio: dict,
                       transcription: list[dict], diarisation: list[dict],
                       capture: dict, accelerateurs: dict,
                       openvino: list[dict] | None = None,
                       observations: str = "") -> dict:
    return {
        "schema_version": VERSION_SCHEMA,
        "horodatage": horodatage_iso(),
        "machine": materiel,
        "mode": mode,
        "audio": audio,
        "transcription": transcription,
        "diarisation": diarisation,
        "openvino": openvino or [],
        "capture": capture,
        "accelerateurs": accelerateurs,
        "verdict": calculer_verdict(transcription),
        "observations": observations,
    }


# ── Rendu Markdown lisible ────────────────────────────────────────────────────

def rendre_markdown(rapport: dict) -> str:
    m = rapport["machine"]
    gpu = m.get("gpu", {})
    mode = rapport["mode"]
    v = rapport["verdict"]
    lignes = [
        f"# Benchmark debriefMeet — {m.get('hostname')} ({m.get('os')})",
        "",
        f"- **Date** : {rapport['horodatage']}",
        f"- **OS** : {m.get('os_version')} ({m.get('arch')})",
        f"- **CPU** : {m.get('cpu')} — {m.get('cpu_cores', {}).get('logiques')} cœurs logiques",
        f"- **RAM** : {m.get('ram_gb')} Go",
        f"- **GPU** : {gpu.get('type')} — {gpu.get('name')} "
        f"(VRAM {gpu.get('vram_mb')} Mo, CUDA {gpu.get('cuda')})",
        f"- **Alimentation** : {m.get('alimentation', {}).get('source')}",
        f"- **Mode** : moteur {mode.get('moteur')}, device {mode.get('device')}, "
        f"compute {mode.get('compute_type')}",
        "",
        f"## Verdict : **{v['niveau'].upper()}** (modèle max viable : {v['modele_max_viable']})",
        "",
        f"> {v['details']}",
        "",
        "## Transcription",
        "",
        "| Modèle | RTF moyen | RTF fin | WER | RAM pic (Mo) | VRAM pic (Mo) | Charge (s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in rapport["transcription"]:
        if "erreur" in t:
            lignes.append(f"| {t['modele']} | ÉCHEC : {t['erreur']} | | | | | |")
        else:
            lignes.append(
                f"| {t['modele']} | {t.get('rtf_moyen')} | {t.get('rtf_fin')} | "
                f"{t.get('wer')} | {t.get('ram_pic_mb')} | {t.get('vram_pic_mb')} | "
                f"{t.get('load_s')} |")
    lignes += ["", "## Diarisation", "",
               "| Moteur | RTF | Locuteurs | RAM pic (Mo) |", "|---|---|---|---|"]
    for d in rapport["diarisation"]:
        if "erreur" in d:
            lignes.append(f"| {d['moteur']} | ÉCHEC : {d['erreur']} | | |")
        else:
            lignes.append(f"| {d['moteur']} | {d.get('rtf')} | {d.get('n_locuteurs')} | "
                          f"{d.get('ram_pic_mb')} |")

    ov = rapport.get("openvino") or []
    if ov:
        lignes += ["", "## Transcription OpenVINO (GPU Intel)", "",
                   "> Comparatif sur GPU Intel, à confronter au sweep faster-whisper CPU ci-dessus.",
                   "",
                   "| Modèle | Device | RTF moyen | RTF fin | WER | RAM pic (Mo) | VRAM pic (Mo) |",
                   "|---|---|---|---|---|---|---|"]
        for t in ov:
            if "erreur" in t:
                lignes.append(f"| {t.get('modele')} | | ÉCHEC : {t['erreur']} | | | | |")
            else:
                lignes.append(
                    f"| {t.get('modele')} | {t.get('device')} | {t.get('rtf_moyen')} | "
                    f"{t.get('rtf_fin')} | {t.get('wer')} | {t.get('ram_pic_mb')} | "
                    f"{t.get('vram_pic_mb')} |")
        # Ligne comparative informative : RTF OpenVINO-GPU vs faster-whisper CPU par modèle.
        cpu = {t.get("modele"): t for t in rapport.get("transcription", []) if "erreur" not in t}
        comparaisons = []
        for t in ov:
            if "erreur" in t:
                continue
            ref = cpu.get(t.get("modele"))
            if ref and ref.get("rtf_moyen") and t.get("rtf_moyen"):
                comparaisons.append(
                    f"{t['modele']} : OpenVINO-GPU {t['rtf_moyen']} vs CPU {ref['rtf_moyen']}")
        if comparaisons:
            lignes += ["", "RTF (plus bas = plus rapide) — " + " ; ".join(comparaisons) + "."]

    cap = rapport["capture"]
    lignes += ["", "## Capture audio système & AEC", ""]
    yt = cap.get("youtube", {})
    lignes.append(f"- **YouTube (loopback)** : "
                  + ("son capté" if yt.get("son_capte") else
                     ("échec : " + yt["erreur"] if yt.get("erreur") else "non réalisé")))
    lv = cap.get("lecture_voix", {})
    if lv.get("realise"):
        lignes.append(f"- **Lecture voix** : WER avant AEC {lv.get('wer_avant_aec')}, "
                      f"après {lv.get('wer_apres_aec')}, "
                      f"atténuation écho {lv.get('attenuation_echo_db')} dB")
    aec = cap.get("aec_livekit", {})
    lignes.append(f"- **AEC livekit** : {'disponible' if aec.get('disponible') else 'indisponible'} "
                  f"(v{aec.get('version')}, {aec.get('plateforme_wheel')})")

    lignes += ["", "## Accélérateurs", ""]
    for nom, a in rapport["accelerateurs"].items():
        ligne = f"- **{nom}** : {'disponible' if a.get('disponible') else 'non'}"
        if nom == "vulkan" and a.get("gpus"):
            noms = [f"{g.get('nom')} ({g['fabricant']})" if g.get("fabricant") else g.get("nom")
                    for g in a["gpus"]]
            ligne += " — " + ", ".join(n for n in noms if n)
        lignes.append(ligne)

    if rapport.get("observations"):
        lignes += ["", "## Observations de l'utilisateur", "", rapport["observations"]]
    return "\n".join(lignes) + "\n"


# ── Écriture & emballage ──────────────────────────────────────────────────────

def ecrire(rapport: dict, dossier: Path) -> dict:
    """Écrit rapport.json + rapport.md dans `dossier`. Retourne les chemins."""
    import json

    dossier.mkdir(parents=True, exist_ok=True)
    chemin_json = dossier / "rapport.json"
    chemin_md = dossier / "rapport.md"
    chemin_json.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    chemin_md.write_text(rendre_markdown(rapport), encoding="utf-8")
    return {"json": chemin_json, "md": chemin_md}


def nom_archive(materiel: dict) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"bench_{_slug(materiel.get('hostname', ''))}_{_slug(materiel.get('os', ''))}_{ts}.zip"


def emballer(dossier: Path, materiel: dict, destination: Path | None = None) -> Path:
    """Emballe TOUT le contenu de `dossier` dans un unique zip à transmettre.

    C'est le seul fichier que l'utilisateur renvoie.
    """
    dossier = Path(dossier)
    destination = Path(destination) if destination else dossier.parent / nom_archive(materiel)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        for fichier in sorted(dossier.rglob("*")):
            # Exclut les fichiers temporaires `_*` (ex. _diar_pyannote.wav, ≈57 Mo) :
            # filet de sécurité si un temp n'a pas été nettoyé en amont.
            if fichier.name.startswith("_"):
                continue
            if fichier.is_file() and fichier.resolve() != destination.resolve():
                zf.write(fichier, fichier.relative_to(dossier))
    journal().info("Archive créée : %s", destination)
    return destination
