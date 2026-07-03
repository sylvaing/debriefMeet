"""Moteur DirectML (ONNX Runtime, iGPU Intel + AMD — tout GPU DX12).

Utilise onnxruntime-directml + optimum[onnxruntime].
Les modèles ONNX sont convertis à l'assemblage via `optimum-cli export onnx`.
Gate : gate_directml() (accel.py).
"""
from __future__ import annotations

import numpy as np

from spike.backends_windows import modeles
from spike.backends_windows.journalisation import journal
from debrief_meet.platform.interfaces import ResultatTranscription, Segment

SR = 16_000
BACKEND = "directml"
PROVIDER = "DmlExecutionProvider"


class MoteurDirectML:
    def __init__(self) -> None:
        self.taille: str | None = None
        self._modele = None
        self._processor = None

    def charger(self, taille: str) -> None:
        from pathlib import Path as _Path
        from optimum.onnxruntime import ORTModelForSpeechSeq2Seq
        from transformers import AutoProcessor
        self.taille = taille
        chemin = modeles.resoudre_directml(taille)
        journal().debug("directml : chargement %s (provider=%s, variante=fp16)", chemin, PROVIDER)
        # onnx-community repos stockent les fichiers ONNX dans un sous-dossier onnx/
        # Variante fp16 explicite (pas le défaut fp32) — cf. doc 18 §12.3.
        if (_Path(chemin) / "onnx").is_dir():
            self._modele = ORTModelForSpeechSeq2Seq.from_pretrained(
                chemin, subfolder="onnx", provider=PROVIDER, use_io_binding=True,
                **modeles.DIRECTML_FICHIERS_FP16)
        else:
            self._modele = ORTModelForSpeechSeq2Seq.from_pretrained(
                chemin, provider=PROVIDER, use_io_binding=True,
                **modeles.DIRECTML_FICHIERS_FP16)
        self._processor = AutoProcessor.from_pretrained(chemin)

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

    @staticmethod
    def info_device() -> dict:
        return {"device_reel": "dml", "compute_type": "int8_onnx"}
