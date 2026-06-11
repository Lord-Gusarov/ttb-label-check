"""EasyOCR adapter (torch-based; optional bake-off entrant).

Only available when the `easyocr` extra is installed; otherwise `available()` is
False and the bench skips it. Downloads its detection/recognition models on first
use, so it needs network once at setup time (not a runtime hot-path dependency).
"""

from __future__ import annotations

import numpy as np

from app.readers.base import Reader, register
from app.readers.types import WordBox


@register
class EasyOcrReader(Reader):
    name = "easyocr"

    def __init__(self) -> None:
        self._engine = None

    def available(self) -> bool:
        try:
            import easyocr  # noqa: F401

            return True
        except Exception:
            return False

    def _ensure_engine(self):
        if self._engine is None:
            import easyocr

            self._engine = easyocr.Reader(["en"], gpu=False)
        return self._engine

    def _read(self, image: np.ndarray) -> list[WordBox]:
        engine = self._ensure_engine()
        results = engine.readtext(image)

        words: list[WordBox] = []
        for box, text, conf in results:
            text = (text or "").strip()
            if not text:
                continue
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            words.append(WordBox(text=text, confidence=float(conf), bbox=bbox))
        return words
