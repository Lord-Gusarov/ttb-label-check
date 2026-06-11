"""RapidOCR adapter (PaddleOCR-class models on ONNX: small, offline, robust on angles).

Bundles its own ONNX models in the pip package — no network at runtime, so it fits
the egress-blocked constraint. Includes angle classification, which helps on the
rotated / creative-layout labels that trip up plain Tesseract.
"""

from __future__ import annotations

import numpy as np

from app.readers.base import Reader, register
from app.readers.types import WordBox


@register
class RapidOcrReader(Reader):
    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None  # constructed lazily on first read

    def available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401

            return True
        except Exception:
            return False

    def _ensure_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def _read(self, image: np.ndarray) -> list[WordBox]:
        engine = self._ensure_engine()
        result, _elapse = engine(image)
        if not result:
            return []

        words: list[WordBox] = []
        for box, text, score in result:
            text = (text or "").strip()
            if not text:
                continue
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            words.append(WordBox(text=text, confidence=float(score), bbox=bbox))
        return words
