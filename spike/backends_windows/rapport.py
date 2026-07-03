"""Construction du rapport spike (JSON + Markdown + zip).

Schéma documenté dans docs/18-spike-backends-windows.md §6.
Clés de premier niveau : machine, libs, accelerateurs, audio, resultats[],
verdict_machine, synthese.
"""
from __future__ import annotations

import datetime
import json
import re
import zipfile
from pathlib import Path

from spike.backends_windows import VERSION_SPIKE
from spike.backends_windows.journalisation import journal

SEUIL_VIABLE = 1.0      # RTF soutenu < 1.0 → suit le temps réel
SEUIL_CONFORTABLE = 0.5

ORDRE_MODELES = ["small", "medium", "large-v3", "large-v3-turbo"]


def horodatage_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _slug(texte: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", (texte or "machine")).strip("-") or "machine"


def _rtf_soutenu(r: dict) -> float | None:
    valeurs = [v for v in (r.get("rtf_moyen"), r.get("rtf_fin")) if v is not None]
    return max(valeurs) if valeurs else None


# ── Verdict par machine ───────────────────────────────────────────────────────

def _meilleur_par_backend(resultats: list[dict]) -> dict:
    """Pour chaque backend, le meilleur couple (modèle, résultat) viable et non halluciné."""
    par_backend: dict[str, list[dict]] = {}
    for r in resultats:
        par_backend.setdefault(r["backend"], []).append(r)

    meilleurs: dict[str, dict | None] = {}
    for backend, lignes in par_backend.items():
        candidats = [
            r for r in lignes
            if r.get("statut") == "ok"
            and not r.get("hallucination", False)
            and _rtf_soutenu(r) is not None
            and _rtf_soutenu(r) < SEUIL_VIABLE
        ]
        if not candidats:
            meilleurs[backend] = None
            continue
        # Meilleur = plus grand modèle viable (WER le plus bas)
        candidats.sort(key=lambda r: (ORDRE_MODELES.index(r["modele"])
                                      if r["modele"] in ORDRE_MODELES else -1), reverse=True)
        meilleurs[backend] = candidats[0]
    return meilleurs


def calculer_verdict_machine(resultats: list[dict]) -> dict:
    """Détermine le meilleur couple (backend, modèle) par machine."""
    meilleurs = _meilleur_par_backend(resultats)
    global_meilleur: dict | None = None
    global_backend: str | None = None

    for backend, r in meilleurs.items():
        if r is None:
            continue
        if global_meilleur is None:
            global_meilleur = r
            global_backend = backend
            continue
        # Préférer le modèle le plus grand, à égalité le RTF le plus bas
        i_new = ORDRE_MODELES.index(r["modele"]) if r["modele"] in ORDRE_MODELES else -1
        i_cur = ORDRE_MODELES.index(global_meilleur["modele"]) if global_meilleur["modele"] in ORDRE_MODELES else -1
        if i_new > i_cur or (i_new == i_cur and (_rtf_soutenu(r) or 99) < (_rtf_soutenu(global_meilleur) or 99)):
            global_meilleur = r
            global_backend = backend

    if global_meilleur is None:
        return {"backend": None, "modele": None, "niveau": "insuffisant",
                "details": "Aucun backend ne suit le temps réel sur cette machine."}

    rtf = _rtf_soutenu(global_meilleur)
    niveau = "viable" if rtf is not None and rtf < SEUIL_CONFORTABLE else "limite"
    return {
        "backend": global_backend,
        "modele": global_meilleur["modele"],
        "rtf_soutenu": rtf,
        "wer": global_meilleur.get("wer"),
        "niveau": niveau,
        "details": (f"{global_backend} + {global_meilleur['modele']} : "
                    f"RTF soutenu {rtf:.3f}, "
                    + ("marge confortable." if niveau == "viable" else "viable, marge réduite.")),
    }


def construire_synthese(resultats: list[dict]) -> dict:
    """Synthèse par profil matériel (iGPU Intel / iGPU AMD / CPU seul)."""
    meilleurs = _meilleur_par_backend(resultats)

    def _fmt(r) -> str | None:
        if r is None:
            return None
        return f"{r['backend']} + {r['modele']} (RTF {_rtf_soutenu(r):.3f})"

    backends_embarquer = [b for b, r in meilleurs.items() if r is not None]
    intel = _fmt(meilleurs.get("openvino"))
    amd_vulkan = _fmt(meilleurs.get("vulkan"))
    directml = _fmt(meilleurs.get("directml"))
    cpu = _fmt(meilleurs.get("faster-whisper"))

    return {
        "igpu_intel": intel or directml or cpu or "insuffisant",
        "igpu_amd": amd_vulkan or directml or cpu or "insuffisant",
        "cpu_seul": cpu or "insuffisant",
        "backends_a_embarquer": backends_embarquer,
        "regle_selection": (
            "Détecter le fabricant iGPU au démarrage → "
            "Intel → OpenVINO (GPU) ; AMD → Vulkan (whisper.cpp) ; "
            "DirectML en repli si disponible sur les deux ; "
            "faster-whisper CPU en dernier recours."
        ),
    }


def construire_rapport(*, materiel: dict, libs: dict, accelerateurs: dict,
                       audio: dict, resultats: list[dict]) -> dict:
    verdict = calculer_verdict_machine(resultats)
    synthese = construire_synthese(resultats)
    return {
        "version_spike": VERSION_SPIKE,
        "horodatage": horodatage_iso(),
        "machine": materiel,
        "libs": libs,
        "accelerateurs": accelerateurs,
        "audio": audio,
        "resultats": resultats,
        "verdict_machine": verdict,
        "synthese": synthese,
    }


# ── Rendu Markdown ────────────────────────────────────────────────────────────

def rendre_markdown(rapport: dict) -> str:
    m = rapport["machine"]
    gpu = m.get("gpu", {})
    v = rapport["verdict_machine"]
    lignes = [
        f"# Spike backends Windows — {m.get('hostname')} ({m.get('os')})",
        "",
        f"- **Date** : {rapport['horodatage']}",
        f"- **OS** : {m.get('os_version')} ({m.get('arch')})",
        f"- **CPU** : {m.get('cpu')} — {m.get('cpu_cores', {}).get('logiques')} cœurs logiques",
        f"- **RAM** : {m.get('ram_gb')} Go",
        f"- **GPU** : {gpu.get('fabricant')} — {gpu.get('name')}",
        f"- **Alimentation** : {m.get('alimentation', {}).get('source')}",
        "",
        f"## Verdict : **{v['niveau'].upper()}** — {v.get('backend')} + {v.get('modele')}",
        "",
        f"> {v['details']}",
        "",
        "## Résultats par backend",
        "",
        "| Backend | Modèle | Device | RTF moy | RTF fin | WER | Hallu | RAM (Mo) | Statut |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in rapport["resultats"]:
        if r.get("statut") in ("indisponible", "erreur"):
            lignes.append(
                f"| {r['backend']} | {r['modele']} | — | — | — | — | — | — "
                f"| {r['statut']}: {r.get('erreur', '')[:60]} |")
        else:
            hallu = "⚠ OUI" if r.get("hallucination") else "non"
            lignes.append(
                f"| {r['backend']} | {r['modele']} | {r.get('device_reel')} "
                f"| {r.get('rtf_moyen')} | {r.get('rtf_fin')} | {r.get('wer')} "
                f"| {hallu} | {r.get('ram_pic_mb')} | {r['statut']} |")

    s = rapport["synthese"]
    lignes += [
        "",
        "## Synthèse par profil matériel",
        "",
        f"- **iGPU Intel** : {s['igpu_intel']}",
        f"- **iGPU AMD** : {s['igpu_amd']}",
        f"- **CPU seul** : {s['cpu_seul']}",
        f"- **Backends à embarquer** : {', '.join(s['backends_a_embarquer']) or 'aucun'}",
        "",
        f"> {s['regle_selection']}",
        "",
        "## Accélérateurs",
        "",
    ]
    for nom, a in rapport["accelerateurs"].items():
        ligne = f"- **{nom}** : {'disponible' if a.get('disponible') else 'non'}"
        if nom == "vulkan" and a.get("gpus"):
            noms = [f"{g.get('nom')} ({g.get('fabricant')})" for g in a["gpus"]]
            ligne += " — " + ", ".join(n for n in noms if n)
        lignes.append(ligne)

    return "\n".join(lignes) + "\n"


# ── Écriture & emballage ──────────────────────────────────────────────────────

def ecrire(rapport: dict, dossier: Path) -> dict:
    dossier.mkdir(parents=True, exist_ok=True)
    chemin_json = dossier / "rapport.json"
    chemin_md = dossier / "rapport.md"
    chemin_json.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    chemin_md.write_text(rendre_markdown(rapport), encoding="utf-8")
    return {"json": chemin_json, "md": chemin_md}


def nom_archive(materiel: dict) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"spike_backends_{_slug(materiel.get('hostname', ''))}" \
           f"_{_slug(materiel.get('os', ''))}_{ts}.zip"


def emballer(dossier: Path, materiel: dict, destination: Path | None = None) -> Path:
    dossier = Path(dossier)
    destination = Path(destination) if destination else dossier.parent / nom_archive(materiel)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        for fichier in sorted(dossier.rglob("*")):
            if fichier.name.startswith("_"):
                continue
            if fichier.is_file() and fichier.resolve() != destination.resolve():
                zf.write(fichier, fichier.relative_to(dossier))
    journal().info("Archive créée : %s", destination)
    return destination
