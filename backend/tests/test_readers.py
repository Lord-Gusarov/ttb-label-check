from pathlib import Path

import numpy as np
import pytest

from app.readers import registered_names
from app.readers.base import Reader
from app.readers.composite import FallbackReader
from app.readers.types import ReadResult, WordBox

CLEAN = Path(__file__).resolve().parent / "fixtures" / "labels" / "old_tom_clean.png"


def test_all_adapters_registered():
    assert {"rapidocr", "easyocr", "paddleocr", "vlm"} <= set(registered_names())


# --- Fallback gating logic (no OCR needed) ------------------------------------
class _Stub(Reader):
    def __init__(self, name, conf, text):
        self.name = name
        self._conf = conf
        self._text = text

    def available(self) -> bool:
        return True

    def _read(self, image):
        return [WordBox(text=self._text, confidence=self._conf, bbox=(0, 0, 1, 1))]


def _img():
    return np.zeros((4, 4, 3), dtype=np.uint8)


def test_fallback_not_triggered_when_primary_confident():
    primary = _Stub("primary", 0.9, "good")
    fallback = _Stub("fallback", 0.99, "better")
    res = FallbackReader(primary, fallback, threshold=0.55).extract(_img())
    assert res.engine == "primary"


def test_fallback_triggered_and_keeps_more_confident():
    primary = _Stub("primary", 0.3, "weak")
    fallback = _Stub("fallback", 0.8, "strong")
    res = FallbackReader(primary, fallback, threshold=0.55).extract(_img())
    assert res.engine == "fallback"
    assert "strong" in res.text


def test_fallback_keeps_primary_if_fallback_worse():
    primary = _Stub("primary", 0.3, "weak")
    fallback = _Stub("fallback", 0.1, "worse")
    res = FallbackReader(primary, fallback, threshold=0.55).extract(_img())
    assert res.engine == "primary"


def test_extract_returns_readresult_shape():
    res = _Stub("x", 0.7, "hello world").extract(_img())
    assert isinstance(res, ReadResult)
    assert res.confidence == pytest.approx(0.7)
