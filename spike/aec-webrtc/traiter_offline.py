#!/usr/bin/env python
"""
Spike AEC WebRTC — Étape 1 (offline).

Traite deux WAV pré-enregistrés sans casque :
  - micro  « Moi »          (near-end, signal) — pollué par l'écho des HP
  - système « Participants » (far-end, référence) — ce qui sort des HP

…et produit un micro nettoyé via l'AEC WebRTC, puis mesure les deux critères
go/no-go (§6 du spike) :
  - SIGNAL  : RMS de l'écho sur les phases « participants seuls », brut vs nettoyé,
              comparé au seuil anti-hallucination _SEUIL_RMS = 0.008.
  - MÉTIER  : transcription Whisper (MLX) brut vs nettoyé ;
              similarité difflib(« Moi nettoyé », « Participants ») — doit chuter ;
              WER(« Moi nettoyé », texte lu) — doit rester bas.

Deux modes :
  --demo                  : cas synthétique (réf bruitée + écho retardé + voix),
                            valide la chaîne AEC + alignement + mesures sans
                            enregistrement réel. Ne lance pas Whisper par défaut.
  --micro X --systeme Y   : traite les vrais enregistrements.

Hypothèses d'archi (cf. spike §5) : travail en 16 kHz mono ; référence système
downmixée ; alignement par cross-corrélation autour d'un clap initial ; dérive
du délai mesurée sur la durée.
"""
from __future__ import annotations

import argparse
import difflib
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.io import wavfile

# Aligné sur moteur_mlx.MoteurMLX._SEUIL_RMS — niveau sous lequel Whisper ne
# transcrirait de toute façon plus (gate anti-hallucination).
SEUIL_RMS = 0.008

SR_CIBLE = 16_000          # 16 kHz mono, comme ce qu'on envoie à Whisper
TRAME_MS = 10              # le module WebRTC impose des trames de 10 ms
TRAME = SR_CIBLE * TRAME_MS // 1000  # 160 échantillons


# ── E/S audio ──────────────────────────────────────────────────────────────

def lire_wav_mono16k(chemin: Path) -> np.ndarray:
    """Charge un WAV, downmix mono, resample à 16 kHz, float32 dans [-1, 1]."""
    sr, data = wavfile.read(chemin)
    data = data.astype(np.float64)
    if data.ndim == 2:                       # stéréo → mono
        data = data.mean(axis=1)
    # Normalisation selon le dtype d'origine
    if np.issubdtype(np.dtype(data.dtype), np.integer):
        pass  # déjà float64 ici ; on normalise via l'amplitude max théorique plus bas
    pic = np.max(np.abs(data)) or 1.0
    if pic > 1.5:                            # PCM entier → ramener dans [-1, 1]
        data = data / 32768.0
    if sr != SR_CIBLE:
        data = signal.resample_poly(data, SR_CIBLE, sr)
    return data.astype(np.float32)


def ecrire_wav_mono16k(chemin: Path, audio: np.ndarray) -> None:
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR_CIBLE)
        w.writeframes(pcm.tobytes())


# ── Alignement (cross-corrélation) ───────────────────────────────────────────

# Délai HP→micro physiquement plausible : latence acoustique + buffers. Au-delà,
# un pic de cross-corrélation est un faux verrou (bruit) → on borne la recherche.
DELAI_MAX_MS = 600


def _meilleur_lag(a: np.ndarray, b: np.ndarray, delai_max: int) -> int:
    """Lag maximisant |cross-corrélation| dans la plage [-delai_max, +delai_max]."""
    corr = np.abs(signal.correlate(a, b, mode="full"))
    lags = signal.correlation_lags(len(a), len(b), mode="full")
    plausible = np.abs(lags) <= delai_max
    corr = np.where(plausible, corr, -1.0)
    return int(lags[np.argmax(corr)])


