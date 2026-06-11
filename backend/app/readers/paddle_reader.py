"""PaddleOCR adapter (optional bake-off entrant).

Only available when the `paddle` extra is installed. PaddleOCR's detector handles
curved/polygon text regions well, which is why it's a strong entrant for creative
label layouts — but paddlepaddle is heavy, so it stays optional.

PaddleOCR's Python API changed substantially at 3.0: the constructor dropped
``use_angle_cls`` / ``show_log`` (now ``use_textline_orientation`` and silent by
default), and ``.ocr()`` was superseded by ``.predict()`` which returns a list of
``OCRResult`` dicts exposing parallel ``rec_texts`` / ``rec_scores`` / ``rec_polys``
arrays instead of the old ``[[box, (text, conf)], ...]`` nesting. This adapter targets
the 3.x API and falls back to the legacy call shape if an older paddleocr is installed.
"""

from __future__ import annotations

import numpy as np

from app.readers.base import Reader, register
from app.readers.types import WordBox


@register
class PaddleOcrReader(Reader):
    name = "paddleocr"

    def __init__(self) -> None:
        self._engine = None

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401

            return True
        except Exception:
            return False

    def _ensure_engine(self):
        if self._engine is None:
            from paddleocr import PaddleOCR

            # 3.x signature; angle/orientation handling keeps rotated lines readable,
            # while the doc-level orientation/unwarp stages are off (we feed flat
            # label crops, and those stages add latency + extra model downloads).
            self._engine = PaddleOCR(
                lang="en",
                use_textline_orientation=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        return self._engine

    @staticmethod
    def _bbox_from_poly(poly) -> tuple[int, int, int, int]:
        pts = np.asarray(poly, dtype=float).reshape(-1, 2)
        xs, ys = pts[:, 0], pts[:, 1]
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

    def _read(self, image: np.ndarray) -> list[WordBox]:
        engine = self._ensure_engine()

        # Prefer the 3.x predict() API; fall back to legacy ocr() if needed.
        results = engine.predict(image) if hasattr(engine, "predict") else None
        if results:
            words: list[WordBox] = []
            for res in results:
                texts = res["rec_texts"]
                scores = res.get("rec_scores", [1.0] * len(texts))
                polys = res.get("rec_polys")
                if polys is None or len(polys) == 0:
                    polys = res.get("rec_boxes", [None] * len(texts))
                for text, score, poly in zip(texts, scores, polys):
                    text = (text or "").strip()
                    if not text or poly is None:
                        continue
                    words.append(
                        WordBox(
                            text=text,
                            confidence=float(score),
                            bbox=self._bbox_from_poly(poly),
                        )
                    )
            return words

        # Legacy (<3.0) fallback: [[ [box, (text, conf)], ... ]]
        result = engine.ocr(image)
        if not result or result[0] is None:
            return []
        words = []
        for line in result[0]:
            box, (text, conf) = line
            text = (text or "").strip()
            if not text:
                continue
            words.append(
                WordBox(text=text, confidence=float(conf), bbox=self._bbox_from_poly(box))
            )
        return words
