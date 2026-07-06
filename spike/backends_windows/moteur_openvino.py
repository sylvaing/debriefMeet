"""Moteur OpenVINO (GPU Intel ou CPU) — optimum-intel.

Interface : charger(taille) / transcrire(audio, langue) / liberer().
Gate : gate_openvino_gpu() (accel.py) → GPU Intel requis pour avoir un avantage.
Sans GPU Intel, le backend peut encore tourner en CPU (comparable à faster-whisper).
"""
from __future__ import annotations

import numpy as np

from spike.backends_windows import modeles
from spike.backends_windows.journalisation import journal
from debrief_meet.platform.interfaces import ResultatTranscription, Segment

SR = 16_000
BACKEND = "openvino"


class MoteurOpenVINO:
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
        # use_fast=False : le tokenizer fast plante sur certains repos turbo
        # (transformers 4.57 : `extra_special_tokens` mal formé → AttributeError
        # 'list' object has no attribute 'keys'). Le tokenizer lent évite ce chemin.
        self._processor = AutoProcessor.from_pretrained(chemin, use_fast=False)

    def transcrire(self, audio: np.ndarray, langue: str | None = None) -> ResultatTranscription:
        if self._modele is None or self._processor is None:
            raise RuntimeError("Modèle non chargé.")
        feats = self._processor(
            audio.astype(np.float32), sampling_rate=SR, return_tensors="pt",
        ).input_features
        kwargs: dict = {"task": "transcribe"}
        if langue:
            kwargs["language"] = langue
        ids = self._modele.generate(feats, **kwargs)
        texte = self._processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        segments = [Segment(0.0, len(audio) / SR, texte)] if texte else []
        return ResultatTranscription(texte, langue, segments)

    def liberer(self) -> None:
        self._modele = None
        self._processor = None

    def info_device(self) -> dict:
        return {"device_reel": self.device.lower(), "compute_type": "int8"}