def estimer_delai(mic: np.ndarray, ref: np.ndarray, fenetre_s: float = 3.0,
                  delai_max_ms: int = DELAI_MAX_MS) -> int:
    """Délai entier (échantillons) tel que ref[n-d] ≈ écho dans mic[n].

    Estimé par cross-corrélation sur les premières `fenetre_s` (autour du clap),
    bornée à ±`delai_max_ms` pour éviter les faux verrous quand le signal est faible.
    Positif = la référence arrive AVANT dans le micro (latence HP→micro)."""
    n = min(len(mic), len(ref), int(fenetre_s * SR_CIBLE))
    a = mic[:n] - mic[:n].mean()
    b = ref[:n] - ref[:n].mean()
    return _meilleur_lag(a, b, int(delai_max_ms / 1000 * SR_CIBLE))


def mesurer_derive(mic: np.ndarray, ref: np.ndarray, delai0: int,
                   n_fenetres: int = 12, fenetre_s: float = 2.0) -> list[int]:
    """Délai local estimé sur des fenêtres réparties sur toute la durée.

    La dispersion de ces délais autour de `delai0` = dérive d'horloge
    (PortAudio ~44,1 k vs SCK 48 k) — critique pour le temps réel (§5)."""
    n = min(len(mic), len(ref))
    taille = int(fenetre_s * SR_CIBLE)
    if n < taille * 2:
        return [delai0]
    delai_max = int(DELAI_MAX_MS / 1000 * SR_CIBLE)
    debuts = np.linspace(0, n - taille, n_fenetres).astype(int)
    delais = []
    for d in debuts:
        a = mic[d:d + taille] - mic[d:d + taille].mean()
        b = ref[d:d + taille] - ref[d:d + taille].mean()
        delais.append(_meilleur_lag(a, b, delai_max))
    return delais


# Le filtre d'écho d'AEC3 est CAUSAL : la référence doit PRÉCÉDER l'écho. Caler
# pile sur le pic de cross-corrélation laisse la queue de la réponse impulsionnelle
# à des lags négatifs qu'AEC3 ne peut pas modéliser → annulation médiocre (~−5 dB).
# Décaler la référence pour qu'elle mène de cette marge fait passer à ~−25 dB.
# (Mesuré sur la session live : plateau stable de −20 à −60 ms de marge.)
MARGE_LEAD_AEC_MS = 40


def aligner(mic: np.ndarray, ref: np.ndarray, delai: int) -> tuple[np.ndarray, np.ndarray]:
    """Décale la référence pour qu'elle soit synchrone avec l'écho dans le micro."""
    if delai > 0:
        ref = np.concatenate([np.zeros(delai, dtype=np.float32), ref])
    elif delai < 0:
        ref = ref[-delai:]
    n = min(len(mic), len(ref))
    return mic[:n], ref[:n]


def aligner_pour_aec(mic: np.ndarray, ref: np.ndarray, delai: int,
                     marge_ms: int = MARGE_LEAD_AEC_MS) -> tuple[np.ndarray, np.ndarray]:
    """Comme `aligner`, mais avance la référence de `marge_ms` pour qu'elle PRÉCÈDE
    l'écho — requis par le filtre causal d'AEC3 (cf. MARGE_LEAD_AEC_MS)."""
    return aligner(mic, ref, delai - int(marge_ms / 1000 * SR_CIBLE))


# ── AEC WebRTC ───────────────────────────────────────────────────────────────

