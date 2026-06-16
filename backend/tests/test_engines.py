"""Smoke tests for the pluggable reader engines.

These are tolerant by design: heavy engines (easyocr / paddleocr / vlm) are optional,
so each test skips when the engine isn't ``available()`` on this host. What we DO assert
is the contract every adapter must honor — when an engine is installed it must read the
canonical clean label and recover the brand + warning as real ``WordBox`` objects with
sane bounding boxes. This is what lets the bake-off compare them apples-to-apples.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.readers import get_reader, registered_names
from app.readers.preprocess import load_image

CLEAN = Path(__file__).resolve().parent / "fixtures" / "labels" / "old_tom_clean.png"

# Engines that are always expected to be present (declared in the `readers` extra).
CORE_ENGINES = {"rapidocr"}
# Engines that are optional — tested only when installed.
OPTIONAL_ENGINES = {"easyocr", "paddleocr", "vlm"}


def _despaced(text: str) -> str:
    """Lowercase, alphanumeric-only — robust to line-level engines (e.g. rapidocr)
    that emit ``OLDTOMDISTILLERY`` with no inter-word spaces."""
    import re

    return re.sub(r"[^a-z0-9]", "", text.lower())


def test_all_adapters_registered():
    names = set(registered_names())
    assert CORE_ENGINES <= names
    assert OPTIONAL_ENGINES <= names


@pytest.mark.parametrize("name", sorted(CORE_ENGINES | OPTIONAL_ENGINES))
def test_engine_reads_clean_label(name: str):
    reader = get_reader(name)
    if not reader.available():
        pytest.skip(f"{name} not installed on this host")

    assert CLEAN.exists(), "clean fixture image missing"
    result = reader.extract(load_image(CLEAN))

    # Contract: produces words with valid, non-degenerate bounding boxes.
    assert result.words, f"{name} returned no words"
    for wb in result.words:
        x1, y1, x2, y2 = wb.bbox
        assert x2 >= x1 and y2 >= y1
        assert wb.text.strip()

    # Accuracy floor: the brand and the government warning must be recoverable.
    # De-spaced substring match so word-level and line-level engines are judged fairly.
    despaced = _despaced(result.text)
    assert "oldtomdistillery" in despaced, f"{name} missed the brand: {result.text!r}"
    assert "governmentwarning" in despaced, f"{name} missed the warning"
