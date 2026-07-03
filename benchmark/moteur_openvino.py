"""Moteur de transcription OpenVINO (GPU Intel) pour le comparatif benchmark.

Sépare l'import lourd d'optimum-intel du reste : ce module ne s'importe
proprement que si `optimum-intel[openvino]` est présent (bundles Windows/Linux).
Sur les machines sans GPU Intel, il n'est jamais sollicité (cf. le gate
`sondes_accel.gpu_intel_disponible`).

Modèles : INT8 pré-convertis `OpenVINO/whisper-*-int8-ov` (cf. modeles.py).
Les tranches sont des fenêtres de 30 s à 16 kHz — exactement la fenêtre native
de Whisper, donc une passe `generate` par tranche.
"""
from __future__ import annotations

import numpy as np

from benchmark import modeles
from benchmark.journalisation import journal
from debrief_meet.platform.interfaces import ResultatTranscription, Segment

SR = 16_000


class MoteurOpenVINO:
    """Transcription Whisper via OpenVINO Runtime (optimum-intel).

    Interface identique à MoteurBench (charger/transcrire/liberer) pour se
    brancher sur le pipeline comme un moteur de plus.
    """

    def __init__(self, device: str = "GPU") -> None:
        self.device = device
        self.taille: str | None = None
        self._modele = None
        self._processor = None

    def charger(self, taille: str) -> None:
        from optimum.intel import OVModelForSpeechSeq2Seq
        from transformers import AutoProcessor

        self.taille = taille
        chemin = modeles.resoudre_openvino(taille)
        journal().debug("openvino : chargement %s sur device=%s", chemin, self.device)
        self._modele = OVModelForSpeechSeq2Seq.from_pretrained(chemin, device=self.device)
        self._processor = AutoProcessor.from_pretrained(chemin)

    def transcrire(self, audio: np.ndarray, langue: str | None = None) -> ResultatTranscription:
        if self._modele is None or self._processor is None:
            raise RuntimeError("Modèle non chargé : appeler charger() d'abord.")
        feats = self._processor(
            audio.astype(np.float32), sampling_rate=SR, return_tensors="pt",
        ).input_features
        kwargs: dict = {"task": "transcribe"}
        if langue:
            kwargs["language"] = langue
        ids = self._modele.generate(feats, **kwargs)
        texte = self._processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        # Une fenêtre de 30 s = un segment (suffisant pour RTF/WER ; pas de
        # timestamps fins, non nécessaires au comparatif).
        segments = [Segment(0.0, len(audio) / SR, texte)] if texte else []
        return ResultatTranscription(texte, langue, segments)

    def liberer(self) -> None:
        self._modele = None
        self._processor = None