def appliquer_aec(mic: np.ndarray, ref: np.ndarray, delai_systeme_ms: int = 0,
                  ns: bool = False) -> tuple[np.ndarray, float]:
    """Applique l'AEC3 (SDK LiveKit, APM WebRTC de prod) → micro nettoyé.

    Trames int16 10 ms ; référence (far) = système aligné.

    `ns` : activer le débruitage. **Désactivé par défaut** — sur l'enregistrement
    réel il dégradait nettement le WER de la voix (0.60 → 0.47) sans nécessité,
    l'écho restant sous le seuil avec l'AEC seule.

    Retourne (micro_nettoyé, facteur_temps_réel) où facteur < 1 = plus rapide
    que le temps réel.

    (Alternative AEC3 plus légère si l'empreinte LiveKit gêne à l'intégration :
    `pywebrtc-audio` — cf. tableau comparatif du README.)"""
    from livekit import rtc

    apm = rtc.AudioProcessingModule(
        echo_cancellation=True, noise_suppression=ns, high_pass_filter=True
    )
    apm.set_stream_delay_ms(delai_systeme_ms)

    n = (min(len(mic), len(ref)) // TRAME) * TRAME
    mic_i = (np.clip(mic[:n], -1, 1) * 32767).astype(np.int16)
    ref_i = (np.clip(ref[:n], -1, 1) * 32767).astype(np.int16)

    sortie = np.empty(n, dtype=np.int16)
    t0 = time.perf_counter()
    for i in range(0, n, TRAME):
        far = rtc.AudioFrame(data=ref_i[i:i + TRAME].tobytes(), sample_rate=SR_CIBLE,
                             num_channels=1, samples_per_channel=TRAME)
        near = rtc.AudioFrame(data=mic_i[i:i + TRAME].tobytes(), sample_rate=SR_CIBLE,
                              num_channels=1, samples_per_channel=TRAME)
        apm.process_reverse_stream(far)
        apm.process_stream(near)  # nettoie « near » en place
        sortie[i:i + TRAME] = np.frombuffer(near.data, dtype=np.int16)
    dt = time.perf_counter() - t0

    duree = n / SR_CIBLE
    return (sortie.astype(np.float32) / 32767.0), (dt / duree if duree else float("nan"))


# ── Mesures ──────────────────────────────────────────────────────────────────

def rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2))) if len(audio) else 0.0


def db(ratio: float) -> float:
    return 20.0 * np.log10(ratio) if ratio > 0 else float("-inf")


def wer(reference: str, hypothese: str) -> float:
    """Word Error Rate par distance d'édition sur les mots (insensible à la casse)."""
    r = reference.lower().split()
    h = hypothese.lower().split()
    if not r:
        return 0.0 if not h else 1.0
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=int)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cout = 0 if r[i - 1] == h[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cout)
    return d[len(r), len(h)] / len(r)


def similarite(a: str, b: str) -> float:
    """Similarité floue difflib (comme l'option B) — 1 = identique."""
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


# ── Phases ───────────────────────────────────────────────────────────────────

@dataclass
class Phase:
    nom: str       # "participants_seuls" | "moi_parle"
    debut: float   # s
    fin: float     # s


def charger_phases(chemin: Path) -> list[Phase]:
    """Format texte : une phase par ligne — `nom debut_s fin_s`."""
    phases = []
    for ligne in Path(chemin).read_text().splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        nom, deb, fin = ligne.split()
        phases.append(Phase(nom, float(deb), float(fin)))
    return phases


def extraire(audio: np.ndarray, p: Phase) -> np.ndarray:
    return audio[int(p.debut * SR_CIBLE):int(p.fin * SR_CIBLE)]


# ── Transcription (MLX) ──────────────────────────────────────────────────────

def transcrire(audio: np.ndarray, langue: str | None) -> str:
    import mlx_whisper
    res = mlx_whisper.transcribe(
        audio.astype(np.float32),
        path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
        language=langue,
        verbose=None,
        condition_on_previous_text=False,
    )
    return res["text"].strip()


# ── Rapport ──────────────────────────────────────────────────────────────────

