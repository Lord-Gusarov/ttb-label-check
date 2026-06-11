"""Tesseract adapter (fast, tiny, CPU; weaker on rotated/creative layouts)."""

from __future__ import annotations

import numpy as np

from app.readers.base import Reader, register
from app.readers.preprocess import prepare_for_tesseract
from app.readers.types import WordBox


@register
class TesseractReader(Reader):
    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def _read(self, image: np.ndarray) -> list[WordBox]:
        import pytesseract
        from pytesseract import Output

        gray = prepare_for_tesseract(image)
        data = pytesseract.image_to_data(gray, output_type=Output.DICT)

        words: list[WordBox] = []
        for i, text in enumerate(data["text"]):
            text = text.strip()
            conf = float(data["conf"][i])
            if not text or conf < 0:
                continue
            x, y, w, h = (
                data["left"][i],
                data["top"][i],
                data["width"][i],
                data["height"][i],
            )
            words.append(
                WordBox(text=text, confidence=conf / 100.0, bbox=(x, y, x + w, y + h))
            )
        return words
