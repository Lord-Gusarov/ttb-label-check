import numpy as np
import pytest

from app.readers import registered_names
from app.readers.base import Reader
from app.readers.types import ReadResult, WordBox


def test_all_adapters_registered():
    assert {"rapidocr", "easyocr", "paddleocr"} <= set(registered_names())


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


def test_extract_returns_readresult_shape():
    res = _Stub("x", 0.7, "hello world").extract(_img())
    assert isinstance(res, ReadResult)
    assert res.confidence == pytest.approx(0.7)