@dataclass
class Rapport:
    delai_echantillons: int = 0
    delai_ms: float = 0.0
    derive_echantillons: list[int] = field(default_factory=list)
    facteur_temps_reel: float = 0.0
    rms_brut_echo: float | None = None
    rms_net_echo: float | None = None
    txt_participants: str = ""
    txt_moi_brut: str = ""
    txt_moi_net: str = ""
    sim_brut: float | None = None
    sim_net: float | None = None
    wer_brut: float | None = None
    wer_net: float | None = None

    def afficher(self) -> None:
        l = print
        l("\n" + "=" * 70)
        l("RAPPORT SPIKE AEC WEBRTC — Étape 1 (offline)")
        l("=" * 70)
        l("\n[ALIGNEMENT]")
        l(f"  délai estimé        : {self.delai_echantillons} éch. ({self.delai_ms:.1f} ms)")
        if self.derive_echantillons:
            d = self.derive_echantillons
            etendue_ms = (max(d) - min(d)) / SR_CIBLE * 1000
            l(f"  délai par fenêtre   : min={min(d)} max={max(d)} étendue={max(d)-min(d)} éch. "
              f"({etendue_ms:.1f} ms)")
            # < 5 ms sur la session = stable pour l'offline (AEC3 absorbe ce résidu).
            # Au-delà, ou extrapolé sur une longue session, à confirmer en temps réel (§7).
            l(f"  → dérive {'FAIBLE (stable)' if etendue_ms <= 5 else 'NOTABLE (à surveiller pour le temps réel)'}")
        l(f"\n[COÛT] facteur temps réel AEC : {self.facteur_temps_reel:.3f}× "
          f"({'OK, négligeable' if self.facteur_temps_reel < 0.5 else 'à vérifier'})")

        if self.rms_brut_echo is not None:
            l("\n[SIGNAL — phases « participants seuls »]")
            l(f"  RMS écho brut       : {self.rms_brut_echo:.5f}")
            l(f"  RMS écho nettoyé    : {self.rms_net_echo:.5f}")
            att = db(self.rms_net_echo / self.rms_brut_echo) if self.rms_brut_echo else float('nan')
            l(f"  atténuation         : {att:.1f} dB")
            l(f"  seuil anti-halluc.  : {SEUIL_RMS:.5f}")
            sous = self.rms_net_echo < SEUIL_RMS
            l(f"  → écho résiduel {'SOUS' if sous else 'AU-DESSUS'} du seuil  "
              f"[{'GO signal' if sous else 'NO-GO signal'}]")

        if self.txt_moi_net:
            l("\n[MÉTIER — transcriptions]")
            l(f"  Participants        : {self.txt_participants[:80]!r}")
            l(f"  Moi (brut)          : {self.txt_moi_brut[:80]!r}")
            l(f"  Moi (nettoyé)       : {self.txt_moi_net[:80]!r}")
            if self.sim_brut is not None:
                l(f"\n  similarité Moi↔Participants : brut={self.sim_brut:.3f} → nettoyé={self.sim_net:.3f} "
                  f"({'CHUTE (ok)' if self.sim_net < self.sim_brut - 0.1 else 'pas de chute nette (!)'})")
            if self.wer_brut is not None:
                l(f"  WER Moi vs texte lu         : brut={self.wer_brut:.3f} → nettoyé={self.wer_net:.3f} "
                  f"(amélioré de {self.wer_brut - self.wer_net:+.2f} vs brut)")
                l(f"    ⓘ jugement absolu de la préservation = comparer au WER d'un micro PROPRE "
                  f"(même texte sans écho).")
        l("\n" + "=" * 70)


# ── Mode démo (synthétique) ──────────────────────────────────────────────────

def generer_demo() -> tuple[np.ndarray, np.ndarray, list[Phase]]:
    """Cas synthétique 30 s : référence = bruit large bande (les « participants »),
    micro = écho retardé+atténué de la référence + voix utilisateur (sinus modulé)
    sur la 2ᵉ moitié. Clap initial dans les deux pistes pour l'alignement."""
    rng = np.random.default_rng(42)
    n = SR_CIBLE * 30
    t = np.arange(n) / SR_CIBLE

    ref = (rng.normal(0, 0.2, n)).astype(np.float32)
    # filtre passe-bande grossier pour ressembler à de la parole
    b, a = signal.butter(2, [300 / (SR_CIBLE / 2), 3400 / (SR_CIBLE / 2)], btype="band")
    ref = signal.lfilter(b, a, ref).astype(np.float32)
    ref *= 0.5 / (np.max(np.abs(ref)) or 1)

    # clap : transitoire net à 0,5 s dans la référence
    clap = np.zeros(n, dtype=np.float32)
    clap[SR_CIBLE // 2:SR_CIBLE // 2 + 20] = 0.9
    ref = ref + clap

    # écho dans le micro : référence retardée de 120 ms et atténuée (-12 dB)
    delai = int(0.120 * SR_CIBLE)
    echo = np.zeros(n, dtype=np.float32)
    echo[delai:] = ref[:n - delai] * 0.25

    # voix « Moi » : sinus modulé en amplitude sur 15–28 s
    voix = np.zeros(n, dtype=np.float32)
    seg = (t >= 15) & (t < 28)
    voix[seg] = (0.3 * np.sin(2 * np.pi * 220 * t[seg])
                 * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t[seg]))).astype(np.float32)

    mic = echo + voix + clap + rng.normal(0, 0.001, n).astype(np.float32)

    phases = [
        Phase("participants_seuls", 2.0, 14.0),
        Phase("moi_parle", 15.0, 28.0),
    ]
    return mic.astype(np.float32), ref.astype(np.float32), phases


# ── Pipeline principal ───────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Spike AEC WebRTC — traitement offline")
    ap.add_argument("--micro", type=Path, help="WAV micro (« Moi »)")
    ap.add_argument("--systeme", type=Path, help="WAV système (« Participants »)")
    ap.add_argument("--phases", type=Path, help="fichier des phases minutées")
    ap.add_argument("--texte-lu", type=Path, help="texte lu par l'utilisateur (vérité terrain WER)")
    ap.add_argument("--sortie", type=Path, default=Path("moi_nettoye.wav"),
                    help="WAV micro nettoyé en sortie")
    ap.add_argument("--ns", action="store_true",
                    help="activer le débruitage (désactivé par défaut : dégrade la voix)")
    ap.add_argument("--langue", default=None, help="code langue Whisper (ex. fr, en)")
    ap.add_argument("--demo", action="store_true", help="cas synthétique sans enregistrement")
    ap.add_argument("--transcrire", action="store_true",
                    help="lance Whisper MLX (lent) — sinon mesure signal seule")
    args = ap.parse_args()

    if args.demo:
        print("Mode DÉMO : cas synthétique (réf bruitée + écho 120 ms + voix).")
        mic, ref, phases = generer_demo()
    else:
        if not (args.micro and args.systeme):
            ap.error("hors --demo, --micro et --systeme sont requis.")
        print(f"Lecture micro={args.micro} / système={args.systeme}")
        mic = lire_wav_mono16k(args.micro)
        ref = lire_wav_mono16k(args.systeme)
        phases = charger_phases(args.phases) if args.phases else []

    rapport = Rapport()

    # 1. Alignement
    delai = estimer_delai(mic, ref)
    rapport.delai_echantillons = delai
    rapport.delai_ms = delai / SR_CIBLE * 1000
    rapport.derive_echantillons = mesurer_derive(mic, ref, delai)
    # Marge de lead pour le filtre causal d'AEC3 (cf. MARGE_LEAD_AEC_MS).
    mic_a, ref_a = aligner_pour_aec(mic, ref, delai)

    # 2. AEC
    print(f"AEC : LiveKit AEC3 (NS {'activé' if args.ns else 'désactivé'})")
    mic_net, facteur = appliquer_aec(mic_a, ref_a, ns=args.ns)
    rapport.facteur_temps_reel = facteur
    ecrire_wav_mono16k(args.sortie, mic_net)
    print(f"Micro nettoyé écrit → {args.sortie}")

    # 3. Mesure SIGNAL sur les phases « participants seuls »
    phases_echo = [p for p in phases if p.nom == "participants_seuls"]
    if phases_echo:
        brut = np.concatenate([extraire(mic_a, p) for p in phases_echo])
        net = np.concatenate([extraire(mic_net, p) for p in phases_echo])
        rapport.rms_brut_echo = rms(brut)
        rapport.rms_net_echo = rms(net)

    # 4. Mesure MÉTIER (transcription) — optionnelle (lente)
    if args.transcrire:
        print("Transcription Whisper MLX (brut, nettoyé, participants)…")
        rapport.txt_moi_brut = transcrire(mic_a, args.langue)
        rapport.txt_moi_net = transcrire(mic_net, args.langue)
        rapport.txt_participants = transcrire(ref_a, args.langue)
        rapport.sim_brut = similarite(rapport.txt_moi_brut, rapport.txt_participants)
        rapport.sim_net = similarite(rapport.txt_moi_net, rapport.txt_participants)
        if args.texte_lu and args.texte_lu.exists():
            ref_txt = args.texte_lu.read_text()
            rapport.wer_brut = wer(ref_txt, rapport.txt_moi_brut)
            rapport.wer_net = wer(ref_txt, rapport.txt_moi_net)

    rapport.afficher()
    return 0


if __name__ == "__main__":
    sys.exit(main())
